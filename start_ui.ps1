# Launch the web UI
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "First-time setup..." -ForegroundColor Yellow
    python -m venv .venv
    & .\.venv\Scripts\pip install -e . -q
}

Write-Host "Starting US Stock Scanner..." -ForegroundColor Cyan

# Try to discover a usable local IP for LAN access
$ip = $null
try {
    $ip = (Get-NetIPAddress -AddressFamily IPv4 |
           Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' -and $_.OperationalStatus -eq 'Up' } |
           Sort-Object -Property PrefixOrigin |
           Select-Object -First 1 -ExpandProperty IPAddress)
} catch {}
if (-not $ip) {
    try {
        $ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | Select-Object -First 1 -ExpandProperty IPAddress)
    } catch {}
}
if (-not $ip) { $ip = "YOUR-MACHINE-IP" }

Write-Host ""
Write-Host "Local (this machine):  http://localhost:8501" -ForegroundColor Green
Write-Host "Network (other PCs):   http://$ip:8501" -ForegroundColor Green
Write-Host ""
Write-Host "Tip: On this machine you can also use http://127.0.0.1:8501" -ForegroundColor Yellow
Write-Host ""

& $python -m streamlit run app.py `
    --server.address 0.0.0.0 `
    --server.port 8501 `
    --browser.gatherUsageStats false