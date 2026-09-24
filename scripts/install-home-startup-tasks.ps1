param(
    [string]$PythonPath = "",
    [switch]$AllowLiveExecution,
    [switch]$SkipStart
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ApiRunnerPath = Join-Path $PSScriptRoot "run-home-api-task.ps1"
$WorkerRunnerPath = Join-Path $PSScriptRoot "run-live-worker-task.ps1"
$PowerShellPath = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$CurrentIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$CurrentUser = $CurrentIdentity.Name
$Principal = New-Object System.Security.Principal.WindowsPrincipal($CurrentIdentity)

if (-not $Principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an elevated PowerShell window (Run as administrator)."
}
if ([System.Diagnostics.Process]::GetCurrentProcess().SessionId -eq 0) {
    throw "Run this script inside the interactive Windows desktop session, not Session 0."
}

if (-not $PythonPath) {
    $PythonPath = (& python -c "import sys; print(sys.executable)").Trim()
}
$PythonPath = (Resolve-Path -LiteralPath $PythonPath).Path

$RequiredFiles = @(
    $ApiRunnerPath,
    $WorkerRunnerPath,
    (Join-Path $Root ".env.api"),
    (Join-Path $Root ".env.exness"),
    (Join-Path $Root ".env.ftmo"),
    (Join-Path $Root "var\trading.sqlite3"),
    (Join-Path $Root "frontend\dist\index.html")
)
foreach ($Path in $RequiredFiles) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required file not found: $Path"
    }
}
$DatabasePath = Join-Path $Root "var\trading.sqlite3"
$DatabaseCheck = @'
import sqlite3, sys
path = sys.argv[1]
with sqlite3.connect(path) as conn:
    rows = conn.execute("PRAGMA quick_check").fetchall()
if rows != [("ok",)]:
    print(rows[0][0] if rows else "quick_check returned no result")
    raise SystemExit(2)
print("ok")
'@
$DatabaseResult = $DatabaseCheck | & $PythonPath - $DatabasePath 2>&1
if ($LASTEXITCODE -ne 0 -or ($DatabaseResult | Select-Object -Last 1) -ne "ok") {
    throw "Database integrity check failed. Restore a clean SQLite backup before enabling startup tasks. $DatabaseResult"
}

function Get-DotEnvValue {
    param(
        [Parameter(Mandatory=$true)][string]$Path,
        [Parameter(Mandatory=$true)][string]$Name
    )
    $Pattern = "^\s*" + [regex]::Escape($Name) + "\s*=\s*(.*)\s*$"
    foreach ($Line in Get-Content -LiteralPath $Path) {
        if ($Line -match $Pattern) {
            return $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
    return $null
}

$Workers = @(
    [pscustomobject]@{ Name = "Exness"; TaskName = "SemiBotTrading-ExnessWorker"; EnvFile = (Join-Path $Root ".env.exness") },
    [pscustomobject]@{ Name = "FTMO"; TaskName = "SemiBotTrading-FTMOWorker"; EnvFile = (Join-Path $Root ".env.ftmo") }
)
foreach ($Worker in $Workers) {
    $TerminalPath = Get-DotEnvValue -Path $Worker.EnvFile -Name "MT5_PATH"
    if (-not $TerminalPath -or -not (Test-Path -LiteralPath $TerminalPath -PathType Leaf)) {
        throw "$($Worker.Name) MT5_PATH is missing or invalid: $TerminalPath"
    }
    $ExecutionEnabled = Get-DotEnvValue -Path $Worker.EnvFile -Name "EXECUTION_ENABLED"
    if ($ExecutionEnabled -match "^(?i:true|1|yes|on)$" -and -not $AllowLiveExecution) {
        throw "$($Worker.Name) has EXECUTION_ENABLED=true. Review the account and database, then rerun with -AllowLiveExecution to acknowledge live order execution."
    }
}

$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $CurrentUser
$Settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries
$TaskPrincipal = New-ScheduledTaskPrincipal -UserId $CurrentUser -LogonType Interactive -RunLevel Highest

$TaskSpecs = @(
    [pscustomobject]@{
        TaskName = "SemiBotTrading-API"
        Arguments = '-NoLogo -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}" -PythonPath "{1}"' -f $ApiRunnerPath, $PythonPath
    }
)
foreach ($Worker in $Workers) {
    $TaskSpecs += [pscustomobject]@{
        TaskName = $Worker.TaskName
        Arguments = '-NoLogo -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}" -WorkerName "{1}" -EnvFile "{2}" -PythonPath "{3}" -StartupDelaySeconds 20' -f $WorkerRunnerPath, $Worker.Name, $Worker.EnvFile, $PythonPath
    }
}

foreach ($Spec in $TaskSpecs) {
    $Existing = Get-ScheduledTask -TaskName $Spec.TaskName -ErrorAction SilentlyContinue
    if ($Existing -and $Existing.State -notin @("Ready", "Disabled")) {
        Stop-ScheduledTask -TaskName $Spec.TaskName
    }
    $Action = New-ScheduledTaskAction -Execute $PowerShellPath -Argument $Spec.Arguments -WorkingDirectory $Root
    $Task = New-ScheduledTask -Action $Action -Trigger $Trigger -Settings $Settings -Principal $TaskPrincipal
    Register-ScheduledTask -TaskName $Spec.TaskName -InputObject $Task -Force | Out-Null
    Write-Host "Registered: $($Spec.TaskName)" -ForegroundColor Green
}

foreach ($LegacyServiceName in @("BotWorker", "BotWorkerFTMO")) {
    $LegacyService = Get-Service -Name $LegacyServiceName -ErrorAction SilentlyContinue
    if ($LegacyService) {
        if ($LegacyService.Status -ne "Stopped") {
            Stop-Service -Name $LegacyServiceName -Force
        }
        Set-Service -Name $LegacyServiceName -StartupType Disabled
    }
}

if (-not $SkipStart) {
    foreach ($Spec in $TaskSpecs) {
        Start-ScheduledTask -TaskName $Spec.TaskName
    }
    Start-Sleep -Seconds 3
}

$TaskSpecs | ForEach-Object {
    $Task = Get-ScheduledTask -TaskName $_.TaskName
    $Info = Get-ScheduledTaskInfo -TaskName $_.TaskName
    [pscustomobject]@{
        TaskName = $_.TaskName
        State = $Task.State
        LastTaskResult = $Info.LastTaskResult
    }
} | Format-Table -AutoSize

Write-Host "API (including the built frontend) and all workers start at Windows logon. Disconnecting the desktop is safe; signing out stops the interactive tasks." -ForegroundColor Cyan
