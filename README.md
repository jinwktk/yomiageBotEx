# yomiageBotEx - Discord読み上げボット

Discordボイスチャンネルで読み上げ機能を提供するボット（Python版）

## 🚀 クイックスタート

### 1. 必要なもの
- Python 3.9以上（推奨: 3.11）
- [uv](https://docs.astral.sh/uv/) - Pythonパッケージマネージャー
- Discord Bot Token
- FFmpeg（音声処理用）※Phase 3以降で必要

### 2. uvのインストール

```bash
# Linux/macOS
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 3. プロジェクトのセットアップ

```bash
# リポジトリのクローン
git clone https://github.com/jinwktk/yomiageBotEx.git
cd yomiageBotEx

# 依存関係のインストール
uv sync --no-install-project
```

### 4. 設定

1. `.env`ファイルを作成し、Discordトークンを設定：
```env
DISCORD_TOKEN=your_discord_bot_token_here
```

2. `config.yaml`で各種設定を調整（オプション）

### 5. 起動

#### 手動起動
```bash
uv run --no-project python bot.py
```

#### スクリプトを使用（推奨）
```bash
# Linux/macOS
./scripts/start.sh

# Windows
scripts\start.bat
```

## 📝 コマンド一覧

| コマンド | 説明 |
|---------|------|
| `/join` | ボイスチャンネルに参加 |
| `/leave` | ボイスチャンネルから退出 |
| `/replay` | 最近の音声を録音・再生（1-300秒） |
| `/recordings` | 最近の録音リストを表示 |
| `/clear_buffer` | 音声バッファをクリア（管理者のみ） |

## 🔧 設定ファイル

`config.yaml`で以下の設定が可能：
- ボットの基本設定
- ロギング設定
- レート制限設定

詳細は`config.yaml`のコメントを参照してください。

## 📋 実装状況

- ✅ Phase 1: 基本機能（VC参加・退出）
- ✅ Phase 2: 自動参加・退出機能  
- ✅ Phase 3: TTS統合（Style-Bert-VITS2）
- ✅ Phase 4: 録音・リプレイ機能

## 🎵 主な機能

### 基本機能
- Discord ボイスチャンネルへの自動参加・退出
- ユーザーの参加・退出時の挨拶音声再生

### 録音・リプレイ機能
- 最大10分間の音声バッファリング
- `/replay`コマンドで過去の音声を再生
- 録音ファイルの自動管理（1時間後削除）

### TTS機能（オプション）
- Style-Bert-VITS2との連携
- 音声キャッシュによる高速化
- フォールバック機能

## 🛠️ 開発者向け

### 開発環境のセットアップ
```bash
# 開発用依存関係のインストール
uv sync --dev --no-install-project

# コードフォーマット
uv run black .

# リンター実行
uv run flake8 .

# テスト実行
uv run pytest
```

## 🐛 トラブルシューティング

### スラッシュコマンドが表示されない
- Botを再起動後、Discordクライアントも再起動してください
- コマンドの同期には数分かかることがあります

### Invalid token エラー
- `.env`ファイルのトークンを確認してください
- トークンの前後に余分なスペースがないか確認してください

## 📄 ライセンス

MIT License