@echo off
cd /d "%~dp0"
title US Stock Scanner
if not exist ".venv\Scripts\python.exe" (
    echo Setting up...
    python -m venv .venv
    .venv\Scripts\pip install -e . -q
)
echo Starting US Stock Scanner...
echo.
echo Local (this machine):  http://localhost:8501
echo Network (other PCs):   http://YOUR-MACHINE-IP:8501
echo.
echo Find your IP with: ipconfig   (look for IPv4 Address)
echo.

.venv\Scripts\python.exe -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501 --browser.gatherUsageStats false
pause