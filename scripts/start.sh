#!/bin/bash
# yomiageBotEx 起動スクリプト

set -e

echo "🤖 yomiageBotEx 起動中..."

# uvがインストールされているかチェック
if ! command -v uv &> /dev/null; then
    echo "❌ uvがインストールされていません。"
    echo "インストール方法: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# .envファイルの存在チェック
if [ ! -f ".env" ]; then
    echo "❌ .envファイルが見つかりません。"
    echo "DISCORD_TOKEN=your_token_here を記述した .env ファイルを作成してください。"
    exit 1
fi

# 依存関係のインストール
echo "📦 依存関係をインストール中..."
uv sync

# ボットの起動
echo "🚀 ボットを起動します..."
uv run python bot.py