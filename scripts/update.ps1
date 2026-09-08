param(
    [switch]$SkipFrontend,
    [switch]$RestartWorker,
    [switch]$RestartFTMO,
    [switch]$RestartAllWorkers,
    [switch]$SkipNews
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$WinSW = "C:\winsw"
$ExnessTaskName = "SemiBotTrading-ExnessWorker"
$FTMOTaskName = "SemiBotTrading-FTMOWorker"

function Invoke-WinSW {
    param(
        [Parameter(Mandatory=$true)][string]$ServiceName,
        [Parameter(Mandatory=$true)][string]$Command,
        [switch]$Required
    )
    $exe = Join-Path $WinSW "$ServiceName.exe"
    if (-not (Test-Path $exe)) {
        if ($Required) {
            throw "WinSW service executable not found: $exe"
        }
        Write-Host "      $ServiceName skipped ($exe not found)." -ForegroundColor Gray
        return $null
    }
    return & $exe $Command
}

function Assert-NativeCommandSucceeded {
    param([Parameter(Mandatory=$true)][string]$Description)

    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE. Selected workers remain stopped; fix the error before starting them."
    }
}

function Get-WorkerTask {
    param([Parameter(Mandatory=$true)][string]$TaskName)

    $Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -eq $Task) {
        throw "Scheduled task '$TaskName' not found. Run .\scripts\install-worker-tasks.ps1 from an elevated RDP PowerShell session first."
    }
    return $Task
}

function Stop-WorkerTask {
    param([Parameter(Mandatory=$true)][string]$TaskName)

    $Task = Get-WorkerTask -TaskName $TaskName
    if ($Task.State -ne "Ready" -and $Task.State -ne "Disabled") {
        Stop-ScheduledTask -TaskName $TaskName
        for ($Attempt = 0; $Attempt -lt 20; $Attempt++) {
            Start-Sleep -Milliseconds 500
            $Task = Get-ScheduledTask -TaskName $TaskName
            if ($Task.State -eq "Ready" -or $Task.State -eq "Disabled") {
                break
            }
        }
        if ($Task.State -ne "Ready" -and $Task.State -ne "Disabled") {
            throw "Scheduled task '$TaskName' did not stop within 10 seconds."
        }
    }
    Write-Host "      Stopped scheduled task: $TaskName" -ForegroundColor Green
}

function Start-WorkerTask {
    param([Parameter(Mandatory=$true)][string]$TaskName)

    $Task = Get-WorkerTask -TaskName $TaskName
    if ($Task.State -eq "Disabled") {
        throw "Scheduled task '$TaskName' is disabled. Enable it before running the update."
    }
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "      Started scheduled task: $TaskName" -ForegroundColor Green
}

function Get-WorkerTaskStatus {
    param([Parameter(Mandatory=$true)][string]$TaskName)

    $Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -eq $Task) {
        return "NOT INSTALLED"
    }
    $Info = Get-ScheduledTaskInfo -TaskName $TaskName
    return "$($Task.State) (last result: $($Info.LastTaskResult))"
}

$RestartExnessWorker = $RestartWorker -or $RestartAllWorkers
$RestartFTMOWorker = $RestartFTMO -or $RestartAllWorkers

Write-Host ""
Write-Host "===============================" -ForegroundColor Cyan
Write-Host "  Reaction Zone Bot - Update   " -ForegroundColor Cyan
Write-Host "===============================" -ForegroundColor Cyan
Write-Host ""

if ($RestartExnessWorker -or $RestartFTMOWorker) {
    Write-Host "[pre] Stopping selected live-worker tasks before update..." -ForegroundColor Yellow
    if ($RestartExnessWorker) {
        Stop-WorkerTask -TaskName $ExnessTaskName
    }
    if ($RestartFTMOWorker) {
        Stop-WorkerTask -TaskName $FTMOTaskName
    }
    Write-Host ""
}

# ── 1. Git pull ──────────────────────────────────────────────────────────────
Write-Host "[1/5] Pulling latest code from GitHub..." -ForegroundColor Yellow
Set-Location $Root
$beforeHash = git rev-parse HEAD
Assert-NativeCommandSucceeded -Description "git rev-parse before update"
# Deployment does not need repository garbage collection. On Windows, auto-GC
# can prompt forever when an IDE, antivirus scanner, or stale Git process holds
# an old pack index open. Restrict pull to a fast-forward and defer maintenance
# to a separate operator action outside the worker restart window.
git -c gc.auto=0 -c maintenance.auto=false pull --ff-only
Assert-NativeCommandSucceeded -Description "git pull"
$afterHash = git rev-parse HEAD
Assert-NativeCommandSucceeded -Description "git rev-parse after update"

if ($beforeHash -eq $afterHash) {
    Write-Host "      Already up to date." -ForegroundColor Gray
} else {
    Write-Host "      Updated: $($beforeHash.Substring(0,7)) -> $($afterHash.Substring(0,7))" -ForegroundColor Green
}

# ── 2. Install Python dependencies ───────────────────────────────────────────
Write-Host ""
Write-Host "[2/5] Installing Python dependencies..." -ForegroundColor Yellow
pip install -e . --quiet --upgrade
Assert-NativeCommandSucceeded -Description "Python dependency installation"
Write-Host "      Done." -ForegroundColor Green

# ── 3. Build frontend ────────────────────────────────────────────────────────
Write-Host ""
if ($SkipFrontend) {
    Write-Host "[3/5] Skipping frontend build (-SkipFrontend)." -ForegroundColor Gray
} else {
    if ($beforeHash -eq $afterHash) {
        Write-Host "[3/5] No code changes, skipping frontend build." -ForegroundColor Gray
    } else {
        # Check if frontend files changed between the two commits
        $frontendChanged = git diff "$beforeHash" "$afterHash" --name-only 2>$null | Select-String "^frontend/"
        if ($frontendChanged) {
            Write-Host "[3/5] Building frontend..." -ForegroundColor Yellow
            Set-Location (Join-Path $Root "frontend")
            npm install --silent
            Assert-NativeCommandSucceeded -Description "Frontend dependency installation"
            npm run build
            Assert-NativeCommandSucceeded -Description "Frontend build"
            Set-Location $Root
            Write-Host "      Done." -ForegroundColor Green
        } else {
            Write-Host "[3/5] No frontend changes, skipping build." -ForegroundColor Gray
        }
    }
}

# ── 4. Fetch news calendar ───────────────────────────────────────────────────
Write-Host ""
if ($SkipNews) {
    Write-Host "[4/5] Skipping fetch-news (-SkipNews)." -ForegroundColor Gray
} else {
    Write-Host "[4/5] Fetching economic calendar..." -ForegroundColor Yellow
    Set-Location $Root
    python -m semi_bot_trading.cli fetch-news
    Assert-NativeCommandSucceeded -Description "Economic calendar fetch"
    Write-Host "      Done." -ForegroundColor Green
}

# ── 5. Restart services ───────────────────────────────────────────────────────
Write-Host ""
Write-Host "[5/5] Restarting services..." -ForegroundColor Yellow

Invoke-WinSW -ServiceName "BotAPI" -Command "restart" -Required | Out-Null
Write-Host "      BotAPI restarted." -ForegroundColor Green

if ($RestartExnessWorker) {
    Start-WorkerTask -TaskName $ExnessTaskName
} else {
    Write-Host "      Exness worker skipped (use -RestartWorker to restart)." -ForegroundColor Gray
}

if ($RestartFTMOWorker) {
    Start-WorkerTask -TaskName $FTMOTaskName
} else {
    Write-Host "      FTMO worker skipped (use -RestartFTMO or -RestartAllWorkers to restart)." -ForegroundColor Gray
}

# ── Done ──────────────────────────────────────────────────────────────────────
Write-Host ""
Start-Sleep 2
$apiStatus = Invoke-WinSW -ServiceName "BotAPI" -Command "status" -Required
$workerStatus = Get-WorkerTaskStatus -TaskName $ExnessTaskName
$ftmoStatus = Get-WorkerTaskStatus -TaskName $FTMOTaskName

Write-Host "===============================" -ForegroundColor Cyan
Write-Host "  Update complete!" -ForegroundColor Green
Write-Host "  BotAPI    : $apiStatus"
Write-Host "  Exness task : $workerStatus"
Write-Host "  FTMO task   : $ftmoStatus"
Write-Host "===============================" -ForegroundColor Cyan
Write-Host ""
