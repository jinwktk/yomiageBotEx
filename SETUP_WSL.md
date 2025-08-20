# yomiageBotEx WSL環境セットアップガイド

## 概要
このガイドは、yomiageBotEx Discord読み上げボットを他のPC（WSL/Linux環境）で動作させるための環境構築手順です。

## 前提条件
- WSL2がインストール済み（Ubuntu 20.04/22.04推奨）
- インターネット接続
- Discord Bot Token
- Style-Bert-VITS2（Serena）サーバーのIPアドレス

## 1. システム要件

### OS・環境
- WSL2 (Ubuntu 20.04/22.04)
- Python 3.10以上（3.13推奨）
- Git
- FFmpeg

### 推奨スペック
- メモリ: 4GB以上
- ストレージ: 2GB以上の空き容量

## 2. 必要なシステムパッケージのインストール

```bash
# システムパッケージの更新
sudo apt update && sudo apt upgrade -y

# 必要なパッケージをインストール
sudo apt install -y \
    python3 \
    python3-pip \
    python3-venv \
    git \
    ffmpeg \
    build-essential \
    libffi-dev \
    libssl-dev \
    libopus-dev \
    libsodium-dev \
    pkg-config

# Python開発ツール
sudo apt install -y \
    python3-dev \
    python3-setuptools \
    python3-wheel
```

## 3. プロジェクトのクローンと環境構築

```bash
# プロジェクトをクローン
git clone https://github.com/yourusername/yomiageBotEx.git
cd yomiageBotEx

# Python仮想環境を作成
python3 -m venv venv
source venv/bin/activate

# Python依存関係のインストール（順番重要）
pip install --upgrade pip setuptools wheel

# 音声関連の依存関係を先にインストール
pip install PyNaCl==1.5.0
pip install audioop-lts

# discord.py（Python 3.13対応版）
pip install discord.py[voice]>=2.3.0

# その他の依存関係
pip install aiofiles aiohttp pyyaml python-dotenv
```

## 4. 必要なPythonライブラリ詳細

### 重要な依存関係
```
discord.py[voice]>=2.3.0    # Discord API（音声機能込み）
PyNaCl==1.5.0               # 音声暗号化
audioop-lts                 # Python 3.13互換性
aiofiles                    # 非同期ファイル操作
aiohttp                     # HTTPクライアント
pyyaml                      # YAML設定ファイル
python-dotenv               # 環境変数管理
```

### システムレベル依存関係（重要）
```
ffmpeg          # 音声処理・再生（必須）
libopus-dev     # Opus音声コーデック（Discord音声用）
libsodium-dev   # 暗号化ライブラリ（音声暗号化用）
libffi-dev      # Foreign Function Interface
build-essential # C/C++コンパイラ（PyNaClビルド用）
```

**FFmpegについて**：
- Discord音声再生に必須
- WAVファイル処理・変換に使用
- `sudo apt install ffmpeg`でインストール

## 5. 設定ファイルの準備

### 5.1 Discord Bot Token設定
```bash
# .envファイルを作成
cp .env.example .env

# .envファイルを編集（実際のトークンに置き換え）
cat > .env << 'EOF'
DISCORD_TOKEN=your_discord_bot_token_here
APPLICATION_ID=your_application_id_here
DEBUG_GUILD_ID=your_debug_guild_id_here
EOF
```

### 5.2 TTS設定ファイル
```bash
# dataディレクトリを作成
mkdir -p data

# TTS設定を作成
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
```

### 5.3 config.yamlの確認
```yaml
bot:
  auto_join: true
  auto_leave: true
  rate_limit_delay: [0.5, 1.0]
  admin_user_id: 372768430149074954

message_reading:
  enabled: true
  max_length: 100
  ignore_prefixes: ["!", "/", ".", "?"]
  ignore_bots: true

logging:
  level: INFO
  rotation:
    max_bytes: 10485760
    backup_count: 5
    compress: true
    rotate_on_startup: true
```

## 6. 起動用スクリプト作成

### 6.1 Linux用起動スクリプト
```bash
# scripts/start_wsl.sh を作成
mkdir -p scripts
cat > scripts/start_wsl.sh << 'EOF'
#!/bin/bash

# WSL用起動スクリプト
cd "$(dirname "$0")/.."

# 仮想環境をアクティベート
source venv/bin/activate

# ログディレクトリを作成
mkdir -p logs cache recordings data

# Pythonパスを設定
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# ボットを起動
echo "Starting yomiageBotEx..."
python3 bot.py

# 終了時にログを表示
echo "Bot stopped. Check logs/yomiage.log for details."
EOF

# 実行権限を付与
chmod +x scripts/start_wsl.sh
```

### 6.2 systemdサービス設定（オプション）
```bash
# サービスファイルを作成
sudo tee /etc/systemd/system/yomiagebot.service > /dev/null << EOF
[Unit]
Description=yomiageBotEx Discord TTS Bot
After=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$(pwd)
Environment=PATH=$(pwd)/venv/bin
ExecStart=$(pwd)/venv/bin/python $(pwd)/bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# サービスを有効化（オプション）
# sudo systemctl daemon-reload
# sudo systemctl enable yomiagebot
# sudo systemctl start yomiagebot
```

## 7. トラブルシューティング

### 7.1 Python 3.13での音声関連エラー
```bash
# audioopエラーが発生した場合
pip install audioop-lts

# PyNaClエラーが発生した場合
sudo apt install libffi-dev libssl-dev
pip install --upgrade PyNaCl
```

### 7.2 FFmpegエラー
```bash
# FFmpegが見つからない場合
sudo apt install ffmpeg

# パスを確認
which ffmpeg
```

### 7.3 権限エラー
```bash
# 実行権限を付与
chmod +x scripts/start_wsl.sh

# ファイル所有権を確認
sudo chown -R $USER:$USER .
```

### 7.4 ネットワーク接続エラー
```bash
# DNS設定を確認
cat /etc/resolv.conf

# Style-Bert-VITS2サーバーへの接続テスト
curl -X POST http://192.168.0.99:5000/voice \
  -H "Content-Type: application/json" \
  -d '{"text": "テスト", "model_id": 7, "speaker_id": 0}'
```

## 8. 起動手順

### 手動起動
```bash
# 1. プロジェクトディレクトリに移動
cd yomiageBotEx

# 2. 仮想環境をアクティベート
source venv/bin/activate

# 3. ボットを起動
./scripts/start_wsl.sh
```

### バックグラウンド起動
```bash
# nohupで起動
nohup ./scripts/start_wsl.sh > logs/bot_output.log 2>&1 &

# プロセスID確認
ps aux | grep bot.py
```

## 9. 動作確認

### 9.1 ログ確認
```bash
# リアルタイムログ監視
tail -f logs/yomiage.log

# エラーログ確認
grep -i error logs/yomiage.log
```

### 9.2 機能テスト
1. Discordでボットがオンライン状態か確認
2. 音声チャンネルに自動参加しているか確認
3. チャットメッセージを送信して読み上げるか確認

## 10. パフォーマンス最適化

### 10.1 メモリ使用量監視
```bash
# プロセス監視
htop
ps aux | grep python

# メモリ使用量確認
free -h
```

### 10.2 ログローテーション設定
```bash
# logrotateを設定（オプション）
sudo tee /etc/logrotate.d/yomiagebot > /dev/null << 'EOF'
/path/to/yomiageBotEx/logs/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 644 $USER $USER
}
EOF
```

## 11. セキュリティ設定

### 11.1 ファイアウォール設定
```bash
# UFWを設定（オプション）
sudo ufw allow ssh
sudo ufw enable
```

### 11.2 環境変数保護
```bash
# .envファイルの権限を制限
chmod 600 .env

# gitignoreで.envを除外確認
echo ".env" >> .gitignore
```

## 12. 更新手順

```bash
# 1. 最新版を取得
git pull origin main

# 2. 依存関係を更新
source venv/bin/activate
pip install --upgrade -r requirements.txt

# 3. 設定ファイルを確認
# 新しい設定項目があれば追加

# 4. ボットを再起動
./scripts/start_wsl.sh
```

## よくある問題と解決法

| 問題 | 原因 | 解決法 |
|------|------|--------|
| `audioop not found` | Python 3.13互換性 | `pip install audioop-lts` |
| `PyNaCl build failed` | 開発ツール不足 | `sudo apt install build-essential libffi-dev` |
| `FFmpeg not found` | FFmpeg未インストール | `sudo apt install ffmpeg` |
| `Permission denied` | 実行権限不足 | `chmod +x scripts/start_wsl.sh` |
| `TTS connection failed` | ネットワーク設定 | IPアドレス・ポート番号確認 |

## サポート

問題が発生した場合は、以下のログファイルを確認してください：
- `logs/yomiage.log` - メインログ
- `logs/bot_output.log` - 起動ログ（nohup使用時）

重要なエラーメッセージをメモして、GitHub Issuesで報告してください。