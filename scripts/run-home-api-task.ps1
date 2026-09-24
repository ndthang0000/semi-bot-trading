param(
    [Parameter(Mandatory=$true)]
    [string]$PythonPath
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$LogDirectory = Join-Path $Root "var"
$StdoutPath = Join-Path $LogDirectory "BotAPI.home.out.log"
$StderrPath = Join-Path $LogDirectory "BotAPI.home.err.log"
$MaxLogBytes = 10MB

function Rotate-Log {
    param([Parameter(Mandatory=$true)][string]$Path)

    if ((Test-Path -LiteralPath $Path) -and ((Get-Item -LiteralPath $Path).Length -ge $MaxLogBytes)) {
        Move-Item -LiteralPath $Path -Destination "$Path.1" -Force
    }
}

New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
Rotate-Log -Path $StdoutPath
Rotate-Log -Path $StderrPath

try {
    $StartedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
    Add-Content -LiteralPath $StdoutPath -Value "[$StartedAt] Starting API and built frontend"
    Set-Location $Root
    $env:PYTHONUNBUFFERED = "1"
    $env:PYTHONUTF8 = "1"
    $PreviousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $PythonPath -m semi_bot_trading.cli serve-api --port 8000 --env .env.api 1>> $StdoutPath 2>> $StderrPath
        $ProcessExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }
    if ($ProcessExitCode -ne 0) {
        throw "API exited with code $ProcessExitCode"
    }
} catch {
    $FailedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
    Add-Content -LiteralPath $StderrPath -Value "[$FailedAt] $($_.Exception.Message)"
    throw
}
