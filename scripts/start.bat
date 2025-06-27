@echo off
rem yomiageBotEx 起動スクリプト (Windows)

echo 🤖 yomiageBotEx 起動中...

rem uvがインストールされているかチェック
where uv >nul 2>nul
if %errorlevel% neq 0 (
    echo ❌ uvがインストールされていません。
    echo インストール方法: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    pause
    exit /b 1
)

rem .envファイルの存在チェック
if not exist ".env" (
    echo ❌ .envファイルが見つかりません。
    echo DISCORD_TOKEN=your_token_here を記述した .env ファイルを作成してください。
    pause
    exit /b 1
)

rem 依存関係のインストール
echo 📦 依存関係をインストール中...
uv sync --no-install-project

rem ボットの起動
echo 🚀 ボットを起動します...
uv run --no-project python bot.py

pause