@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Setting up...
    python -m venv .venv
    .venv\Scripts\pip install -e . -q
)
.venv\Scripts\python.exe -m us_stock_scanner %*
pause