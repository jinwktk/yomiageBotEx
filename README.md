# yomiageBotEx v2 - シンプル録音機能付き読み上げBot

## 概要

シンプルで理解しやすい録音機能付きDiscord読み上げBotです。
複雑な機能を排除し、コア機能のみに特化した軽量設計。

## 主要機能

### 🎵 コア機能（必須）
- **読み上げ機能**: StyleBertVITS2による高品質音声合成
- **録音・リプレイ機能**: ボイスチャンネルの音声録音と再生
- **VC操作**: 自動・手動でのボイスチャンネル参加退出

### 🔧 オプション機能
- **辞書機能**: 単語の読み方変更

## セットアップ

### 1. 依存関係インストール
```bash
pip install -r requirements_v2.txt
```

### 2. 環境設定
`.env`ファイルを作成:
```
DISCORD_TOKEN=your_discord_bot_token_here
```

### 3. 設定ファイル
`config_v2.yaml`で各種設定を調整（デフォルトのままでも動作）

### 4. Bot起動
```bash
python bot_v2.py
```

または
```bash
python test_v2.py  # テスト用
```

## 利用可能コマンド

### 基本操作
- `/join` - ボイスチャンネルに参加
- `/leave` - ボイスチャンネルから退出
- `/reading on/off` - 読み上げ機能のON/OFF切り替え

### 録音機能
- `/replay [秒数]` - 録音した音声を再生（デフォルト30秒）

### 辞書機能（オプション）
- `/dict_add 単語 読み方` - 辞書に単語を追加
- `/dict_remove 単語` - 辞書から単語を削除

## StyleBertVITS2設定

デフォルトで`http://localhost:5000`のTTS APIサーバーに接続します。

### APIサーバー起動方法
1. [Style-Bert-VITS2](https://github.com/litagin02/Style-Bert-VITS2)をインストール
2. APIサーバーを起動:
```bash
python server_fastapi.py --port 5000
```

## ファイル構成

```
yomiageBotEx/
├── bot_v2.py              # メインBot
├── config_v2.yaml         # 設定ファイル
├── requirements_v2.txt    # 依存関係
├── test_v2.py            # テスト起動スクリプト
├── .env                  # Discordトークン
├── cogs_v2/              # 機能モジュール
│   ├── voice.py          # VC操作
│   ├── tts.py            # 読み上げ機能
│   ├── recording.py      # 録音機能
│   └── dictionary.py     # 辞書機能
└── utils_v2/             # ユーティリティ
    ├── tts_client.py     # TTS API連携
    └── audio_recorder.py # 音声録音処理
```

## v1からの主な変更点

### ✅ 改善点
- **シンプル化**: 複雑な機能を削除、コア機能に特化
- **理解しやすさ**: コードの可読性とデバッグ性を向上
- **保守性**: ファイル数を削減、依存関係を最小限に

### ❌ 削除された機能
- ユーザー個人設定システム
- パフォーマンス監視
- 複雑な音声処理（ノーマライズ等）
- ログローテーション
- ホットリロード機能
- 複雑なエラーハンドリング

## トラブルシューティング

### よくある問題

1. **スラッシュコマンドが表示されない**
   - Bot再起動後、Discordクライアントも再起動
   - コマンド同期に数分かかる場合があります

2. **TTS APIに接続できない**
   - StyleBertVITS2サーバーが起動しているか確認
   - `config_v2.yaml`のapi_url設定を確認

3. **録音機能が動作しない**
   - py-cord[voice]がインストールされているか確認
   - FFmpegがシステムにインストールされているか確認

## 開発・デバッグ

### ログ確認
```bash
tail -f bot_v2.log
```

### 設定変更
`config_v2.yaml`を編集後、Bot再起動

## ライセンス

このプロジェクトはMITライセンスの下で公開されています。