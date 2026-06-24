param(
    [switch]$SkipFrontend,
    [switch]$RestartWorker,
    [switch]$SkipNews
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$WinSW = "C:\winsw"

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

& "$WinSW\BotAPI.exe" restart
Write-Host "      BotAPI restarted." -ForegroundColor Green

if ($RestartWorker) {
    & "$WinSW\BotWorker.exe" restart
    Write-Host "      BotWorker restarted." -ForegroundColor Green
} else {
    Write-Host "      BotWorker skipped (use -RestartWorker to restart)." -ForegroundColor Gray
}

# ── Done ──────────────────────────────────────────────────────────────────────
Write-Host ""
Start-Sleep 2
$apiStatus    = & "$WinSW\BotAPI.exe" status
$workerStatus = & "$WinSW\BotWorker.exe" status

Write-Host "===============================" -ForegroundColor Cyan
Write-Host "  Update complete!" -ForegroundColor Green
Write-Host "  BotAPI    : $apiStatus"
Write-Host "  BotWorker : $workerStatus"
Write-Host "===============================" -ForegroundColor Cyan
Write-Host ""
