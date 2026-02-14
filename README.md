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
| `/replay` | 最近の音声を録音してチャットに投稿（1-300秒、`debug_audio_stages=true` で生/正規化後/加工後を保存） |
| `/recordings` | 最近の録音リストを表示 |
| `/start_record` | 手動録音を開始（WAV形式・リアルタイム録音を一時停止） |
| `/stop_record` | 手動録音を停止し、混合WAVとユーザー別ZIPを返信 |
| `/reading` | チャット読み上げのON/OFFを切り替え（人がいないVCでは自動一時停止） |
| `/echo` | 指定したテキストをボイスチャットで読み上げ（メッセージは残さず、返信は「音声を流しました」固定／VCに参加者がいない場合はエラー応答） |
| `/replay_diag` | `/replay` 実行前に録音チャンクの有無を診断し、最後に記録された時刻を表示 |
| `/replay_probe` | 最新の録音チャンクを診断用WAVとして取得（録音状況の切り分け用） |
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
- 録音設定（`prefer_replay_buffer_manager` で ReplayBufferManager を優先利用するか制御可能）

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
- プレフィックス（!、/、.、?、`、;）で始まるメッセージは除外
- `/dict_add` `/dict_remove` で更新した辞書内容をボット再起動なしで即時適用
- Opusデコードエラー時のログにSSRC対応ユーザー・ギルド・チャンネル情報を含め、障害箇所を即座に特定可能
- VC自動再接続の際は既存接続のハンドシェイク完了を最大8秒待機し、進行中の接続を切らずに復帰
- 古いボイス接続参照が残っていても、ユーザー参加を検知すると自動で再参加して録音・挨拶処理を再開
- 直近で接続していたチャンネル情報を保持し、ユーザー検出に失敗しても最後のチャンネルへフォールバック再接続
- Discordの新方式暗号化（aead_xchacha20_poly1305）で復号に失敗したフレームは自動的にスキップし、録音スレッドが落ちないよう保護
- 大容量ログのローテーション時は圧縮処理をバックグラウンド化し、イベントループをブロックしない
- 読み上げメッセージはギルドごとのキューに積まれ、VC再接続後に順番に処理されるためスキップされない
- VCが無人になった時点で自動的に読み上げを一時停止し、参加者が戻れば手動設定を変えずに即時再開
- ボイスチャンネルにBot以外の参加者がいない場合は読み上げを実行せず、無人時の再生や録音を防止

### 録音・リプレイ機能
- 最大10分間の音声バッファリング
- `/replay`コマンドで過去の音声を再生
- 録音ファイルの自動管理（1時間後削除）
- リアルタイム音声受信（フォールバック機能付き）
- チェックポイント再開時に重複チャンクを自動除去し、リプレイ時の巻き戻りを防止
- 読み上げ時の自動再接続は、参加者がいない場合に既存接続を温存するフェイルセーフ付き
- `/start_record`・`/stop_record` で手動録音を制御（録音中はリアルタイム録音を一時停止し、停止時にミックス済みWAVとユーザー別ZIPを返却）
- 録音の定期チェックポイントはイベントループをブロックしないよう非同期化し、VC心拍ブロックを防止
- `/replay` は RecordingCallbackManager からの ReplayBufferManager を常に優先し、取得できた場合は旧バッファ経路へフォールバックしない仕組み
- RealTimeAudioRecorder で取得したチャンクを RecordingCallbackManager に直接転送し、リレー機能なしでも `/replay` 新経路の取得精度を維持
- ReplayBufferManager のユーザー音声結合は WAV ヘッダ長を固定値で扱わず `wave` 解析でPCM抽出する方式に修正し、可変ヘッダ混在時の機械音化を防止
- `/replay`（ユーザー指定）の結合時に16bit PCMピークを抑制するクリップ保護を追加
- RealTimeAudioRecorder の `finished_callback` は接続中VoiceClientの `recording` 状態に同期してフラグ更新するよう修正し、チェックポイント後に録音ループが止まる競合を防止
- ReplayBufferManager のユーザー結合時にチャンク時刻ベースで重複区間を除去し、同一区間の二重連結による機械音/尺伸びを抑制
- `/replay` の出力は要求秒数を上限に末尾側へトリムするようにし、30秒指定で過剰な尺になるケースを防止
- `/replay` 新経路の最終出力は既存の音声処理パイプライン（`_process_audio_buffer`）へ統一し、`adeclip + loudnorm` を適用して歪みを緩和
- WaveSink が空データ（`sink.audio_data keys: []`）を連続で返した場合、録音セッションを自動で再起動して復旧を試みる保護を追加
- 自動復旧時に `Not currently recording audio` が返るレース条件でも、停止済みとして扱って再開処理を継続するよう改善
- 自動復旧の再開処理で `Already recording.` 競合が出た場合は、1回だけ停止→再開を再試行して復旧成功率を上げるよう改善
- `/replay` の `debug_audio_stages=true` で工程別音声（生データ/正規化後/加工後）を `recordings/replay/<GuildID>/debug/` に保存し、ZIPも生成
- `aead_xchacha20_poly1305_rtpsize` 利用時の受信互換性向上として、Voice受信パイプラインに互換パッチ（RTP判定と復号互換）を適用
- `/replay_diag` コマンドで連続バッファと RecordingCallbackManager の双方にチャンクが存在するかを即時確認可能
- `/replay_probe` コマンドで最新チャンクをWAVとして取得し、録音が実際に取れているか素早く確認可能

### 手動録音ワークフロー
1. ボイスチャンネルに参加し、ボットが同じチャンネルに接続していることを確認します。
2. `/start_record` を実行すると手動録音が開始され、リアルタイム録音が自動で一時停止します（必要に応じて正規化を無効化可能）。
3. `/stop_record` を実行すると録音を終了し、混合WAVファイルとユーザー別のWAVをまとめたZIP（25MB以内の場合）を返信します。同時に `recordings/manual/<GuildID>/` に保存されます。
4. 停止後はリアルタイム録音が再開され、`/replay` などの既存フローと共存できます。

### TTS機能（オプション）
- Style-Bert-VITS2との連携
- 音声キャッシュによる高速化
- フォールバック機能（ビープ音での代替再生）
- ユーザーの入退室時にカスタム挨拶を再生（py-cord PR2651 対応済み）
- 辞書登録済みの名前や単語を挨拶メッセージにも即時適用
- TTS APIの文字数上限（デフォルト100文字）を超えないよう安全に短縮し、422エラーを回避

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

### 2026-02-14 メンテナンスメモ
- 読み上げ機能を中心に運用する方針に合わせ、機能整理前の状態を一度コミットする運用に変更。
- 今後の削除対象は `relay` 系と `admin` 系に限定し、`recording`・`tts`・`user_settings`・`dictionary` は維持する。

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
- `logs/yomiage.log` に `WaveSink callback returned no audio data` が連続する場合は録音入力が詰まっている可能性があります。最新版では一定回数連続時に録音セッションを自動再起動します。
- Discord側で `aead_xchacha20_poly1305_rtpsize` が選択される環境では、古い py-cord 実装との差分で受信品質が落ちる場合があります。最新版では受信互換パッチを適用してパケット判定と復号処理を補正しています。

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
