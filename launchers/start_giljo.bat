@echo off
REM Giljo HQ Windows Launcher

echo ===============================================
echo    Giljo HQ Launcher
echo ===============================================
echo.

REM Set working directory to script location
cd /d "%~dp0"

REM Check if venv exists
if not exist "venv\Scripts\python.exe" (
    echo Error: Virtual environment not found
    echo Please run the installer first
    pause
    exit /b 1
)

REM Launch with venv Python
venv\Scripts\python.exe start_giljo.py %*

if errorlevel 1 (
    echo.
    echo Launch failed. Check the error messages above.
    pause
)
