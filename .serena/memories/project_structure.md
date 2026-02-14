# プロジェクト構造

## ディレクトリ構成

```
yomiageBotEx/
├── bot.py              # メインボットファイル（Cog構造対応）
├── config.yaml         # 設定ファイル
├── .env               # Discordトークン（Gitignore対象）
├── .gitignore         # Git除外設定
├── pyproject.toml     # プロジェクト設定と依存関係（uv使用）
├── uv.lock           # 依存関係のロックファイル
├── CLAUDE.md          # プロジェクト文書・作業履歴
├── README.md          # プロジェクト概要・セットアップガイド
├── cogs/              # Cogモジュール
├── utils/             # ユーティリティモジュール
├── scripts/           # 起動スクリプト
├── cache/             # TTSキャッシュディレクトリ（自動生成）
├── recordings/        # 録音ファイルディレクトリ（自動生成）
├── data/              # データディレクトリ（自動生成）
└── logs/              # ログディレクトリ（自動生成）
```

## 主要ファイル

### bot.py
- メインボットクラス: `YomiageBot`
- Cogの動的ロード機能
- カスタムVoiceClient実装
- プロセス管理（シングルプロセス強制）

### cogs/ ディレクトリ
- **voice.py**: ボイスチャンネル管理Cog
- **tts.py**: TTS機能Cog  
- **recording.py**: 録音・リプレイ機能Cog
- **message_reader.py**: チャット読み上げ機能Cog
- **dictionary.py**: 辞書機能Cog
- **user_settings.py**: ユーザー設定機能Cog
- **relay.py**: 音声横流し（リレー）機能Cog

### utils/ ディレクトリ
- **logger.py**: ロギング設定（ローテーション付き）
- **tts.py**: TTS機能ユーティリティ（モデル選択付き）
- **recording.py**: 録音・リプレイ機能ユーティリティ
- **audio_processor.py**: 音声処理（ノーマライズ、フィルタリング）
- **dictionary.py**: 辞書管理システム
- **user_settings.py**: ユーザー別設定管理
- **real_audio_recorder.py**: 統合版音声録音
- **audio_relay.py**: 音声横流し（リレー）機能ユーティリティ

### scripts/ ディレクトリ
- **start.bat**: Windows用起動スクリプト
- **start.sh**: Linux/macOS用起動スクリプト

## 自動生成ディレクトリ

### cache/
- **tts/**: TTS音声キャッシュ

### recordings/
- **.wav**: 録音ファイル（1時間後自動削除）

### data/
- **dictionary.json**: 辞書データ
- **user_settings.json**: ユーザー設定データ  
- **tts_config.json**: TTS設定（Git管理下外）

### logs/
- **yomiage.log**: 現在のログ
- **yomiage.log.*.gz**: 過去のログファイル（圧縮）

## アーキテクチャ
- **Cog構造**: 機能別にモジュール化されたDiscordコマンド実装
- **非同期処理**: asyncio使用による非ブロッキング処理
- **イベントドリブン**: Discord.pyのイベントリスナー活用
- **設定駆動**: YAMLファイルによる柔軟な設定管理