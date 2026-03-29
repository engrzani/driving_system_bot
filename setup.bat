@echo off
title DVSA Slot Monitor - Setup
color 0A

echo.
echo ============================================================
echo   DVSA Pupil Test Slot Monitor - Windows Setup
echo ============================================================
echo.

:: Check Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    echo         Download from https://www.python.org/downloads/
    echo         Make sure to tick "Add Python to PATH" during install.
    pause
    exit /b 1
)

echo [1/3] Installing Python dependencies...
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] pip install failed. Check your internet connection.
    pause
    exit /b 1
)
echo       Done.

echo.
echo [2/3] Installing Playwright browser (Chromium)...
python -m playwright install chromium
if errorlevel 1 (
    echo [ERROR] Playwright install failed.
    pause
    exit /b 1
)
echo       Done.

echo.
echo [3/3] Checking .env file...
if not exist .env (
    echo       .env not found — copying from .env.example
    copy .env.example .env >nul
    echo       Edit .env with your credentials before running.
) else (
    echo       .env already exists.
)

echo.
echo ============================================================
echo   Setup complete!
echo.
echo   NEXT STEPS:
echo   1. Open .env and fill in your DVSA credentials
echo   2. Open config.json and update your test centres
echo   3. (Optional) Add your Telegram bot token to .env
echo   4. Run the monitor:   python main.py
echo ============================================================
echo.
pause
