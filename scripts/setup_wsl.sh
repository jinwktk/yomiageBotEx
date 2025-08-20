#!/bin/bash

# yomiageBotEx WSL環境自動セットアップスクリプト
# Usage: ./scripts/setup_wsl.sh

set -e  # エラー時に停止

# 色付きログ出力
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

# 前提条件チェック
check_prerequisites() {
    log_step "前提条件チェック中..."
    
    # WSL環境チェック
    if [[ ! -f /proc/version ]] || ! grep -qi "microsoft\|wsl" /proc/version; then
        log_warn "WSL環境ではない可能性があります"
    fi
    
    # Ubuntu バージョンチェック
    if command -v lsb_release &> /dev/null; then
        ubuntu_version=$(lsb_release -r -s)
        log_info "Ubuntu バージョン: $ubuntu_version"
    fi
    
    # インターネット接続チェック
    if ! ping -c 1 google.com &> /dev/null; then
        log_error "インターネット接続が必要です"
        exit 1
    fi
    
    log_info "前提条件チェック完了"
}

# システムパッケージインストール
install_system_packages() {
    log_step "システムパッケージをインストール中..."
    
    # パッケージリストを更新
    sudo apt update
    
    # 必要なパッケージをインストール
    sudo apt install -y \
        python3 \
        python3-pip \
        python3-venv \
        python3-dev \
        python3-setuptools \
        python3-wheel \
        git \
        ffmpeg \
        build-essential \
        libffi-dev \
        libssl-dev \
        libopus-dev \
        libsodium-dev \
        pkg-config \
        curl \
        wget
    
    log_info "システムパッケージインストール完了"
}

# Python環境構築
setup_python_environment() {
    log_step "Python仮想環境を構築中..."
    
    # Python バージョン確認
    python_version=$(python3 --version 2>&1 | cut -d' ' -f2)
    log_info "Python バージョン: $python_version"
    
    # 仮想環境作成
    if [ ! -d "venv" ]; then
        python3 -m venv venv
        log_info "仮想環境を作成しました"
    else
        log_info "既存の仮想環境を使用します"
    fi
    
    # 仮想環境をアクティベート
    source venv/bin/activate
    
    # pipをアップグレード
    pip install --upgrade pip setuptools wheel
    
    log_info "Python環境構築完了"
}

# Python依存関係インストール
install_python_dependencies() {
    log_step "Python依存関係をインストール中..."
    
    source venv/bin/activate
    
    # 音声関連ライブラリを先にインストール（順番重要）
    log_info "音声関連ライブラリをインストール中..."
    pip install PyNaCl==1.5.0
    pip install audioop-lts
    
    # discord.pyをインストール
    log_info "discord.pyをインストール中..."
    pip install "discord.py[voice]>=2.3.0"
    
    # その他の依存関係
    log_info "その他の依存関係をインストール中..."
    pip install aiofiles aiohttp pyyaml python-dotenv
    
    # 依存関係をfreeze（参考用）
    pip freeze > requirements_generated.txt
    
    log_info "Python依存関係インストール完了"
}

# 必要なディレクトリ作成
create_directories() {
    log_step "必要なディレクトリを作成中..."
    
    mkdir -p logs
    mkdir -p cache/tts
    mkdir -p recordings
    mkdir -p data
    mkdir -p scripts
    
    log_info "ディレクトリ作成完了"
}

# 設定ファイルのテンプレート作成
create_config_templates() {
    log_step "設定ファイルテンプレートを作成中..."
    
    # .env.example作成（既存がない場合）
    if [ ! -f ".env.example" ]; then
        cat > .env.example << 'EOF'
# Discord Bot設定
DISCORD_TOKEN=your_discord_bot_token_here
APPLICATION_ID=your_application_id_here
DEBUG_GUILD_ID=your_debug_guild_id_here
EOF
        log_info ".env.exampleを作成しました"
    fi
    
    # .envファイル作成（既存がない場合）
    if [ ! -f ".env" ]; then
        cp .env.example .env
        log_warn ".envファイルを作成しました。実際のトークンを設定してください。"
    fi
    
    # TTS設定ファイル作成（既存がない場合）
    if [ ! -f "data/tts_config.json" ]; then
        cat > data/tts_config.json << 'EOF'
{
  "api_url": "http://192.168.0.99:5000",
  "timeout": 30,
  "cache_size": 5,
  "cache_hours": 24,
  "max_text_length": 100,
  "model_id": 7,
  "speaker_id": 0,
  "style": "Neutral",
  "greeting": {
    "enabled": false,
    "skip_on_startup": true,
    "startup_message": "おもちだよ",
    "join_message": "さん、こんちゃ！",
    "leave_message": "さん、またね！"
  }
}
EOF
        log_info "TTS設定ファイルを作成しました"
    fi
    
    log_info "設定ファイル作成完了"
}

# 起動スクリプト作成
create_startup_scripts() {
    log_step "起動スクリプトを作成中..."
    
    # WSL用起動スクリプト
    cat > scripts/start_wsl.sh << 'EOF'
#!/bin/bash

# WSL用起動スクリプト
cd "$(dirname "$0")/.."

# 色付きログ出力
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 仮想環境の確認とアクティベート
if [ ! -d "venv" ]; then
    log_error "仮想環境が見つかりません。setup_wsl.shを先に実行してください。"
    exit 1
fi

source venv/bin/activate

# 必要なディレクトリを作成
mkdir -p logs cache recordings data

# Pythonパスを設定
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# 設定ファイルの存在確認
if [ ! -f ".env" ]; then
    log_error ".envファイルが見つかりません。Discord Bot Tokenを設定してください。"
    exit 1
fi

if [ ! -f "data/tts_config.json" ]; then
    log_error "TTS設定ファイルが見つかりません。"
    exit 1
fi

# ボットを起動
log_info "yomiageBotExを起動中..."
python3 bot.py
EOF
    
    # 実行権限を付与
    chmod +x scripts/start_wsl.sh
    
    # デーモン用スクリプト
    cat > scripts/start_daemon.sh << 'EOF'
#!/bin/bash

# バックグラウンド起動スクリプト
cd "$(dirname "$0")/.."

# 既存プロセスを確認
if pgrep -f "python3 bot.py" > /dev/null; then
    echo "ボットは既に起動しています。"
    exit 1
fi

# バックグラウンドで起動
nohup ./scripts/start_wsl.sh > logs/bot_output.log 2>&1 &

echo "ボットをバックグラウンドで起動しました。"
echo "ログ確認: tail -f logs/yomiage.log"
echo "停止: ./scripts/stop_daemon.sh"
EOF
    
    # 停止用スクリプト
    cat > scripts/stop_daemon.sh << 'EOF'
#!/bin/bash

# デーモン停止スクリプト
echo "yomiageBotExを停止中..."

# プロセスを探して終了
pids=$(pgrep -f "python3 bot.py")
if [ -n "$pids" ]; then
    kill $pids
    echo "ボットを停止しました (PID: $pids)"
else
    echo "実行中のボットが見つかりません。"
fi
EOF
    
    chmod +x scripts/start_daemon.sh
    chmod +x scripts/stop_daemon.sh
    
    log_info "起動スクリプト作成完了"
}

# システム要件テスト
test_system_requirements() {
    log_step "システム要件をテスト中..."
    
    source venv/bin/activate
    
    # Python モジュール確認
    log_info "Python モジュールをテスト中..."
    python3 -c "
import discord
import aiohttp
import yaml
print('✓ 基本モジュールOK')

try:
    import PyNaCl
    print('✓ PyNaCl OK')
except ImportError as e:
    print('✗ PyNaCl エラー:', e)

try:
    import audioop_lts
    print('✓ audioop-lts OK')
except ImportError:
    try:
        import audioop
        print('✓ audioop OK')
    except ImportError as e:
        print('✗ audioop エラー:', e)
" || log_warn "一部モジュールでエラーが発生しました"
    
    # FFmpeg確認
    if command -v ffmpeg &> /dev/null; then
        ffmpeg_version=$(ffmpeg -version 2>&1 | head -n1)
        log_info "FFmpeg OK: $ffmpeg_version"
    else
        log_error "FFmpegが見つかりません"
    fi
    
    log_info "システム要件テスト完了"
}

# TTS サーバー接続テスト
test_tts_connection() {
    log_step "TTS サーバー接続をテスト中..."
    
    tts_url="http://192.168.0.99:5000"
    
    if curl -s --connect-timeout 5 "$tts_url/voice" > /dev/null; then
        log_info "TTS サーバー接続OK: $tts_url"
    else
        log_warn "TTS サーバーに接続できません: $tts_url"
        log_warn "後でdata/tts_config.jsonのapi_urlを正しいIPアドレスに変更してください"
    fi
}

# セットアップ結果サマリー
show_setup_summary() {
    log_step "セットアップ完了サマリー"
    
    echo "=================================="
    echo "🎉 yomiageBotEx WSL環境セットアップ完了！"
    echo "=================================="
    echo
    echo "📁 プロジェクト構成:"
    echo "  ├── venv/              # Python仮想環境"
    echo "  ├── logs/              # ログファイル"
    echo "  ├── data/              # 設定・データファイル"
    echo "  ├── cache/             # キャッシュファイル"
    echo "  ├── recordings/        # 録音ファイル"
    echo "  └── scripts/           # 起動スクリプト"
    echo
    echo "⚙️  次のステップ:"
    echo "  1. .envファイルにDiscord Bot Tokenを設定"
    echo "     nano .env"
    echo
    echo "  2. TTS設定を確認・調整（必要に応じて）"
    echo "     nano data/tts_config.json"
    echo
    echo "  3. ボットを起動"
    echo "     ./scripts/start_wsl.sh"
    echo
    echo "  または、バックグラウンド起動:"
    echo "     ./scripts/start_daemon.sh"
    echo
    echo "📋 便利なコマンド:"
    echo "  - ログ確認: tail -f logs/yomiage.log"
    echo "  - 停止: ./scripts/stop_daemon.sh"
    echo "  - 状態確認: ps aux | grep bot.py"
    echo
    echo "❓ トラブルシューティング:"
    echo "  - 詳細ガイド: SETUP_WSL.md"
    echo "  - ログファイル: logs/yomiage.log"
    echo
}

# メイン実行
main() {
    echo "🚀 yomiageBotEx WSL環境セットアップを開始します..."
    echo
    
    check_prerequisites
    install_system_packages
    setup_python_environment
    install_python_dependencies
    create_directories
    create_config_templates
    create_startup_scripts
    test_system_requirements
    test_tts_connection
    show_setup_summary
    
    echo "✅ セットアップが完了しました！"
    echo "上記の「次のステップ」に従ってボットを起動してください。"
}

# スクリプト実行
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi