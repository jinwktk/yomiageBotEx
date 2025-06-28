@echo off
rem yomiageBotEx reload script (Windows) - Bot停止不要で最新化
setlocal enabledelayedexpansion

echo ========================================
echo yomiageBotEx リロードスクリプト
echo ========================================
echo.

rem Get latest code
echo [1/4] 最新コードを取得中...
git pull
if %errorlevel% neq 0 (
    echo ❌ Git pullに失敗しました。手動で確認してください。
    echo.
    pause
    exit /b 1
) else (
    echo ✅ 最新コードを取得しました
)
echo.

rem Check for changes in dependencies
echo [2/4] 依存関係の変更をチェック中...
set "deps_changed=false"
git diff HEAD~1 HEAD --name-only | findstr "pyproject.toml" >nul
if %errorlevel% equ 0 (
    set "deps_changed=true"
    echo ⚠️  pyproject.tomlに変更があります
)

git diff HEAD~1 HEAD --name-only | findstr "requirements.txt" >nul
if %errorlevel% equ 0 (
    set "deps_changed=true"
    echo ⚠️  requirements.txtに変更があります
)

if "!deps_changed!"=="true" (
    echo.
    echo [3/4] 依存関係を更新中...
    uv sync
    if %errorlevel% neq 0 (
        echo ❌ 依存関係の更新に失敗しました
        pause
        exit /b 1
    ) else (
        echo ✅ 依存関係を更新しました
    )
) else (
    echo ✅ 依存関係の変更はありません
    echo [3/4] 依存関係更新をスキップ
)
echo.

rem Check what files changed
echo [4/4] 変更されたファイルを確認中...
echo.
echo 📋 変更されたファイル:
git diff HEAD~1 HEAD --name-only
echo.

rem Check if cogs were changed
set "cogs_changed=false"
for /f %%i in ('git diff HEAD~1 HEAD --name-only ^| findstr "cogs/"') do (
    set "cogs_changed=true"
    echo 🔄 Cogファイルが変更されています: %%i
)

rem Check if bot.py was changed
git diff HEAD~1 HEAD --name-only | findstr "bot.py" >nul
if %errorlevel% equ 0 (
    echo ⚠️  bot.pyが変更されています（要再起動）
)

rem Check if utils were changed
for /f %%i in ('git diff HEAD~1 HEAD --name-only ^| findstr "utils/"') do (
    echo 🔄 ユーティリティが変更されています: %%i
)

echo.
echo ========================================
echo リロード完了
echo ========================================

if "!cogs_changed!"=="true" (
    echo 💡 Cogファイルが変更されました
    echo    - Botが起動中の場合: 自動リロードされます
    echo    - または /reload_all コマンドを実行してください
)

if "!deps_changed!"=="true" (
    echo 💡 依存関係が変更されました
    echo    - 新しいライブラリがある場合はBot再起動を推奨
)

git diff HEAD~1 HEAD --name-only | findstr "bot.py" >nul
if %errorlevel% equ 0 (
    echo ⚠️  bot.pyが変更されました
    echo    - Bot本体の再起動が必要です
)

echo.
echo 📌 次のステップ:
echo    - Cogのみ変更: そのまま開発継続可能
echo    - bot.py/依存関係変更: scripts/start.bat で再起動
echo.

pause