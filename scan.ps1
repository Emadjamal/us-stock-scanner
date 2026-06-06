# US Stock Scanner
#   .\scan.ps1                 S&P 500 scan
#   .\scan.ps1 -Symbol NVDA    One ticker
#   .\scan.ps1 -Watchlist      Your watchlist
#   .\scan.ps1 -Outcomes       Journal results
param(
    [string]$Symbol,
    [switch]$Watchlist,
    [string]$Universe = "sp500",
    [switch]$Full,
    [switch]$Outcomes,
    [switch]$LogWatch,
    [switch]$NoLog,
    [int]$Watch = 7
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "First-time setup..." -ForegroundColor Yellow
    python -m venv .venv
    & .\.venv\Scripts\pip install -e . -q
}

if ($Outcomes) {
    & $python -m us_stock_scanner --outcomes
    exit $LASTEXITCODE
}

$argsList = @("--watch", $Watch)
if ($Symbol) { $argsList += @("--symbol", $Symbol.ToUpper()) }
elseif ($Watchlist) { $argsList += "--watchlist" }
else {
    $argsList += @("-u", $Universe)
    if ($Full) { $argsList += "--full" }
}
if ($LogWatch) { $argsList += "--log-watch" }
if ($NoLog) { $argsList += "--no-log" }

& $python -m us_stock_scanner @argsList