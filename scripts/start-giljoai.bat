@echo off
title Giljo HQ Server

REM This launcher ships inside scripts/, but the venv and startup.py live one
REM level up in the installation root -- go there before launching anything.
cd /d "%~dp0.."

if not exist "venv\Scripts\python.exe" (
    echo.
    echo Error: no virtual environment found at "%CD%\venv".
    echo Run the installer first, then start Giljo HQ again.
    echo.
    pause
    exit /b 1
)

REM venv\Scripts\python.exe, never a bare "python": on a fresh Windows the
REM first python on PATH is the Store app-execution-alias stub, which just
REM prints "Python was not found" and opens the Store.
REM startup.py, never the api.run_api module: only startup.py builds the
REM frontend, applies migrations, and opens the browser.
venv\Scripts\python.exe startup.py --verbose %*

if errorlevel 1 (
    echo.
    echo Giljo HQ exited with an error. The messages above explain why.
    echo.
    pause
    exit /b 1
)
