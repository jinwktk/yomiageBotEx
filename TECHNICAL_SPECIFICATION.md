# yomiageBotEx 技術仕様書

## 📋 プロジェクト概要

**yomiageBotEx**は、Discordボイスチャンネル向けの多機能読み上げ・音声リレーボットです。Python + py-cordで実装されており、モジュラーなCog構造を採用しています。

- **バージョン**: 0.2.0
- **言語**: Python 3.10以上
- **主要フレームワーク**: py-cord[voice] >=2.4.0
- **アーキテクチャ**: Cog-based modular design

## 🏗️ システムアーキテクチャ

### 全体構成
```
yomiageBotEx/
├── bot.py                 # メインボット（YomiageBot クラス）
├── config.yaml           # 設定ファイル
├── cogs/                 # Cogモジュール（7つの主要機能）
├── utils/                # ユーティリティモジュール（14個のモジュール）
├── scripts/              # 起動スクリプト
├── data/                 # 動的データ（JSON設定、辞書等）
└── logs/                 # ログファイル（ローテーション対応）
```

### Cogモジュール構成（7つの主要機能）

#### 1. VoiceCog (`cogs/voice.py`)
- **機能**: ボイスチャンネル管理の中核
- **主要コマンド**: `/join`, `/leave`
- **主要機能**:
  - 自動参加・退出機能（config.yaml設定に基づく）
  - セッション復元機能（`sessions.json`）
  - ユーザー参加・退出時の音声通知
  - 空きチャンネル自動検出・退出

#### 2. TTSCog (`cogs/tts.py`)
- **機能**: Text-to-Speech（音声合成）機能
- **主要コマンド**: `/set_global_tts`（管理者限定）
- **主要機能**:
  - Style-Bert-VITS2 API統合
  - 音声キャッシュシステム（`cache/`）
  - フォールバック機能（ビープ音代替再生）
  - モデル・話者選択機能

#### 3. RecordingCog (`cogs/recording.py`)
- **機能**: 音声録音・リプレイ機能
- **主要コマンド**: `/replay [duration] [user]`, `/recordings`
- **主要機能**:
  - リアルタイム音声バッファリング（最大10分）
  - 時間指定録音（1-300秒）
  - ユーザー別録音機能
  - 自動ファイルクリーンアップ（1時間後削除）

#### 4. MessageReaderCog (`cogs/message_reader.py`)
- **機能**: チャットメッセージ読み上げ
- **主要コマンド**: `/reading`（読み上げON/OFF切り替え）
- **主要機能**:
  - リアルタイムチャット読み上げ
  - URL・メンション・絵文字の自動変換
  - プレフィックス除外機能（`!`, `/`, `.`, `?`）
  - 辞書機能との連携

#### 5. DictionaryCog (`cogs/dictionary.py`)
- **機能**: 読み上げ用辞書管理
- **主要コマンド**: `/dict_add <word> <reading>`, `/dict_remove <word>`
- **主要機能**:
  - Guild別辞書管理
  - 動的な単語追加・削除
  - JSON形式でのデータ永続化（`data/dictionary.json`）

#### 6. UserSettingsCog (`cogs/user_settings.py`)
- **機能**: ユーザー別設定管理
- **主要コマンド**: `/my_settings`, `/set_reading`
- **主要機能**:
  - ユーザー別読み上げ設定
  - TTS音声設定のカスタマイズ
  - 設定データの永続化（`data/user_settings.json`）

#### 7. RelayCog (`cogs/relay.py`)
- **機能**: サーバー間音声リレー（音声横流し機能）
- **主要コマンド**: `/relay_start`, `/relay_stop`, `/relay_status`（管理者限定）
- **主要機能**:
  - 複数セッション並列実行
  - 自動リレー開始（config.yaml設定）
  - リアルタイム音声ストリーミング
  - セッション管理・監視

## 🛠️ ユーティリティモジュール（utils/）

### 音声処理系
- **`audio_relay.py`**: 音声リレーエンジン（RelaySession, FixedAudioRelay, StreamingSink）
- **`smooth_audio_relay.py`**: スムーズ音声リレー実装
- **`real_audio_recorder.py`**: 統合版音声録音システム（RealTimeAudioRecorder）
- **`audio_processor.py`**: 音声正規化・フィルタリング処理
- **`direct_audio_capture.py`**: 直接音声キャプチャ機能

### データ管理系
- **`dictionary.py`**: 辞書管理システム
- **`user_settings.py`**: ユーザー設定管理
- **`tts.py`**: TTS API管理とキャッシュシステム
- **`recording_callback_manager.py`**: 録音コールバック管理
- **`replay_buffer_manager.py`**: リプレイバッファ管理

### システム系
- **`logger.py`**: ログローテーション設定（圧縮付き）

### レガシー・参考ファイル
- **`audio_relay_old.py`**: 旧版音声リレー
- **`simple_audio_relay_old.py`**: シンプル音声リレー（参考実装）

## ⚙️ 設定システム

### メイン設定（`config.yaml`）
```yaml
bot:
  admin_user_id: 372768430149074954  # 管理者権限
  auto_join: true                   # 自動参加機能
  auto_leave: true                  # 自動退出機能

audio_relay:
  enabled: true                     # 音声リレー有効
  auto_start: true                  # 起動時自動開始
  auto_relay_pairs:                 # 自動リレー設定
    - source_guild_id: 995627275074666568
      target_guild_id: 813783748566581249
      enabled: true

recording:
  max_duration: 300                 # 最大録音時間（秒）
  default_duration: 30              # デフォルト録音時間

message_reading:
  max_length: 100                   # 最大文字数
  ignore_prefixes: ["!", "/", ".", "?"]
```

### 動的設定（`data/`）
- **`tts_config.json`**: TTS設定（APIエンドポイント、モデル選択）
- **`dictionary.json`**: 辞書データ（Guild別管理）
- **`user_settings.json`**: ユーザー個別設定

### 環境変数（`.env`）
```env
DISCORD_TOKEN=your_bot_token_here
DEBUG_GUILD_ID=your_guild_id_here
```

## 🎮 利用可能コマンド

### 基本機能
| コマンド | 機能 | 権限 |
|---------|------|------|
| `/join` | ボイスチャンネル参加 | 全ユーザー |
| `/leave` | ボイスチャンネル退出 | 全ユーザー |
| `/reading` | チャット読み上げON/OFF | 全ユーザー |

### 録音・再生
| コマンド | 機能 | 権限 |
|---------|------|------|
| `/replay [duration] [user]` | 指定時間分の音声録音・投稿 | 全ユーザー |
| `/recordings` | 最近の録音リスト表示 | 全ユーザー |

### 辞書機能
| コマンド | 機能 | 権限 |
|---------|------|------|
| `/dict_add <word> <reading>` | 辞書に単語追加 | 全ユーザー |
| `/dict_remove <word>` | 辞書から単語削除 | 全ユーザー |

### ユーザー設定
| コマンド | 機能 | 権限 |
|---------|------|------|
| `/my_settings` | 個人設定表示 | 全ユーザー |
| `/set_reading` | 読み上げ設定変更 | 全ユーザー |

### 管理者機能
| コマンド | 機能 | 権限 |
|---------|------|------|
| `/set_global_tts` | サーバー全体TTS設定 | 管理者限定 |
| `/relay_start` | 音声リレーセッション開始 | 管理者限定 |
| `/relay_stop` | 音声リレーセッション停止 | 管理者限定 |
| `/relay_status` | アクティブセッション表示 | 管理者限定 |

## 🔧 技術的特徴

### 非同期処理アーキテクチャ
- **非同期I/O**: `asyncio`による完全非ブロッキング処理
- **並列処理**: 複数音声リレーセッションの同時実行
- **リソース管理**: 適切な接続・リソースクリーンアップ

### 音声処理技術
- **リアルタイムストリーミング**: 低遅延音声転送
- **音声品質向上**: FFmpeg使用による正規化・フィルタリング
- **バッファ管理**: リングバッファによる効率的な音声録音

### データ永続化
- **JSON形式**: 設定・辞書・ユーザーデータの永続化
- **セッション復元**: ボット再起動時の状態復元
- **自動クリーンアップ**: 不要ファイルの定期削除

### エラーハンドリング・安定性
- **包括的例外処理**: 各モジュールでの適切なエラーハンドリング
- **プロセス管理**: `bot.lock`による重複実行防止
- **ログローテーション**: 圧縮付きログ管理

## 📦 依存関係

### 必須依存関係
```toml
[project]
dependencies = [
    "py-cord[voice]>=2.4.0",      # Discordボット・音声機能
    "python-dotenv>=1.0.0",        # 環境変数管理
    "PyYAML>=6.0",                # YAML設定解析
    "aiofiles>=23.0.0",           # 非同期ファイル操作
    "aiohttp>=3.8.0",             # 非同期HTTP通信
    "numpy>=1.24.0",              # 音声データ処理
    "PyNaCl>=1.5.0"               # 音声暗号化
]
```

### 開発用依存関係
```toml
dev = [
    "pytest>=7.0.0",             # テストフレームワーク
    "pytest-asyncio>=0.21.0",    # 非同期テスト
    "black>=23.0.0",             # コードフォーマッター
    "flake8>=6.0.0"              # コード品質チェック
]
```

### 外部システム依存
- **FFmpeg**: 音声処理（システムレベル）
- **Style-Bert-VITS2**: TTS APIサーバー（オプション）

## 🚀 起動・実行

### セットアップ手順
1. **環境準備**
   ```bash
   # リポジトリクローン
   git clone <repository-url>
   cd yomiageBotEx
   
   # 依存関係インストール
   uv sync --no-install-project
   
   # 環境変数設定
   echo "DISCORD_TOKEN=your_token" > .env
   ```

2. **起動方法**
   ```bash
   # 推奨: スクリプト起動
   ./scripts/start.bat    # Windows
   ./scripts/start.sh     # Linux/macOS
   
   # 手動起動
   uv run --no-project python bot.py
   ```

### プロセス管理
- **重複実行防止**: `bot.lock`ファイルによる自動制御
- **単一プロセス強制**: 複数プロセス実行時の自動停止
- **セッション復元**: 異常終了時の状態復元機能

## 🔍 デバッグ・開発

### ログシステム
- **ログファイル**: `logs/yomiage.log`（現在）+ 圧縮バックアップ
- **ログレベル**: INFO（本番）/ DEBUG（開発）
- **ローテーション**: 10MB毎、最大5ファイル保持

### デバッグツール
- **`check_relay_status.py`**: 音声リレー状態確認
- **`test_real_audio.py`**: 音声録音機能テスト

### 開発環境
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

## ⚠️ 既知の制限・問題

### 技術的制限
1. **py-cord WaveSinkバグ**: PCMデータ取得不可（録音機能に影響）
2. **メモリ使用量**: 長時間実行時のメモリリーク対策必要
3. **TTS依存**: Style-Bert-VITS2サーバー依存

### 運用上の注意点
1. **管理者権限**: 音声リレー機能は管理者限定
2. **プロセス管理**: 必ず単一プロセス実行
3. **ファイルサイズ**: 録音ファイルの自動削除（1時間後）

## 🔮 今後の開発予定

### 機能拡張
- [ ] WebUI管理画面の追加
- [ ] 音声品質の更なる向上
- [ ] 録音機能の代替実装（WaveSinkバグ回避）
- [ ] パフォーマンス最適化

### 技術改善
- [ ] discord.py移行の検討
- [ ] マルチサーバー対応強化
- [ ] セキュリティ強化
- [ ] テストカバレッジ向上

---

## 📄 ドキュメント更新履歴

- **2025-09-06**: 初版作成（v0.2.0ベース）
- プロジェクト全体の技術仕様を包括的に文書化

**注意**: この技術仕様書は、実際の実装状況に基づいて作成されています。コード変更時は必ず本ドキュメントも更新してください。