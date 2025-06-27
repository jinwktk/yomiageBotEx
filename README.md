# yomiageBotEx - Discord読み上げボット

Discordボイスチャンネルで読み上げ機能を提供するボット（Python版）

## 🚀 クイックスタート

### 1. 必要なもの
- Python 3.9以上
- Discord Bot Token
- FFmpeg（音声処理用）※Phase 3以降で必要

### 2. インストール

```bash
# リポジトリのクローン
git clone https://github.com/yourusername/yomiageBotEx.git
cd yomiageBotEx

# 依存関係のインストール
pip install -r requirements.txt
```

### 3. 設定

1. `.env`ファイルを作成し、Discordトークンを設定：
```env
DISCORD_TOKEN=your_discord_bot_token_here
```

2. `config.yaml`で各種設定を調整（オプション）

### 4. 起動

```bash
python bot.py
```

## 📝 コマンド一覧

| コマンド | 説明 |
|---------|------|
| `/join` | ボイスチャンネルに参加 |
| `/leave` | ボイスチャンネルから退出 |

## 🔧 設定ファイル

`config.yaml`で以下の設定が可能：
- ボットの基本設定
- ロギング設定
- レート制限設定

詳細は`config.yaml`のコメントを参照してください。

## 📋 実装状況

- ✅ Phase 1: 基本機能（VC参加・退出）
- ⏳ Phase 2: 自動参加・退出機能
- ⏳ Phase 3: 読み上げ機能（Style-Bert-VITS2）
- ⏳ Phase 4: 録音・リプレイ機能

## 🐛 トラブルシューティング

### スラッシュコマンドが表示されない
- Botを再起動後、Discordクライアントも再起動してください
- コマンドの同期には数分かかることがあります

### Invalid token エラー
- `.env`ファイルのトークンを確認してください
- トークンの前後に余分なスペースがないか確認してください

## 📄 ライセンス

MIT License