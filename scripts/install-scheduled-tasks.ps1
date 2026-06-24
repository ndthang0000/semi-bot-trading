<#
.SYNOPSIS
    Đăng ký Windows Scheduled Tasks cho semi-bot-trading.
    Chạy 1 lần khi setup VPS hoặc khi muốn update lịch.

.USAGE
    # Chạy với quyền Administrator
    .\scripts\install-scheduled-tasks.ps1
#>

param(
    [string]$Python = (Get-Command python).Source,
    [string]$At = "01:00",
    [switch]$SkipSeed
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$LogDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
$LogFile = Join-Path $LogDir "fetch-news.log"

if (-not (Test-Path $Python)) {
    throw "Python executable not found: $Python"
}

# ── Task: fetch-news hàng ngày lúc 1h sáng ──────────────────────────────────
$taskName   = "SemiBot-FetchNews"
$action     = New-ScheduledTaskAction `
                  -Execute "powershell.exe" `
                  -Argument "-NoProfile -ExecutionPolicy Bypass -Command `"cd '$Root'; & '$Python' -m semi_bot_trading.cli fetch-news >> '$LogFile' 2>&1`"" `
                  -WorkingDirectory $Root
$trigger    = New-ScheduledTaskTrigger -Daily -At $At
$settings   = New-ScheduledTaskSettingsSet `
                  -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
                  -RestartCount 3 `
                  -RestartInterval (New-TimeSpan -Minutes 2) `
                  -StartWhenAvailable   # chạy bù nếu máy tắt lúc 1h

# Xoá task cũ nếu có rồi tạo lại
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask `
    -TaskName $taskName `
    -Action   $action `
    -Trigger  $trigger `
    -Settings $settings `
    -RunLevel Highest `
    -Force | Out-Null

Write-Host "[OK] Registered: $taskName (daily $At, WorkingDir: $Root)" -ForegroundColor Green
Write-Host "     Python: $Python" -ForegroundColor Gray
Write-Host "     Log   : $LogFile" -ForegroundColor Gray

# ── Chạy fetch-news ngay lần đầu để seed DB ─────────────────────────────────
if (-not $SkipSeed) {
    Write-Host ""
    Write-Host "Running fetch-news now to seed DB..." -ForegroundColor Yellow
    Set-Location $Root
    & $Python -m semi_bot_trading.cli fetch-news
    Write-Host "Done." -ForegroundColor Green
}
