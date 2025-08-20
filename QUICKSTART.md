# yomiageBotEx クイックスタート

## 🚀 他のPCでの環境構築（自動）

### 1. WSL/Linux環境
```bash
# リポジトリをクローン
git clone https://github.com/yourusername/yomiageBotEx.git
cd yomiageBotEx

# 自動セットアップスクリプトを実行
./scripts/setup_wsl.sh
```

### 2. Discord Bot Tokenを設定
```bash
# .envファイルを編集
nano .env

# 以下の値を実際のものに置き換え
DISCORD_TOKEN=your_actual_bot_token
APPLICATION_ID=your_actual_application_id
```

### 3. TTS サーバー設定（必要に応じて）
```bash
# TTS設定ファイルを編集
nano data/tts_config.json

# api_urlを実際のStyle-Bert-VITS2サーバーIPに変更
{
  "api_url": "http://YOUR_TTS_SERVER_IP:5000",
  ...
}
```

### 4. ボットを起動
```bash
# フォアグラウンド起動
./scripts/start_wsl.sh

# または、バックグラウンド起動
./scripts/start_daemon.sh
```

## 📋 動作確認チェックリスト

- [ ] ボットがDiscordでオンライン状態
- [ ] 音声チャンネルに自動参加
- [ ] チャットメッセージを音声で読み上げ
- [ ] ログにエラーが出ていない

## 🛠️ トラブルシューティング

### よくある問題
```bash
# ログ確認
tail -f logs/yomiage.log

# プロセス確認
ps aux | grep bot.py

# 停止
./scripts/stop_daemon.sh
```

### 詳細ガイド
- **完全な手順**: `SETUP_WSL.md`
- **ログファイル**: `logs/yomiage.log`
- **設定ファイル**: `data/tts_config.json`, `.env`

## 🎯 現在の機能

✅ **実装済み機能**
- 自動音声チャンネル参加・退出
- チャットメッセージ読み上げ（Style-Bert-VITS2）
- 辞書機能（単語の読み方変換）
- 音声録音・リプレイ機能
- ユーザー設定管理
- ログローテーション

⚠️ **制限事項**
- Discord 1ボット = 1音声チャンネル制限
- スラッシュコマンドはdiscord.py互換性修正が必要
- Python 3.13環境では特別な音声ライブラリが必要

## 📞 サポート

問題が発生した場合：
1. `logs/yomiage.log`でエラーメッセージを確認
2. `SETUP_WSL.md`のトラブルシューティング参照
3. GitHub Issuesで報告