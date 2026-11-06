param(
    [string]$SourceBranch = "codex/dev-local",
    [switch]$SkipTests,
    [switch]$SkipPush
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ExpectedLiveRoot = "C:\workspace\semi-bot-trading"
$RequiredTasks = @(
    "SemiBotTrading-API",
    "SemiBotTrading-ExnessWorker"
)
$OptionalTasks = @(
    "SemiBotTrading-FTMOWorker"
)

function Invoke-NativeChecked {
    param(
        [Parameter(Mandatory=$true)][string]$FilePath,
        [Parameter(Mandatory=$true)][string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath exited with code $LASTEXITCODE"
    }
}

if (-not $Root.Equals($ExpectedLiveRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Run this script from the LIVE checkout at $ExpectedLiveRoot. Current root: $Root"
}
Set-Location $Root

$CurrentBranch = (& git branch --show-current).Trim()
if ($CurrentBranch -ne "main") {
    throw "LIVE checkout must be on main. Current branch: $CurrentBranch"
}
if (& git status --porcelain) {
    throw "LIVE checkout has uncommitted changes. Commit or restore them before deployment."
}

Invoke-NativeChecked -FilePath "git" -Arguments @("rev-parse", "--verify", "$SourceBranch^{commit}")
& git merge-base --is-ancestor main $SourceBranch
if ($LASTEXITCODE -ne 0) {
    throw "$SourceBranch is not based on the current main. Merge main into DEV and test again first."
}

Write-Host "Merging $SourceBranch into LIVE main..." -ForegroundColor Cyan
Invoke-NativeChecked -FilePath "git" -Arguments @("merge", "--ff-only", $SourceBranch)

Write-Host "Installing Python dependencies..." -ForegroundColor Cyan
Invoke-NativeChecked -FilePath "python" -Arguments @("-m", "pip", "install", "-e", ".")
Invoke-NativeChecked -FilePath "python" -Arguments @("-m", "pip", "check")

Write-Host "Installing and building frontend..." -ForegroundColor Cyan
Push-Location (Join-Path $Root "frontend")
try {
    Invoke-NativeChecked -FilePath "npm.cmd" -Arguments @("ci")
    Invoke-NativeChecked -FilePath "npm.cmd" -Arguments @("run", "build")
} finally {
    Pop-Location
}

if (-not $SkipTests) {
    Write-Host "Running Python tests..." -ForegroundColor Cyan
    Invoke-NativeChecked -FilePath "python" -Arguments @("-m", "unittest", "discover", "-s", "tests")
}

if (-not $SkipPush) {
    Write-Host "Pushing validated main..." -ForegroundColor Cyan
    Invoke-NativeChecked -FilePath "git" -Arguments @("push", "origin", "main")
}

foreach ($TaskName in $RequiredTasks) {
    if (-not (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)) {
        throw "Scheduled Task not found: $TaskName"
    }
}
$Tasks = @($RequiredTasks)
foreach ($TaskName in $OptionalTasks) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        $Tasks += $TaskName
    } else {
        Write-Host "Optional LIVE task not installed; skipping: $TaskName" -ForegroundColor Yellow
    }
}

Write-Host "Stopping LIVE tasks..." -ForegroundColor Cyan
foreach ($TaskName in $Tasks) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
}

$StopDeadline = (Get-Date).AddSeconds(20)
do {
    $RunningTasks = @($Tasks | Where-Object {
        (Get-ScheduledTask -TaskName $_).State -eq "Running"
    })
    if ($RunningTasks.Count -eq 0) { break }
    Start-Sleep -Milliseconds 500
} while ((Get-Date) -lt $StopDeadline)
if ($RunningTasks.Count -gt 0) {
    throw "Tasks did not stop in time: $($RunningTasks -join ', ')"
}

Write-Host "Starting LIVE API..." -ForegroundColor Cyan
Start-ScheduledTask -TaskName "SemiBotTrading-API"

$ApiHealthy = $false
$ApiDeadline = (Get-Date).AddSeconds(45)
do {
    try {
        $Health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 2
        if ($Health.status -eq "ok") {
            $ApiHealthy = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 1
    }
} while ((Get-Date) -lt $ApiDeadline)
if (-not $ApiHealthy) {
    throw "LIVE API health check failed. Workers remain stopped. Check var\BotAPI.home.err.log."
}

Write-Host "Starting LIVE workers..." -ForegroundColor Cyan
Start-ScheduledTask -TaskName "SemiBotTrading-ExnessWorker"
if ($Tasks -contains "SemiBotTrading-FTMOWorker") {
    Start-ScheduledTask -TaskName "SemiBotTrading-FTMOWorker"
}
Start-Sleep -Seconds 3

$Tasks | ForEach-Object {
    $Task = Get-ScheduledTask -TaskName $_
    $Info = Get-ScheduledTaskInfo -TaskName $_
    [pscustomobject]@{
        Task = $_
        State = $Task.State
        LastResult = $Info.LastTaskResult
    }
} | Format-Table -AutoSize

Write-Host "Deployment complete: $(& git rev-parse --short HEAD)" -ForegroundColor Green
