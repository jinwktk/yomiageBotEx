# yomiageBotEx - Discord読み上げボット

Discordボイスチャンネルで読み上げ機能を提供するボット（Python版）

## 🚀 クイックスタート

### 1. 必要なもの
- Python 3.10以上（推奨: 3.13）
- [uv](https://docs.astral.sh/uv/) - Pythonパッケージマネージャー（推奨）または pip
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

# 依存関係のインストール（推奨: uv）
uv sync --no-install-project

# または、pipを使用する場合:
# pip install -r requirements.txt           # 開発ツール込み
# pip install -r requirements-minimal.txt   # 最小限のみ
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
| `/replay` | 最近の音声を録音してチャットに投稿（1-300秒） |
| `/recordings` | 最近の録音リストを表示 |
| `/start_record` | 手動録音を開始（WAV形式・リアルタイム録音を一時停止） |
| `/stop_record` | 手動録音を停止し、混合WAVとユーザー別ZIPを返信 |
| `/reading` | チャット読み上げのON/OFFを切り替え |
| `/dict_add` | 辞書に単語を追加 |
| `/dict_remove` | 辞書から単語を削除 |
| `/my_settings` | 現在の個人設定を表示 |
| `/set_reading` | 読み上げ設定を変更 |
| `/set_global_tts` | サーバー全体のTTS設定を変更（管理者限定） |

## 🔧 設定ファイル

`config.yaml`で以下の設定が可能：
- ボットの基本設定（管理者ユーザーID、自動参加設定等）
- TTS設定（APIサーバーURL、モデル/話者/スタイル設定）
- ロギング設定
- レート制限設定
- 辞書設定

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

### チャット読み上げ機能
- リアルタイムでチャットメッセージを音声で読み上げ
- URL、メンション、絵文字の自動変換
- 読み上げON/OFF切り替え（`/reading`コマンド）
- プレフィックス（!、/、.、?）で始まるメッセージは除外

### 録音・リプレイ機能
- 最大10分間の音声バッファリング
- `/replay`コマンドで過去の音声を再生
- 録音ファイルの自動管理（1時間後削除）
- リアルタイム音声受信（フォールバック機能付き）
- チェックポイント再開時に重複チャンクを自動除去し、リプレイ時の巻き戻りを防止
- `/start_record`・`/stop_record` で手動録音を制御（録音中はリアルタイム録音を一時停止し、停止時にミックス済みWAVとユーザー別ZIPを返却）

### 手動録音ワークフロー
1. ボイスチャンネルに参加し、ボットが同じチャンネルに接続していることを確認します。
2. `/start_record` を実行すると手動録音が開始され、リアルタイム録音が自動で一時停止します（必要に応じて正規化を無効化可能）。
3. `/stop_record` を実行すると録音を終了し、混合WAVファイルとユーザー別のWAVをまとめたZIP（25MB以内の場合）を返信します。同時に `recordings/manual/<GuildID>/` に保存されます。
4. 停止後はリアルタイム録音が再開され、`/replay` などの既存フローと共存できます。

### TTS機能（オプション）
- Style-Bert-VITS2との連携
- 音声キャッシュによる高速化
- フォールバック機能（ビープ音での代替再生）

## 🎵 Style-Bert-VITS2 TTS APIサーバーのセットアップ（オプション）

実際の音声合成を使用する場合は、Style-Bert-VITS2 APIサーバーが必要です。

### 1. Style-Bert-VITS2のインストール

```bash
# Style-Bert-VITS2をクローン
git clone https://github.com/litagin02/Style-Bert-VITS2.git
cd Style-Bert-VITS2

# 依存関係のインストール
pip install -r requirements.txt
```

### 2. 事前学習モデルのダウンロード

```bash
# 日本語モデルをダウンロード（約2GB）
python -m style_bert_vits2.nlp.bert_models
```

### 3. APIサーバーの起動

```bash
# APIサーバーを起動（デフォルトの127.0.0.1:8000で起動）
python server_fastapi.py
```

### 4. 動作確認

```bash
# APIサーバーが起動しているか確認
curl http://127.0.0.1:8000/status
```

成功すると、実際の音声合成での挨拶が再生されます。APIサーバーが動作していない場合は、自動的にフォールバック音声（ビープ音）が再生されます。

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

### ホットリロード
- `config.yaml` の `development.hot_reload.enabled` を `true` にすると、Cog ファイル（`cogs/*.py`）の更新をポーリングで検知して自動的に `reload_extension` が走ります。
- 間隔は `development.hot_reload.poll_interval`（秒）で調整できます。デフォルトは 1.0 秒です。
- 実行中に `/reload_cog` コマンドを使う従来の手動リロードとも併用できます。

## 🐛 トラブルシューティング

### スラッシュコマンドが表示されない
- Botを再起動後、Discordクライアントも再起動してください
- コマンドの同期には数分かかることがあります

### Invalid token エラー
- `.env`ファイルのトークンを確認してください
- トークンの前後に余分なスペースがないか確認してください

### Opus library エラー（Windows）
録音機能でOpusエラーが出る場合：
```
Could not find Opus library. Make sure it is installed.
```

**解決方法**：
1. Windowsの場合、Opusライブラリは自動的にフォールバックモードで動作します
2. 完全な音声受信機能が必要な場合は、以下をインストール：
   - [Opus公式サイト](https://opus-codec.org/downloads/)からWindows用DLLをダウンロード
   - システムのPATHに追加するか、ボットのディレクトリに配置

**注意**: Opusライブラリがなくても基本的な録音機能は動作しますが、音質が低下する可能性があります。

### `/replay` コマンドで生成したファイルが見つからない
- 2025-10-23 の修正で、保存先は必ずプロジェクトルート直下の `recordings/replay/<GuildID>/` に統一されました。
- サービスを別ディレクトリから起動している場合でも、上記ディレクトリを確認してください。
- パス解決が正しく機能しているかは `pytest tests/test_replay_file_storage.py` で回帰テストできます。
- 1回目の `/replay` 実行後に「データが見つからない」応答が続く場合、2025-10-23 修正以降では定期チェックポイントでチャンクが継続的に蓄積されるようになっています。`pytest tests/test_real_audio_recorder_buffers.py` で時間管理ロジックを確認できます。

## 📄 ライセンス

MIT License

## PST.exe（Process Stoper Tool）との競合問題

### 問題：
Palworld ServerのPST.exeが9:00AMに自動でDiscord botを終了させる場合があります。

### 解決策：
1. **保護モードで起動**（推奨）
   - `scripts/start.bat`を使用してbotを起動
   - 自動的にシグナル保護機能が有効になります

2. **環境変数で無効化**
   ```batch
   set ENABLE_PST=false
   ```

3. **PST.exe設定変更**
   - `pst\yomiage_protection.txt`を作成
   - 除外プロセスに`python.exe`、`YomiageBotEx`を追加

### ログで確認：
```
SIGINT received - possibly from PST.exe. Checking source...
Protected mode: Ignoring external termination signal for 5 seconds...
```
