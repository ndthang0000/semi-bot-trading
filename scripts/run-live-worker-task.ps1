param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("Exness", "FTMO")]
    [string]$WorkerName,

    [Parameter(Mandatory=$true)]
    [string]$EnvFile,

    [Parameter(Mandatory=$true)]
    [string]$PythonPath
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$LogDirectory = Join-Path $Root "var"
$LogPrefix = if ($WorkerName -eq "Exness") { "BotWorker.task" } else { "BotWorkerFTMO.task" }
$StdoutPath = Join-Path $LogDirectory "$LogPrefix.out.log"
$StderrPath = Join-Path $LogDirectory "$LogPrefix.err.log"
$MaxLogBytes = 10MB

function Rotate-Log {
    param([Parameter(Mandatory=$true)][string]$Path)

    if ((Test-Path $Path) -and ((Get-Item $Path).Length -ge $MaxLogBytes)) {
        Move-Item -Path $Path -Destination "$Path.1" -Force
    }
}

New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
Rotate-Log -Path $StdoutPath
Rotate-Log -Path $StderrPath

try {
    $CurrentSessionId = [System.Diagnostics.Process]::GetCurrentProcess().SessionId
    if ($CurrentSessionId -eq 0) {
        throw "$WorkerName worker refused to start in Windows Session 0. Reinstall the scheduled task with LogonType Interactive."
    }

    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
        throw "Python executable not found: $PythonPath"
    }

    $ResolvedEnvFile = if ([System.IO.Path]::IsPathRooted($EnvFile)) {
        $EnvFile
    } else {
        Join-Path $Root $EnvFile
    }
    if (-not (Test-Path -LiteralPath $ResolvedEnvFile -PathType Leaf)) {
        throw "Worker environment file not found: $ResolvedEnvFile"
    }

    $StartedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
    Add-Content -LiteralPath $StdoutPath -Value "[$StartedAt] Starting $WorkerName worker in Windows Session $CurrentSessionId"

    Set-Location $Root
    $env:PYTHONUNBUFFERED = "1"
    $env:PYTHONUTF8 = "1"
    $Utf8Encoding = New-Object System.Text.UTF8Encoding($false)
    [Console]::OutputEncoding = $Utf8Encoding
    $OutputEncoding = $Utf8Encoding

    # Windows PowerShell 5.1 converts native stderr records into PowerShell
    # errors. With the script-level preference set to Stop, an ordinary Python
    # warning or a caught iteration traceback terminates this wrapper even
    # though the live worker is designed to continue. Keep native stderr as log
    # output and decide process success strictly from Python's exit code.
    $PreviousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $PythonPath -m semi_bot_trading.cli live-worker --env $ResolvedEnvFile 1>> $StdoutPath 2>> $StderrPath
        $WorkerExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }
    if ($WorkerExitCode -ne 0) {
        throw "$WorkerName worker exited with code $WorkerExitCode"
    }
} catch {
    $FailedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
    Add-Content -LiteralPath $StderrPath -Value "[$FailedAt] $($_.Exception.Message)"
    throw
}
