@echo off
title DVSA Slot Monitor - Ahmed Ali
color 0A

echo.
echo ============================================================
echo   DVSA Pupil Test Slot Monitor - Starting...
echo ============================================================
echo.

cd /d "%~dp0"

:: Quick check that Python and dependencies are installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Run setup.bat first.
    pause
    exit /b 1
)

:: Check .env exists
if not exist .env (
    echo [ERROR] .env file missing. Run setup.bat first.
    pause
    exit /b 1
)

echo Starting monitor... Press Ctrl+C to stop.
echo.

python main.py

echo.
echo Monitor stopped.
pause
