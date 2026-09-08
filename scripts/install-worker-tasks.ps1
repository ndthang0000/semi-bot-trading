param(
    [string]$PythonPath = "",
    [switch]$SkipStart
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RunnerPath = Join-Path $PSScriptRoot "run-live-worker-task.ps1"
$PowerShellPath = [System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
$CurrentIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$CurrentUser = $CurrentIdentity.Name
$Principal = New-Object System.Security.Principal.WindowsPrincipal($CurrentIdentity)
$IsAdministrator = $Principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)

$Workers = @(
    [pscustomobject]@{
        Name = "Exness"
        TaskName = "SemiBotTrading-ExnessWorker"
        EnvFile = (Join-Path $Root ".env.exness")
        LegacyService = "BotWorker"
    },
    [pscustomobject]@{
        Name = "FTMO"
        TaskName = "SemiBotTrading-FTMOWorker"
        EnvFile = (Join-Path $Root ".env.ftmo")
        LegacyService = "BotWorkerFTMO"
    }
)

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

function Disable-LegacyWorkerService {
    param([Parameter(Mandatory=$true)][string]$ServiceName)

    $Service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($null -eq $Service) {
        return
    }
    if ($Service.Status -ne "Stopped") {
        Stop-Service -Name $ServiceName -Force
    }
    Set-Service -Name $ServiceName -StartupType Disabled
    Write-Host "Disabled legacy WinSW service: $ServiceName" -ForegroundColor Yellow
}

function Stop-ExistingWorkerTask {
    param([Parameter(Mandatory=$true)][string]$TaskName)

    $Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -eq $Task -or $Task.State -eq "Ready" -or $Task.State -eq "Disabled") {
        return
    }

    Stop-ScheduledTask -TaskName $TaskName
    for ($Attempt = 0; $Attempt -lt 20; $Attempt++) {
        Start-Sleep -Milliseconds 500
        $Task = Get-ScheduledTask -TaskName $TaskName
        if ($Task.State -eq "Ready" -or $Task.State -eq "Disabled") {
            Write-Host "Stopped existing scheduled task: $TaskName" -ForegroundColor Yellow
            return
        }
    }
    throw "Scheduled task '$TaskName' did not stop within 10 seconds."
}

if (-not $IsAdministrator) {
    throw "Run this script from an elevated PowerShell window (Run as administrator)."
}

$CurrentSessionId = [System.Diagnostics.Process]::GetCurrentProcess().SessionId
if ($CurrentSessionId -eq 0) {
    throw "Run this script inside the Administrator desktop/RDP session, not from Windows Session 0."
}

if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $PythonPath = (Get-Command python -ErrorAction Stop).Source
}
$PythonPath = (Resolve-Path -LiteralPath $PythonPath).Path

if (-not (Test-Path -LiteralPath $RunnerPath -PathType Leaf)) {
    throw "Scheduled-task runner not found: $RunnerPath"
}
foreach ($Worker in $Workers) {
    if (-not (Test-Path -LiteralPath $Worker.EnvFile -PathType Leaf)) {
        throw "Missing $($Worker.Name) environment file: $($Worker.EnvFile)"
    }
}

Write-Host "Installing live-worker tasks for $CurrentUser in Windows Session $CurrentSessionId" -ForegroundColor Cyan
Write-Host "Python: $PythonPath"

foreach ($Worker in $Workers) {
    Disable-LegacyWorkerService -ServiceName $Worker.LegacyService
    Stop-ExistingWorkerTask -TaskName $Worker.TaskName
}

$BrokerTerminalPaths = @(
    $Workers |
        ForEach-Object { Get-DotEnvValue -Path $_.EnvFile -Name "MT5_PATH" } |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        ForEach-Object { [System.IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($_)) }
)

if ($BrokerTerminalPaths.Count -gt 0) {
    $SessionZeroTerminals = Get-CimInstance Win32_Process -Filter "Name = 'terminal64.exe'" |
        Where-Object {
            $_.SessionId -eq 0 -and
            $_.ExecutablePath -and
            ($BrokerTerminalPaths -contains [System.IO.Path]::GetFullPath($_.ExecutablePath))
        }
    foreach ($Terminal in $SessionZeroTerminals) {
        Stop-Process -Id $Terminal.ProcessId -Force
        Write-Host "Stopped orphan Session 0 MT5 process $($Terminal.ProcessId): $($Terminal.ExecutablePath)" -ForegroundColor Yellow
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

foreach ($Worker in $Workers) {
    $ActionArguments = '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "{0}" -WorkerName "{1}" -EnvFile "{2}" -PythonPath "{3}"' -f `
        $RunnerPath, $Worker.Name, $Worker.EnvFile, $PythonPath
    $Action = New-ScheduledTaskAction `
        -Execute $PowerShellPath `
        -Argument $ActionArguments `
        -WorkingDirectory $Root
    $Task = New-ScheduledTask -Action $Action -Trigger $Trigger -Settings $Settings -Principal $TaskPrincipal
    Register-ScheduledTask -TaskName $Worker.TaskName -InputObject $Task -Force | Out-Null
    Write-Host "Registered: $($Worker.TaskName)" -ForegroundColor Green
}

if (-not $SkipStart) {
    foreach ($Worker in $Workers) {
        Start-ScheduledTask -TaskName $Worker.TaskName
        Write-Host "Started: $($Worker.TaskName)" -ForegroundColor Green
    }
    Start-Sleep -Seconds 2
}

Write-Host ""
$TaskStatuses = foreach ($Worker in $Workers) {
    $Task = Get-ScheduledTask -TaskName $Worker.TaskName
    $TaskInfo = Get-ScheduledTaskInfo -TaskName $Worker.TaskName
    [pscustomobject]@{
        TaskName = $Worker.TaskName
        State = $Task.State
        LastTaskResult = $TaskInfo.LastTaskResult
    }
}
$TaskStatuses | Format-Table -AutoSize
Write-Host "Keep this Windows user logged in. Disconnecting RDP is safe; signing out stops interactive tasks." -ForegroundColor Cyan
