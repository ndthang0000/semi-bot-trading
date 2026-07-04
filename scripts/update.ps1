param(
    [switch]$SkipFrontend,
    [switch]$RestartWorker,
    [switch]$RestartFTMO,
    [switch]$RestartAllWorkers,
    [switch]$SkipNews
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$WinSW = "C:\winsw"

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

Write-Host ""
Write-Host "===============================" -ForegroundColor Cyan
Write-Host "  Reaction Zone Bot - Update   " -ForegroundColor Cyan
Write-Host "===============================" -ForegroundColor Cyan
Write-Host ""

# ── 1. Git pull ──────────────────────────────────────────────────────────────
Write-Host "[1/5] Pulling latest code from GitHub..." -ForegroundColor Yellow
Set-Location $Root
$beforeHash = git rev-parse HEAD
git pull
$afterHash = git rev-parse HEAD

if ($beforeHash -eq $afterHash) {
    Write-Host "      Already up to date." -ForegroundColor Gray
} else {
    Write-Host "      Updated: $($beforeHash.Substring(0,7)) -> $($afterHash.Substring(0,7))" -ForegroundColor Green
}

# ── 2. Install Python dependencies ───────────────────────────────────────────
Write-Host ""
Write-Host "[2/5] Installing Python dependencies..." -ForegroundColor Yellow
pip install -e . --quiet --upgrade
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
            npm run build
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
    Write-Host "      Done." -ForegroundColor Green
}

# ── 5. Restart services ───────────────────────────────────────────────────────
Write-Host ""
Write-Host "[5/5] Restarting services..." -ForegroundColor Yellow

Invoke-WinSW -ServiceName "BotAPI" -Command "restart" -Required | Out-Null
Write-Host "      BotAPI restarted." -ForegroundColor Green

if ($RestartWorker -or $RestartAllWorkers) {
    Invoke-WinSW -ServiceName "BotWorker" -Command "restart" -Required | Out-Null
    Write-Host "      BotWorker restarted." -ForegroundColor Green
} else {
    Write-Host "      BotWorker skipped (use -RestartWorker to restart)." -ForegroundColor Gray
}

if ($RestartFTMO -or $RestartAllWorkers) {
    Invoke-WinSW -ServiceName "BotWorkerFTMO" -Command "restart" | Out-Null
    if (Test-Path (Join-Path $WinSW "BotWorkerFTMO.exe")) {
        Write-Host "      BotWorkerFTMO restarted." -ForegroundColor Green
    }
} else {
    Write-Host "      BotWorkerFTMO skipped (use -RestartFTMO or -RestartAllWorkers to restart)." -ForegroundColor Gray
}

# ── Done ──────────────────────────────────────────────────────────────────────
Write-Host ""
Start-Sleep 2
$apiStatus = Invoke-WinSW -ServiceName "BotAPI" -Command "status" -Required
$workerStatus = Invoke-WinSW -ServiceName "BotWorker" -Command "status"
$ftmoStatus = Invoke-WinSW -ServiceName "BotWorkerFTMO" -Command "status"

Write-Host "===============================" -ForegroundColor Cyan
Write-Host "  Update complete!" -ForegroundColor Green
Write-Host "  BotAPI    : $apiStatus"
Write-Host "  BotWorker : $workerStatus"
Write-Host "  FTMO      : $ftmoStatus"
Write-Host "===============================" -ForegroundColor Cyan
Write-Host ""
