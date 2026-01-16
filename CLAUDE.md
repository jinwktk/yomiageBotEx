# CLAUDE.md - yomiageBotEx Discord Bot プロジェクトドキュメント

## 🎯 プロジェクト概要

**yomiageBotEx**は、Discordボイスチャンネル向けの高機能な読み上げ・音声リレーボットです。Python + py-cord で実装されており、TTS(音声合成)、録音・再生、辞書機能、サーバー間音声リレーなどの機能を提供します。

**現在の状態**: 音声リレー・TTS機能完全動作、リプレイ機能py-cordバグにより要再実装（2025-08-30）

## 🚀 セットアップ・起動方法

### 1. 必要な環境
- **Python 3.10以上**（推奨: 3.13）
- **uv**（Pythonパッケージマネージャー）
- **FFmpeg**（音声処理用）
- **Discord Bot Token**

### 2. 初期セットアップ
```bash
# リポジトリクローン
git clone <repository-url>
cd yomiageBotEx

# 依存関係インストール
uv sync --no-install-project

# 環境変数設定（.envファイル作成）
echo "DISCORD_TOKEN=your_discord_bot_token_here" > .env
echo "DEBUG_GUILD_ID=your_guild_id_here" >> .env
```

### 3. 起動方法
```bash
# 推奨: スクリプトでの起動
./scripts/start.bat    # Windows
./scripts/start.sh     # Linux/macOS

# 手動起動
uv run --no-project python bot.py
```

## 📋 プロジェクト作業指針

### デフォルトツール設定
**このプロジェクトではデフォルトでSerenaを使用してください。**

理由:
- プロジェクト全体の把握と整理が効率的
- ファイル検索・コード分析が高性能
- 大規模リファクタリングに適している
- メモリ機能で作業履歴を保持可能

### 作業メモの記録ルール
**すべての作業内容は必ずCLAUDE.mdに記録してください。**

記録する内容:
- 実装した機能の詳細
- 修正した問題と解決方法
- ファイル・コードの変更内容
- 設定変更の理由と影響
- パフォーマンス改善の結果
- 発生したエラーと対処方法
- テスト結果と確認事項

### 🔄 プロセス管理の重要ルール
**CRITICAL: 複数プロセス重複の防止**

⚠️ **複数プロセス実行禁止**: 必ず1つのBotプロセスのみ実行してください

**起動前チェック手順:**
1. **既存プロセス確認**: `tasklist | findstr python`
2. **重複プロセス停止**: `taskkill /PID [PID] /F`
3. **bot.lockファイル**: 自動的に重複実行を防止
4. **単一プロセス起動**: 1つのBotプロセスのみ実行

**理由**: 複数Botプロセスが同時実行されると以下の問題が発生
- Discord API制限による接続エラー
- 音声録音の競合・破損
- リソース使用量の増大
- デバッグの困難化

**注意**: bot.lockファイルで自動的に重複実行を防止しますが、手動確認も推奨

## 🏗️ アーキテクチャ

### Cog構成（7つの主要モジュール）
1. **`cogs/voice.py`** - ボイスチャンネル管理、自動参加・退出
2. **`cogs/tts.py`** - TTS機能、Style-Bert-VITS2統合
3. **`cogs/message_reader.py`** - チャット読み上げ機能
4. **`cogs/recording.py`** - 録音・リプレイ機能
5. **`cogs/dictionary.py`** - 辞書機能（単語置換）
6. **`cogs/user_settings.py`** - ユーザー別設定管理
7. **`cogs/relay.py`** - 音声リレー（サーバー間音声転送）

### 主要ユーティリティ
- **`utils/tts.py`** - TTS API管理とキャッシュシステム
- **`utils/audio_relay.py`** - 音声リレーエンジン
- **`utils/real_audio_recorder.py`** - 音声録音システム
- **`utils/recording_callback_manager.py`** - 録音コールバック管理
- **`utils/replay_buffer_manager.py`** - リプレイバッファ管理
- **`utils/smooth_audio_relay.py`** - スムーズ音声リレー実装

## 📁 フォルダ構成

### 現在のプロジェクト構成
```
yomiageBotEx/
├── bot.py              # メインボットファイル（Cog構造対応）
├── config.yaml         # 設定ファイル
├── .env               # Discordトークン（Gitignore対象）
├── .gitignore         # Git除外設定
├── pyproject.toml      # uv用プロジェクト設定
├── CLAUDE.md          # このファイル
├── cogs/              # Cogモジュール
│   ├── __init__.py    # Cogパッケージ初期化
│   ├── voice.py       # ボイスチャンネル管理Cog
│   ├── tts.py         # TTS機能Cog
│   ├── recording.py   # 録音・リプレイ機能Cog
│   ├── message_reader.py # チャット読み上げ機能Cog
│   ├── dictionary.py  # 辞書機能Cog
│   ├── user_settings.py # ユーザー設定機能Cog
│   └── relay.py       # 音声横流し（リレー）機能Cog
├── utils/             # ユーティリティモジュール
│   ├── __init__.py    # ユーティリティパッケージ初期化
│   ├── logger.py      # ロギング設定ユーティリティ（ローテーション付き）
│   ├── tts.py         # TTS機能ユーティリティ（モデル選択付き）
│   ├── audio_processor.py # 音声処理（ノーマライズ、フィルタリング）
│   ├── dictionary.py  # 辞書管理システム
│   ├── user_settings.py # ユーザー別設定管理
│   ├── real_audio_recorder.py # 統合版音声録音システム
│   ├── audio_relay.py # 音声リレーシステム
│   ├── recording_callback_manager.py # 録音コールバック管理
│   ├── replay_buffer_manager.py # リプレイバッファ管理
│   └── smooth_audio_relay.py # スムーズ音声リレー実装
├── scripts/           # 起動スクリプト
│   ├── start.sh       # Linux/macOS用起動スクリプト
│   ├── start.bat      # Windows用起動スクリプト
├── pyproject.toml     # uv用プロジェクト設定
├── uv.lock           # uv依存関係ロックファイル
├── bot.lock          # プロセス重複防止ロックファイル（自動生成）
├── sessions.json     # セッション復元データ（自動生成）
├── cache/            # TTSキャッシュディレクトリ（自動生成）
├── recordings/       # 録音ファイルディレクトリ（自動生成）
├── data/             # データディレクトリ（自動生成）
│   ├── tts_config.json    # TTS設定（Git除外対象）
│   ├── dictionary.json    # 辞書データ
│   └── user_settings.json # ユーザー設定データ
└── logs/             # ログディレクトリ（自動生成）
    └── yomiage.log   # 現在のログ（ローテーション対応）
```

## 🎮 利用可能コマンド

### 基本機能
- `/join` - ボイスチャンネルに参加
- `/leave` - ボイスチャンネルから退出
- `/reading` - チャット読み上げのON/OFF切り替え

### 録音・再生
- `/replay [duration] [user]` - 指定時間分の音声を録音・投稿（1-300秒）
- `/recordings` - 最近の録音リスト表示

### 辞書機能
- `/dict_add <word> <reading>` - 辞書に単語追加
- `/dict_remove <word>` - 辞書から単語削除

### ユーザー設定
- `/my_settings` - 個人設定を表示
- `/set_reading` - 読み上げ設定変更
- `/set_global_tts` - サーバー全体TTS設定（管理者限定）

### 音声リレー（管理者限定）
- `/relay_start` - 音声リレーセッション開始
- `/relay_stop` - 音声リレーセッション停止
- `/relay_status` - アクティブセッション表示

## ⚙️ 設定ファイル

### `config.yaml` - メイン設定
```yaml
bot:
  admin_user_id: 372768430149074954  # 管理者ユーザーID
  auto_join: true                   # 自動参加機能
  auto_leave: true                  # 自動退出機能

audio_relay:
  enabled: true                     # 音声リレー機能
  auto_start: true                  # 自動開始
  auto_relay_pairs:                 # 自動リレー設定
    - source_guild_id: 995627275074666568
      target_guild_id: 813783748566581249
      # ... その他設定

recording:
  enabled: true
  max_duration: 300                 # 最大録音時間（秒）
  default_duration: 30              # デフォルト録音時間

message_reading:
  enabled: true                     # チャット読み上げ
  max_length: 100                   # 最大文字数
  ignore_prefixes: ["!", "/", ".", "?", "`", ";"]       # 無視するプレフィックス
```

### `.env` - 秘密情報
```env
DISCORD_TOKEN=your_bot_token_here
DEBUG_GUILD_ID=your_guild_id_here
```

### `data/tts_config.json` - TTS設定（動的に変更）
```json
{
  "api_base_url": "http://192.168.0.99:5000",
  "default_model_id": 0,
  "default_speaker_id": 0,
  "default_style": "Neutral"
}
```

## 🔧 開発・デバッグ

### 開発環境セットアップ
```bash
# 開発用依存関係インストール
uv sync --dev --no-install-project

# コードフォーマット
uv run black .

# リンター実行
uv run flake8 .

# テスト実行
uv run pytest
```

### ログ確認
```bash
# リアルタイムログ
tail -f logs/yomiage.log

# ログレベルの変更（config.yaml）
logging:
  level: "DEBUG"  # INFO → DEBUG
```

### デバッグ用スクリプト
- **`python check_relay_status.py`** - 音声リレー状態確認
- **`python test_real_audio.py`** - 音声録音テスト

## 🎵 主要機能詳細

### 1. 音声リレー機能
- **機能**: あるDiscordサーバーの音声を別のサーバーに転送
- **自動開始**: config.yamlの設定に基づいて起動時に自動開始
- **セッション管理**: 複数セッションの同時実行、状態監視
- **パフォーマンス**: リアルタイム音声ストリーミング、遅延最小化

### 2. 録音・リプレイ機能
- **リングバッファ**: 最大5分間の音声を常時バッファリング
- **時間指定再生**: `/replay 30` で30秒分の音声を取得
- **ユーザー別録音**: 個別ユーザーまたは全員の音声を選択可能
- **自動クリーンアップ**: 1時間後に録音ファイルを自動削除

### 3. TTS統合
- **Style-Bert-VITS2**: 高品質な日本語音声合成
- **キャッシュシステム**: 音声ファイルの自動キャッシュで高速化
- **フォールバック**: API不通時のビープ音代替再生
- **モデル選択**: 複数の音声モデル・話者から選択可能

### 4. 辞書機能
- **読み替え**: チャット読み上げ時の単語置換
- **Guild別管理**: サーバーごとの独立した辞書
- **動的更新**: 実行中の辞書追加・削除

## 🛠️ トラブルシューティング

### よくある問題

#### 1. スラッシュコマンドが表示されない
```
対処: Bot再起動後、Discordクライアントも再起動
時間: コマンド同期に最大数分かかる場合あり
```

#### 2. 音声接続エラー
```
ログ確認: "Voice connection attempt failed"
対処: config.yamlのtimeout設定を調整
```

#### 3. 録音機能が動作しない
```
原因: py-cord WaveSinkのPCMデータ取得問題
状態: 既知の問題、修復作業中
回避策: 音声リレー機能は正常動作
```

#### 4. TTS APIエラー
```
確認: Style-Bert-VITS2サーバーの起動状態
URL: http://192.168.0.99:5000/status
フォールバック: API不通時はビープ音で代替
```

#### 5. プロセス重複エラー
```
確認: tasklist | findstr python
停止: taskkill /PID [PID] /F
対策: bot.lockファイルで自動防止
```

## 📋 実装状況・開発履歴

### 完了した機能（最新状態）
- ✅ **全7つのCogシステム完全動作**
  - voice.py: ボイスチャンネル管理
  - tts.py: Style-Bert-VITS2統合
  - message_reader.py: チャット読み上げ
  - recording.py: 録音・リプレイ
  - dictionary.py: 辞書機能
  - user_settings.py: ユーザー設定
  - relay.py: 音声リレー

- ✅ **音声リレー機能**（サーバー間音声転送）
  - 自動開始機能
  - セッション管理
  - 複数同時セッション対応

- ✅ **TTS読み上げ機能**（Style-Bert-VITS2統合）
  - キャッシュシステム
  - フォールバック機能
  - モデル・話者選択

- ✅ **自動参加・退出機能**
  - ユーザー参加時の自動VC参加
  - 退出時の自動VC離脱
  - セッション復元機能

- ✅ **辞書機能・ユーザー設定**
  - 単語置換システム
  - ユーザー別設定管理
  - 動的設定変更

- ✅ **プロセス重複防止システム**
  - bot.lockファイル
  - 単一プロセス実行強制

### 現在の問題・修復中
- ⚠️ **リプレイ機能**（py-cord WaveSinkバグ）
  - PCMデータが0バイトで音声データ取得不可
  - 録音機能の代替実装検討中
  - 音声リレー機能は正常動作

- 🔧 **メモリ最適化**（長期実行時）
  - 長時間実行時のメモリリーク対策
  - バッファ管理の最適化

### 技術的ハイライト
- **アーキテクチャ**: Cog-based modular design
- **非同期処理**: asyncio/await パターンの徹底
- **リソース管理**: 適切なクリーンアップとセッション管理
- **エラーハンドリング**: 包括的例外処理システム
- **設定管理**: YAML + JSON による柔軟な設定システム

### 重要な技術的決定
1. **py-cord採用**: discord.pyではなくpy-cordを使用
2. **単一プロセス実行**: bot.lockファイルによる重複防止
3. **Cog構造**: 機能別のモジュール分割
4. **非同期処理**: asyncio/awaitパターンの徹底
5. **リソース管理**: 適切なクリーンアップとセッション管理

### 既知の制限事項
- **録音機能**: py-cord WaveSinkのPCMデータ取得問題
- **メモリ使用量**: 長時間実行時のメモリリーク対策必要
- **TTS依存**: Style-Bert-VITS2サーバーへの依存

### セキュリティ考慮事項
- **管理者権限**: admin_user_idによる機能制限
- **プライベートメッセージ**: ephemeral=trueによる応答
- **設定ファイル**: .envファイルのGitignore設定
- **トークン保護**: ログ出力からのトークン除外

### 今後の改善予定
- WebUI管理画面の追加
- 音声品質の更なる向上  
- 録音機能の代替実装
- パフォーマンス最適化
- discord.py移行の検討

---

**プロジェクト状態**: 安定版・運用可能（リプレイ機能を除く全機能正常動作）

**重要**: このドキュメントは実際の実装状況に基づいて作成されています。新機能追加・バグ修正時は、必ずCLAUDE.mdを更新してください。
