@echo off
setlocal
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
  py -3.10 -m venv venv
)
"venv\Scripts\python.exe" -m pip install --upgrade pip
"venv\Scripts\python.exe" -m pip install -r requirements.txt
echo.
echo Done. Run run.bat to start.
pause
