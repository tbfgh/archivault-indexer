@echo off
title ArchiveVault Indexer
color 0A

echo.
echo  ==========================================
echo   ArchiveVault Indexer - Windows
echo  ==========================================
echo.

:: Check if config.json exists
if not exist "config.json" (
    echo  [!] config.json not found.
    echo      Copy config.json.example to config.json
    echo      and fill in your server URL and token.
    echo.
    pause
    exit /b 1
)

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  [!] Python not found. Please install Python 3.10+ from python.org
    pause
    exit /b 1
)

:: Check virtualenv
if not exist "venv\Scripts\activate.bat" (
    echo  [*] Creating virtual environment...
    python -m venv venv
    echo  [*] Installing dependencies...
    venv\Scripts\pip install -r requirements.txt -q
    echo  [OK] Dependencies installed.
)

echo  [*] Starting indexer on http://localhost:8989
echo  [*] Browser will open automatically...
echo  [*] Press Ctrl+C to stop
echo.

venv\Scripts\python server.py
pause
