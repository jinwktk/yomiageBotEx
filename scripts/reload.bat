@echo off
rem yomiageBotEx reload script (Windows) - Bot restart not required
setlocal enabledelayedexpansion

echo ========================================
echo yomiageBotEx Reload Script
echo ========================================
echo.

rem Get latest code
echo [1/4] Getting latest code...
git pull
if %errorlevel% neq 0 (
    echo [ERROR] Git pull failed. Please check manually.
    echo.
    pause
    exit /b 1
) else (
    echo [OK] Latest code retrieved
)
echo.

rem Check for changes in dependencies
echo [2/4] Checking dependency changes...
set "deps_changed=false"
git diff HEAD~1 HEAD --name-only | findstr "pyproject.toml" >nul
if %errorlevel% equ 0 (
    set "deps_changed=true"
    echo [WARNING] pyproject.toml has changes
)

git diff HEAD~1 HEAD --name-only | findstr "requirements.txt" >nul
if %errorlevel% equ 0 (
    set "deps_changed=true"
    echo [WARNING] requirements.txt has changes
)

if "!deps_changed!"=="true" (
    echo.
    echo [3/4] Updating dependencies...
    uv sync
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to update dependencies
        pause
        exit /b 1
    ) else (
        echo [OK] Dependencies updated
    )
) else (
    echo [OK] No dependency changes
    echo [3/4] Skipping dependency update
)
echo.

rem Check what files changed
echo [4/4] Checking changed files...
echo.
echo Changed files:
git diff HEAD~1 HEAD --name-only
echo.

rem Check if cogs were changed
set "cogs_changed=false"
for /f %%i in ('git diff HEAD~1 HEAD --name-only ^| findstr "cogs/"') do (
    set "cogs_changed=true"
    echo [COG CHANGED] %%i
)

rem Check if bot.py was changed
git diff HEAD~1 HEAD --name-only | findstr "bot.py" >nul
if %errorlevel% equ 0 (
    echo [BOT CHANGED] bot.py changed (restart required)
)

rem Check if utils were changed
for /f %%i in ('git diff HEAD~1 HEAD --name-only ^| findstr "utils/"') do (
    echo [UTIL CHANGED] %%i
)

echo.
echo ========================================
echo Reload Complete
echo ========================================

if "!cogs_changed!"=="true" (
    echo [INFO] Cog files changed
    echo        - If bot is running: Auto-reload will happen
    echo        - Or run /reload_all command in Discord
)

if "!deps_changed!"=="true" (
    echo [INFO] Dependencies changed
    echo        - Bot restart recommended for new libraries
)

git diff HEAD~1 HEAD --name-only | findstr "bot.py" >nul
if %errorlevel% equ 0 (
    echo [INFO] bot.py changed
    echo        - Bot restart required
)

echo.
echo Next steps:
echo   - Cog only changes: Continue development
echo   - bot.py/deps changes: Restart with scripts/start.bat
echo.

pause