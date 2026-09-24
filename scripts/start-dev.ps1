param(
  [int]$BackendPort = 8000,
  [int]$FrontendPort = 5173,
  [switch]$WithWorker,
  [switch]$EnableExecution,
  [string]$ApiEnv = ".env.api",
  [string]$WorkerEnv = "",
  [string]$Env = ""
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")

Write-Host "Starting backend on http://127.0.0.1:$BackendPort"
Write-Host "Starting frontend on http://127.0.0.1:$FrontendPort"
$resolvedWorkerEnv = if ($WorkerEnv) { $WorkerEnv } elseif ($Env) { $Env } else { ".env.exness" }
Write-Host "Backend env: $ApiEnv"
if ($WithWorker) {
  $executionText = if ($EnableExecution) { "enabled" } else { "forced disabled" }
  Write-Host "Starting MT5/Telegram live worker, env=$resolvedWorkerEnv, execution=$executionText"
}
Write-Host "Press Ctrl+C to stop all started processes."

$backendJob = Start-Job -Name "reaction-zone-backend" -ScriptBlock {
  param($RootPath, $Port, $EnvPath)
  Set-Location $RootPath
  python -m semi_bot_trading.cli serve-api --port $Port --env $EnvPath
} -ArgumentList $Root, $BackendPort, $ApiEnv

$frontendJob = Start-Job -Name "reaction-zone-frontend" -ScriptBlock {
  param($RootPath, $Port, $BackendPort)
  Set-Location (Join-Path $RootPath "frontend")
  $env:VITE_API_PROXY_TARGET = "http://127.0.0.1:$BackendPort"
  npm run dev -- --port $Port
} -ArgumentList $Root, $FrontendPort, $BackendPort

$jobs = @($backendJob, $frontendJob)

if ($WithWorker) {
  $workerJob = Start-Job -Name "reaction-zone-live-worker" -ScriptBlock {
    param($RootPath, $ExecutionEnabled, $EnvPath)
    Set-Location $RootPath
    $env:EXECUTION_ENABLED = if ($ExecutionEnabled) { "true" } else { "false" }
    python -m semi_bot_trading.cli live-worker --env $EnvPath
  } -ArgumentList $Root, [bool]$EnableExecution, $resolvedWorkerEnv
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
