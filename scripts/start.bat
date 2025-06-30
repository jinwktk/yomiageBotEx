@echo off
rem yomiageBotEx startup script (Windows)

echo yomiageBotEx starting...

rem Get latest code
echo Getting latest code...
git pull
if %errorlevel% neq 0 (
    echo Git pull failed. Please check manually.
    pause
)

rem Check if uv is installed
where uv >nul 2>nul
if %errorlevel% neq 0 (
    echo uv is not installed.
    echo Install command: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    pause
    exit /b 1
)

rem Check .env file exists
if not exist ".env" (
    echo .env file not found.
    echo Please create .env file with DISCORD_TOKEN=your_token_here
    pause
    exit /b 1
)

rem Install dependencies
echo Installing dependencies...
uv sync --no-install-project

rem Start bot with protection against external termination
echo Starting bot in protected mode...
title "YomiageBotEx-Protected"
set PYTHONIOENCODING=utf-8
uv run --no-project python bot.py

pause