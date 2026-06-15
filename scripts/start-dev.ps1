param(
  [int]$BackendPort = 8000,
  [int]$FrontendPort = 5173,
  [switch]$WithWorker,
  [switch]$EnableExecution,
  [string]$Env = ".env"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")

Write-Host "Starting backend on http://127.0.0.1:$BackendPort"
Write-Host "Starting frontend on http://127.0.0.1:$FrontendPort"
if ($WithWorker) {
  $executionText = if ($EnableExecution) { "enabled" } else { "from .env" }
  Write-Host "Starting MT5/Telegram live worker, execution=$executionText"
}
Write-Host "Press Ctrl+C to stop all started processes."

$backendJob = Start-Job -Name "reaction-zone-backend" -ScriptBlock {
  param($RootPath, $Port)
  Set-Location $RootPath
  python -m semi_bot_trading.cli serve-api --port $Port
} -ArgumentList $Root, $BackendPort

$frontendJob = Start-Job -Name "reaction-zone-frontend" -ScriptBlock {
  param($RootPath, $Port)
  Set-Location (Join-Path $RootPath "frontend")
  npm run dev -- --port $Port
} -ArgumentList $Root, $FrontendPort

$jobs = @($backendJob, $frontendJob)

if ($WithWorker) {
  $workerJob = Start-Job -Name "reaction-zone-live-worker" -ScriptBlock {
    param($RootPath, $ExecutionEnabled, $EnvPath)
    Set-Location $RootPath
    if ($ExecutionEnabled) {
      $env:EXECUTION_ENABLED = "true"
    }
    python -m semi_bot_trading.cli live-worker --env $EnvPath
  } -ArgumentList $Root, [bool]$EnableExecution, $Env
  $jobs += $workerJob
}

try {
  while ($true) {
    Receive-Job -Job $jobs
    $failed = @($jobs | Where-Object { $_.State -in @("Failed", "Stopped", "Completed") })
    if ($failed.Count -gt 0) {
      Receive-Job -Job $jobs
      throw "One of the dev servers exited: $($failed.Name -join ', ')"
    }
    Start-Sleep -Milliseconds 500
  }
}
finally {
  Write-Host "Stopping dev servers..."
  Stop-Job -Job $jobs -ErrorAction SilentlyContinue
  Remove-Job -Job $jobs -Force -ErrorAction SilentlyContinue
}
