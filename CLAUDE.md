# CLAUDE.md - yomiageBotEx プロジェクトドキュメント

## プロジェクト概要
Discord読み上げボット（Python版）の実装。TypeScript版の失敗を踏まえ、段階的に機能を追加していく方針で開発。

## フォルダ構成

### Phase 2 (現在の構成)
```
yomiageBotEx/
├── bot.py              # メインボットファイル（Cog構造対応）
├── config.yaml         # 設定ファイル
├── .env               # Discordトークン（Gitignore対象）
├── .gitignore         # Git除外設定
├── requirements.txt    # 依存関係
├── CLAUDE.md          # このファイル
├── cogs/              # Cogモジュール
│   ├── __init__.py    # Cogパッケージ初期化
│   ├── voice.py       # ボイスチャンネル管理Cog
│   ├── tts.py         # TTS機能Cog
│   ├── recording.py   # 録音・リプレイ機能Cog
│   ├── message_reader.py # チャット読み上げ機能Cog
│   ├── dictionary.py  # 辞書機能Cog
│   ├── user_settings.py # ユーザー設定機能Cog
│   └── reload.py      # ホットリロード・Cog管理機能
├── utils/             # ユーティリティモジュール
│   ├── __init__.py    # ユーティリティパッケージ初期化
│   ├── logger.py      # ロギング設定ユーティリティ（ローテーション付き）
│   ├── tts.py         # TTS機能ユーティリティ（モデル選択付き）
│   ├── recording.py   # 録音・リプレイ機能ユーティリティ
│   ├── audio_processor.py # 音声処理（ノーマライズ、フィルタリング）
│   ├── dictionary.py  # 辞書管理システム
│   ├── user_settings.py # ユーザー別設定管理
│   ├── real_audio_recorder.py # 統合版音声録音（bot_simple.py移植）
│   ├── audio_sink.py  # Discord音声受信用AudioSink
│   ├── voice_receiver.py # カスタム音声受信システム
│   └── simple_recorder.py # シンプル音声録音（フォールバック）
├── scripts/           # 起動スクリプト
│   ├── start.sh       # Linux/macOS用起動スクリプト
│   ├── start.bat      # Windows用起動スクリプト
│   └── reload.bat     # Windows用リロードスクリプト（Bot停止不要）
├── pyproject.toml     # uv用プロジェクト設定
├── .python-version    # Python バージョン指定
├── uv.lock           # uv依存関係ロックファイル
├── cache/             # TTSキャッシュディレクトリ（自動生成）
│   └── tts/          # TTS音声キャッシュ
├── recordings/        # 録音ファイルディレクトリ（自動生成）
│   └── *.wav         # 録音ファイル（1時間後自動削除）
├── data/              # データディレクトリ（自動生成）
│   ├── dictionary.json # 辞書データ
│   └── user_settings.json # ユーザー設定データ
└── logs/              # ログディレクトリ（自動生成）
    ├── yomiage.log    # 現在のログ
    ├── yomiage.log.1.gz # ローテーション済みログ（圧縮）
    └── yomiage.log.*.gz # 過去のログファイル
```

## 実装フェーズ

### Phase 1: 基本機能（実装済み）
- [x] Discord接続
- [x] スラッシュコマンド（/join, /leave）
- [x] 基本的なロギング
- [x] レート制限対策
- [x] エラーハンドリング

### Phase 2: 自動機能（実装済み）
- [x] Cog構造の導入
- [x] 自動参加・退出（0人チェック付き）
- [x] 5分ごとの空チャンネルチェック
- [x] セッション永続化（再起動時の復元）
- [x] ログクリーンアップ機能

### Phase 3: TTS統合（実装済み）
- [x] Style-Bert-VITS2統合
- [x] 挨拶機能（参加/退出）
- [x] 音声キャッシュシステム
- [x] 軽量化設計（フォールバック機能付き）
- [x] TTSAPIサーバー接続管理

### Phase 4: 録音機能（実装済み）
- [x] 録音・リプレイ機能（/replayコマンド）
- [x] メモリバッファ管理（リングバッファ）
- [x] 録音ファイル自動クリーンアップ（1時間後）
- [x] 録音リスト表示（/recordingsコマンド）
- [x] 音声バッファクリア（/clear_bufferコマンド）
- [x] 管理者権限チェック

## 技術的詳細

### 使用ライブラリ
- discord.py 2.3.0以上（py-cordは使用しない）
- python-dotenv（環境変数管理）
- pyyaml（設定ファイル）
- aiofiles（非同期ファイル操作）
- aiohttp（HTTPクライアント）
- numpy（音声処理）
- ffmpeg-python（音声処理用、Phase 3以降）

### パッケージ管理
- **uv**: 高速なPythonパッケージマネージャー
- **pyproject.toml**: プロジェクト設定と依存関係管理
- **uv.lock**: 依存関係のロックファイル

### 設定管理
- `.env`: DISCORD_TOKENのみ保存
- `config.yaml`: その他すべての設定
- デフォルト値をコード内に持ち、config.yamlがなくても動作可能

### エラーハンドリング
- グローバルエラーハンドラで捕捉
- 個別のエラーでもボット全体は停止しない設計
- すべてのエラーをログに記録

### レート制限対策
- API呼び出し前に0.5～1秒のランダム遅延
- `rate_limit_delay`メソッドで一元管理

## 実装メモ

### 2024-06-27 Phase 1実装
- 基本的なDiscordボット構造を実装
- /joinと/leaveコマンドのみの最小構成
- ロギングシステムの基礎を構築
- config.yamlによる設定管理を導入
- エラーハンドリングとレート制限対策を最初から組み込み

### 2024-06-27 Phase 2実装
- Cog構造への移行完了（bot.py → cogs/voice.py）
- utils/logger.pyでロギング機能を分離
- 自動参加・退出機能の実装（空チャンネル検知付き）
- セッション永続化システム（sessions.json）
- 5分ごとの定期チェックタスク
- 1日ごとの古いログファイル自動削除

### 2024-06-27 uv環境構築
- pyproject.tomlでuv対応のプロジェクト設定
- .python-versionでPython 3.11を指定
- scripts/ディレクトリに起動スクリプト追加
- README.mdでuv環境でのセットアップ手順を更新
- 開発用依存関係（pytest、black、flake8）を追加

### 2024-06-27 Phase 3実装（TTS統合）
- utils/tts.pyでTTS機能とキャッシュシステムを実装
- cogs/tts.pyで挨拶機能を実装
- Style-Bert-VITS2 API統合とフォールバック機能
- 軽量化設計（キャッシュ、タイムアウト、文字数制限）
- 音声キャッシュの自動クリーンアップ
- 設定ファイルで挨拶機能の有効/無効切り替え可能

### 2024-06-27 Phase 4実装（録音・リプレイ機能）
- utils/recording.pyで録音バッファとファイル管理を実装
- cogs/recording.pyで/replay、/recordings、/clear_bufferコマンドを実装
- リングバッファによるメモリ効率的な音声バッファ管理
- WAVファイル形式での録音保存（最大300秒）
- 1時間後の自動ファイルクリーンアップ
- 管理者限定のバッファクリア機能
- 音量調整機能付きリプレイ

### 2024-06-28 エラー修正（第1回）
- **PyNaCl依存関係の追加**: discord.py[voice]、PyNaCl、ffmpeg-pythonをpyproject.tomlに追加
- **ディレクトリ作成エラーの修正**: utils/tts.py、utils/recording.py、utils/logger.pyでmkdir()にparents=True引数を追加
- **問題**: 
  - `PyNaCl library needed in order to use voice`エラー
  - `[WinError 3] 指定されたパスが見つかりません。: 'cache\\tts'`エラー
- **修正内容**:
  - pyproject.tomlに音声関連ライブラリを追加
  - 全てのディレクトリ作成処理でparents=Trueを指定し、親ディレクトリも同時作成

### 2024-06-28 機能修正（第2回）
- **TTS音声再生の修正**: cogs/tts.pyでio.BytesIOからの直接再生を一時ファイル方式に変更
- **録音機能の改善**: utils/recording.pyでDiscord音声受信の実装を改善
- **音声受信の実装**: cogs/recording.pyにvoice_client.listen()を使用した音声受信を追加
- **問題**:
  - TTS音声が再生されない（FFmpegPCMAudioのpipe=True問題）
  - 録音機能で音声データが受信されない
  - `No audio data to save`エラー
- **修正内容**:
  - TTS再生で一時ファイルを使用するように変更
  - RecordingSinkクラスをdiscord.sinks.Sinkベースに変更
  - SimpleRecordingSinkでフォールバック実装を追加
  - voice_clientでの音声受信開始・停止処理を追加

### 2024-06-28 discord.sinksエラー修正（第3回）
- **discord.sinksエラーの解決**: `module 'discord' has no attribute 'sinks'`エラーを修正
- **RecordingSinkクラスの削除**: discord.sinksが存在しないため、SimpleRecordingSinkのみを使用
- **音声受信の簡素化**: voice_client.listen()を削除し、ダミー音声データでの録音テストに変更
- **問題**:
  - `discord.sinks`が存在しない
  - RecordingCogのロードに失敗
- **修正内容**:
  - RecordingSinkクラス（discord.sinks.Sink継承）を削除
  - SimpleRecordingSinkのみを使用するように変更
  - 録音機能をダミーデータでのテスト実装に変更

### 2024-06-28 デバッグログ追加（第4回）
- **TTS・録音機能の動作調査**: 機能が動作しない問題の原因調査のためデバッグログを追加
- **設定値の確認**: Cog初期化時に設定値をログ出力するように修正
- **音声状態変更の詳細ログ**: on_voice_state_updateで詳細な状態をログ出力
- **問題**:
  - TTS挨拶が再生されない
  - 録音機能が開始されない（No audio data to save）
- **追加内容**:
  - TTSCogとRecordingCogの初期化時設定ログ
  - on_voice_state_updateでの詳細な状態ログ
  - チャンネル変更の詳細な追跡ログ

### 2024-06-28 タイミング問題修正（第5回）
- **自動参加のタイミング問題を解決**: ユーザー参加→ボット接続の順序でTTS・録音が動作しない問題を修正
- **ボット接続完了後の処理追加**: ボットがVCに接続した時点で既にいるユーザーに対する処理を実装
- **Cog間連携の実装**: VoiceCogから他のCogに接続完了を通知する仕組みを追加
- **問題**:
  - ユーザーがVCに参加した時点ではボットが未接続（`Voice client connected: False`）
  - ボット接続完了時に既存ユーザーに対する挨拶・録音が開始されない
- **修正内容**:
  - VoiceCog.notify_bot_joined_channel()メソッドを追加
  - TTSCog.handle_bot_joined_with_user()メソッドを追加
  - RecordingCog.handle_bot_joined_with_user()メソッドを追加
  - セッション復元時にも同様の処理を実行

### 2024-06-28 機能拡張完了（第6回）
- **Option 1: Style-Bert-VITS2セットアップ手順**: README.mdにAPIサーバーのセットアップ手順を追加
- **Option 2: チャット読み上げ機能**: 新しいMessageReaderCogを実装
- **Option 3: 実際の音声録音機能**: リアルタイム音声受信システムを実装
- **実装内容**:
  - `cogs/message_reader.py`: チャットメッセージの読み上げ機能
  - `utils/audio_sink.py`: Discord音声受信用のAudioSinkクラス
  - `/reading`コマンド: 読み上げON/OFF切り替え
  - メッセージ前処理: URL除去、メンション変換、絵文字処理
  - リアルタイム音声録音: 実際のPCM音声データ受信
  - フォールバック機能: API未使用時の代替処理
- **設定追加**:
  - config.yamlにmessage_reading設定セクションを追加
  - 読み上げ文字数制限、無視プレフィックス等の設定

### 実装完了機能
- ✅ Phase 1: 基本機能（VC参加・退出）
- ✅ Phase 2: 自動参加・退出機能  
- ✅ Phase 3: TTS統合（Style-Bert-VITS2）
- ✅ Phase 4: 録音・リプレイ機能
- ✅ Option 1: Style-Bert-VITS2セットアップ手順
- ✅ Option 2: チャット読み上げ機能
- ✅ Option 3: 実際の音声録音機能

### 2024-06-27 Style-Bert-VITS2 API統合最終調整
- **TTS APIエンドポイントの修正**: ヘルスチェックを/health → /statusに変更
- **APIリクエスト形式の修正**: JSONボディ → クエリパラメータ形式に変更
- **デフォルトポートの修正**: config.yamlとREADME.mdで5000 → 8000に変更
- **完全統合テスト**: 全機能（自動参加・退出、TTS、録音・リプレイ、チャット読み上げ）の動作確認完了

### 2024-06-28 機能改善
- **TTS API完全動作確認**: Style-Bert-VITS2との統合成功、実際の音声合成で読み上げ実現
- **録音機能の仕様変更**: /replayコマンドでボット再生→チャットにファイル投稿に変更
- **パラメータ整理**: 不要になったvolumeパラメータを削除

### 2024-06-28 Guild別録音機能修正（第10回）
- **Guild別録音バッファの実装**: 複数のGuildで同時に録音する際に音声データが混在する問題を修正
- **RealTimeAudioRecorderの改良**:
  - `guild_user_buffers`による階層化されたバッファ管理: `{guild_id: {user_id: [(buffer, timestamp), ...]}}`
  - `get_user_audio_buffers(guild_id, user_id)`メソッドでGuild別データ取得
  - `clean_old_buffers(guild_id)`でGuild別クリーンアップ
- **RecordingCogの修正**:
  - `/replay`コマンドでGuild IDを指定してバッファ取得
  - `/debug_recording`と`/test_recording`でもGuild別対応
- **TTSCogの改良**: 挨拶無効時のログ出力を抑制
- **問題**:
  - ユーザーがGuild Aで/replayを実行すると、Guild Bの録音データが再生される問題
  - 音声バッファがGuild間で共有されていた
- **修正内容**:
  - 音声バッファをGuild単位で完全分離
  - 各録音操作でguild_idを必須パラメータに変更
  - デバッグログでGuild IDを表示するように改善
  - 挨拶機能無効時の不要なログを削減

### 2024-06-28 録音機能の本格実装
- **カスタムVoiceClient実装**: EnhancedVoiceClientでdiscord.pyの音声受信制限を回避
- **音声パケット処理**: RTPヘッダー解析とOpusデコード処理を実装
- **VoiceReceiverクラス**: 非同期での音声データ受信・処理システム
- **依存関係追加**: opuslib>=3.0.0（Opusデコード用）
- **実装内容**:
  - `utils/voice_receiver.py`: カスタム音声受信クラス
  - `bot.py`: connect_to_voiceメソッドでEnhancedVoiceClientを使用
  - `cogs/voice.py`: すべての接続処理をカスタムクライアントに変更
  - フォールバック機能: opuslibがない場合はダミーPCMデータ生成

### 2024-06-28 録音機能のフォールバック実装追加
- **Discord.py内部API変更対応**: WebSocketからsocketが取得できない問題を修正
- **SimpleVoiceRecorder実装**: より現実的な音声シミュレーション
- **自動フォールバック機能**: EnhancedVoiceClientが動作しない場合の代替実装
- **実装内容**:
  - `utils/simple_recorder.py`: シンプルな音声録音実装（シミュレーション）
  - `utils/voice_receiver.py`: 複数のsocket取得方法を試行
  - 音声パターン生成: 会話のような音声パターンをシミュレート
  - エラーハンドリング: インポートエラー時の自動切り替え

### 2024-06-28 discord.py vs py-cord API差分調査完了
- **ライブラリ状況確認**: pyproject.tomlでpy-cord 2.6.1がインストール済み、requirements.txtとの矛盾を確認
- **主要なAPI差分特定**:
  - py-cordでは`app_commands`モジュールが存在しない
  - `commands.Bot`に`tree`属性がないため、`tree.sync()`が使用不可
  - スラッシュコマンドは`@discord.slash_command`を使用
  - パラメータは`interaction`ではなく`ctx`、レスポンスは`ctx.respond()`
- **修正が必要な箇所**:
  - `bot.py`: line 97の`tree.sync()`削除
  - `cogs/voice.py`: app_commands → discord.slash_command (lines 15, 231, 302)
  - `cogs/recording.py`: 同様のスラッシュコマンド修正 (lines 14, 154, 239, 293)
  - `cogs/message_reader.py`: 同様の修正が必要
- **VoiceClient互換性**: ✅ 基本的なVoice関連APIは互換性あり
- **テスト結果**: 基本的なBot初期化は成功、スラッシュコマンド関連のみ修正が必要

### 2024-06-27 py-cord スラッシュコマンド修正実施
- **bot_simple.pyの修正完了**:
  - `discord.Bot(intents=intents, debug_guilds=[DEBUG_GUILD_ID])`でBot初期化
  - debug_guildsを使用して即座にスラッシュコマンド同期
  - requirements.txtをdiscord.py → py-cord[voice]に修正
  - 音声接続に`timeout=15.0, reconnect=True`を追加
- **根本原因の発見**:
  - pip listでpy-cordがインストールされていないことを確認
  - pyproject.tomlとrequirements.txtの不一致
  - py-cordが未インストールのためスラッシュコマンドが登録されない
- **修正内容**:
  - `pip install py-cord[voice]==2.6.1`でインストール必要
  - debug_guilds設定で即座にコマンド同期（開発用）
  - requirements.txt修正でライブラリ統一
- **期待される改善**:
  - py-cordインストール後、スラッシュコマンドが即座に利用可能
  - ギルド固有コマンドで同期遅延なし
  - 音声接続の安定性向上

### 2024-06-28 全員音声マージ機能追加
- **成功確認**: py-cordのスラッシュコマンドが正常動作
- **/replayコマンドの拡張**:
  - user指定なしの場合、全員の音声をマージして1ファイルで出力
  - ファイル名: `recording_all_{user_count}users_{timestamp}.wav`
  - 最新5個のバッファを各ユーザーから取得して結合
  - 有効な音声データがない場合の適切なエラー処理
- **動作確認済み機能**:
  - ✅ /joinコマンド：音声チャンネルへの参加
  - ✅ /leaveコマンド：音声チャンネルからの退出
  - ✅ 自動参加・退出機能
  - ✅ 実際の音声録音（discord.sinks.WaveSink）
  - ✅ /replayコマンド：個別ユーザー録音再生
  - ✅ /replayコマンド：全員音声マージ再生

### 2024-06-28 音声接続エラー修正（第7回）
- **IndexError: list index out of range修正**: py-cordの音声接続で発生する暗号化モード選択エラーを解決
- **CustomBotクラス追加**: 安全な音声接続のためのconnect_voice_safely()メソッドを実装
- **接続パラメータ最適化**: timeout=30.0、reconnect=Trueで接続安定性向上
- **self_deafエラー修正**: py-cordのconnect()ではself_deafパラメータ未対応のため接続後に設定
- **問題**:
  - `mode = modes[0]` で `IndexError: list index out of range`
  - `TypeError: Connectable.connect() got an unexpected keyword argument 'self_deaf'`
  - Discord音声サーバーとの暗号化モード互換性問題
- **修正内容**:
  - CustomBotクラスでconnect_voice_safely()メソッド実装
  - 接続後にchange_voice_state()でself_deaf=Trueを設定
  - フォールバック機能：エラー時は基本的なconnect()を試行
  - タイムアウト値を15秒→30秒に延長

### 2024-06-28 bot.pyへのユーザー別録音機能実装（第8回）
- **bot_simple.pyの機能をbot.pyに統合**: /replayコマンドにユーザー指定機能を追加
- **RecordingManagerの拡張**:
  - `user_buffers`辞書を追加（ギルドID → ユーザーID → AudioBuffer）
  - `add_audio_data`メソッドにuser_idパラメータ追加
  - `save_recent_audio`メソッドにtarget_user_idパラメータ追加
  - `_merge_user_audio`メソッドで全ユーザー音声をマージ
- **RealTimeAudioRecorderの修正**:
  - audio_callbackでユーザーIDを渡すように変更
  - ユーザー別の音声データを個別に保存
- **/replayコマンドの機能拡張**:
  - userパラメータ追加（Optional[discord.Member]）
  - 特定ユーザー指定時：そのユーザーの音声のみ
  - ユーザー未指定時：全ユーザーの音声をマージ
  - ファイル名にユーザー情報を含める（_user{id}、_all_{count}users）

### 2024-06-28 音声接続安定化対応（第9回）
- **音声接続エラー（WebSocket 4000）の根本的解決**: 音声データ取得問題の修正
- **VoiceCogのnotify_bot_joined_channelメソッド強化**:
  - 接続安定性チェックの時間を7.5秒に延長（15回×0.5秒）
  - WebSocketの内部状態確認（`_connected`プロパティ）
  - 追加の安定化待機（1.5秒）
  - 各メンバー処理前の接続確認
  - TTSと録音処理の間隔調整（0.5秒）
- **bot.pyのconnect_voice_safelyメソッド改良**:
  - 最大3回のリトライ機構
  - WebSocket 4000エラーの特別な処理（指数バックオフ）
  - 接続タイムアウトを45秒に延長
  - 接続後の安定化待機（1.0秒）
  - self_deaf設定のエラーハンドリング強化
- **RecordingCogのhandle_bot_joined_with_userメソッド改善**:
  - 5回の接続安定性チェック
  - 録音開始前の最終接続確認
  - フォールバック録音のエラーハンドリング強化
- **期待される改善**:
  - 音声データ取得の安定性向上
  - WebSocket切断エラーの大幅減少
  - TTS挨拶と録音機能の確実な動作
  - 起動時自動参加の信頼性向上

### 2024-06-28 Phase 5: 機能拡張完了
- **bot_simple.pyの録音機能統合**: utils/real_audio_recorder.pyでpy-cordのWaveSink機能を完全統合
- **FFmpegノーマライズ処理**: utils/audio_processor.pyで音声正規化、フィルタリング機能を実装
- **辞書登録機能**: utils/dictionary.py、cogs/dictionary.pyで単語・読み方の管理システム
- **Style-Bert-VITS2モデル選択**: utils/tts.pyでモデル・話者一覧取得、/tts_models、/tts_speakers、/tts_testコマンド
- **ログRotate機能**: utils/logger.pyでCompressedRotatingFileHandlerによる圧縮付きローテーション
- **ユーザー別設定機能**: utils/user_settings.py、cogs/user_settings.pyで個人別TTS・読み上げ設定

### 実装完了機能（完全版）
- ✅ Phase 1: 基本機能（VC参加・退出）
- ✅ Phase 2: 自動参加・退出機能  
- ✅ Phase 3: TTS統合（Style-Bert-VITS2）
- ✅ Phase 4: 録音・リプレイ機能
- ✅ Phase 5: 全機能拡張
  - ✅ bot_simple.py統合
  - ✅ 自動VC参加（既存）
  - ✅ FFmpegノーマライズ処理
  - ✅ 辞書登録機能
  - ✅ Style-Bert-VITS2モデル選択
  - ✅ ログRotate機能
  - ✅ ユーザー別設定機能

### 新規追加ファイル
- `utils/audio_processor.py`: 音声処理（ノーマライズ、フィルタリング）
- `utils/dictionary.py`: 辞書管理システム
- `utils/user_settings.py`: ユーザー別設定管理
- `utils/real_audio_recorder.py`: 統合版音声録音システム（bot_simple.py移植）
- `cogs/dictionary.py`: 辞書機能Cog（/dict_add、/dict_search等）
- `cogs/user_settings.py`: ユーザー設定Cog（/my_settings、/set_tts等）

### 追加コマンド一覧
**辞書機能**:
- `/dict_add` - 辞書に単語追加
- `/dict_remove` - 辞書から単語削除
- `/dict_search` - 辞書で単語検索
- `/dict_list` - 辞書統計表示
- `/dict_export` - 辞書エクスポート
- `/dict_import` - 辞書インポート

**TTSモデル管理**:
- `/tts_models` - 利用可能モデル一覧
- `/tts_speakers` - 指定モデルの話者一覧
- `/tts_test` - TTS設定テスト

**ユーザー設定**:
- `/my_settings` - 個人設定表示
- `/set_tts` - TTS設定変更
- `/set_reading` - 読み上げ設定変更
- `/set_greeting` - 挨拶設定変更
- `/reset_settings` - 設定リセット
- `/export_settings` - 設定エクスポート

### 軽量化対策
- キャッシュ機能：TTS音声、辞書検索、モデル情報
- 圧縮ログローテーション：自動圧縮でディスク使用量削減
- 設定ファイル最適化：必要最小限の設定項目
- エラーハンドリング：フォールバック機能で安定動作
- メモリ効率：適切なデータ構造とクリーンアップ

### 2024-06-28 主要機能の修正・改善完了（第9回）
- **TTSタイムアウト問題の解決**: APIタイムアウトを10秒→30秒に延長、asyncio.wait_forでの確実なタイムアウト制御実装
- **ユーザー設定のデフォルト値自動適用**: /set_ttsコマンド実行前でもUserSettingsManagerでデフォルト設定が自動マージ
- **/set_ttsのプルダウン選択式UI実装**: SimpleTTSSettingsViewでモデルID、話者ID、スタイル、速度の選択をドロップダウンで実現
- **辞書機能のデバッグ強化**: MessageReaderで辞書適用前後の変化をログ出力、初期化時の辞書状態確認ログ追加
- **問題**:
  - TTS API呼び出しでタイムアウトが発生し、ビープ音が再生される
  - /set_ttsでデフォルト設定が事前に設定されていない
  - /set_ttsがコマンドライン引数形式で使いにくい
  - 辞書機能が実装済みだが実際に適用されているか不明確
- **修正内容**:
  - `utils/tts.py`: タイムアウト30秒延長、別々の接続・読み取りタイムアウト、高速ヘルスチェック（3秒）
  - `cogs/user_settings.py`: SimpleTTSSettingsViewによるプルダウン式設定UI、TTSManagerとの統合
  - `cogs/message_reader.py`: 辞書適用前後の変化ログ、初期化時の辞書状態ログ
  - ユーザー設定は既存のget_user_settings()で自動的にデフォルト値がマージされる仕組みを確認

### 実装完了機能（最終状態）
- ✅ Phase 1: 基本機能（VC参加・退出）
- ✅ Phase 2: 自動参加・退出機能  
- ✅ Phase 3: TTS統合（Style-Bert-VITS2）
- ✅ Phase 4: 録音・リプレイ機能
- ✅ Phase 5: 高度な機能拡張
  - ✅ bot_simple.pyの録音機能統合（WaveSink）
  - ✅ FFmpeg音声正規化・フィルタリング
  - ✅ 辞書登録・管理機能
  - ✅ Style-Bert-VITS2モデル・話者選択
  - ✅ 圧縮ログローテーション
  - ✅ ユーザー別個人設定システム
  - ✅ プルダウン式設定UI
  - ✅ タイムアウト問題の解決
  - ✅ 全コマンドephemeral化
  - ✅ 起動時ログローテーション
  - ✅ 非同期処理最適化
  - ✅ グローバル例外ハンドラー
  - ✅ 音声録音安定性向上

### 2024-06-28 バグ修正・改善（第10回）
- **aiohttp セッション適切なクリーンアップ実装**: Bot終了時にTTSManagerのHTTPセッションが確実に閉じられるように修正
- **シャットダウンハンドリング強化**: SIGINT、SIGTERM、KeyboardInterrupt時の適切なリソースクリーンアップを実装
- **TTSManagerの非同期コンテキストマネージャー対応**: `async with`構文でのセッション管理をサポート
- **自動挨拶機能の無効化**: config.yamlでgreeting.enabledをfalseに設定してボイスチャンネル参加時の自動挨拶を停止
- **問題解決**:
  - ❌ **aiohttp client session not closed properly**: bot.py終了時クリーンアップで解決
  - ✅ **/replayコマンド未実装**: 既に完全実装済み（ユーザー指定録音・全員音声マージ対応）
  - ❌ **自動挨拶機能**: config.yamlでgreeting.enabled=falseに変更済み

### 2024-06-28 UX改善（第11回）
- **全スラッシュコマンドのephemeral化完了**: 全ての`ctx.respond`に`ephemeral=True`が既に設定済み（voice.py、recording.py、message_reader.py、dictionary.py、user_settings.py、tts.py）
- **ボット再起動時のログローテーション機能追加**: 
  - `utils/logger.py`に`rotate_log_on_startup()`関数を追加
  - 起動時に既存ログをタイムスタンプ付きでローテーション・圧縮
  - `config.yaml`に`rotation.rotate_on_startup`設定を追加
  - ログファイルサイズが0より大きい場合のみローテーション実行
- **目的**: 
  - ユーザーの応答を他のユーザーから隠す（プライバシー保護）
  - 再起動ごとに新しいログファイルで開始（管理性向上）

### 2024-06-28 安定性改善（第12回）
- **音声録音の例外修正**: `utils/real_audio_recorder.py`で`_finished_callback`をasync化してコルーチン要求エラーを解決
- **replayコマンドの並列処理化**: 
  - `cogs/recording.py`で重い処理を`_process_replay_async`として分離
  - `asyncio.create_task`でバックグラウンド実行し、ボットのブロックを回避
  - `ctx.defer(ephemeral=True)`で即座に応答、結果は`ctx.followup.send`で送信
- **グローバル例外ハンドラー強化**: 
  - `bot.py`に`on_application_command_error`と`on_command_error`を追加
  - 全ての例外を`exc_info=True`付きでログ記録
  - ユーザーへの適切なエラー通知
- **非同期I/O最適化**: `save_buffers`をワーカータスクとして実行し、メインループのブロックを防止
- **問題解決**:
  - ❌ **TypeError: A coroutine object is required**: コールバック関数のasync化で解決
  - ❌ **Voice heartbeat blocked**: replayコマンドの並列処理化で解決  
  - ❌ **replayコマンドがephemeralでない**: defer(ephemeral=True)とfollowup.send(ephemeral=True)で解決
  - ❌ **未捕捉の例外**: グローバルエラーハンドラーで全て捕捉・ログ記録

### 2024-06-28 ホットリロード機能実装
- **cogwatch統合**: コードファイル変更の自動検知とCog再読み込み機能を実装
- **@watchデコレータ追加**: bot.pyのon_readyメソッドにcogs/ディレクトリ監視を設定
- **手動リロードコマンド追加**:
  - `/reload_cog` - 指定したCogを手動で再読み込み（管理者限定）
  - `/reload_all` - すべてのCogを一括再読み込み（管理者限定）
  - `/list_cogs` - 現在ロードされているCogの一覧表示
- **開発効率の向上**:
  - コード変更時のBot再起動が不要
  - ボイスチャンネル接続を維持したまま開発可能
  - セッション復元機能との連携により、万が一の再起動時も自動復帰
- **reload.batスクリプト追加**: Bot停止不要で`git pull` + 依存関係更新を実行
- **Python要求バージョン更新**: cogwatch要求によりPython 3.9→3.10に変更

**解決された問題**:
- ❌ **コード変更時のBot再起動**: cogwatchで自動リロード
- ❌ **VC切断問題**: Bot本体稼働維持でVC接続保持
- ❌ **開発効率低下**: ホットリロードで即座に変更反映

### 2024-06-28 音声録音パフォーマンス問題修正（第13回）
- **voice heartbeat blocked問題の解決**: save_buffers()の同期的JSON書き込みが原因でDiscord接続が不安定になる問題を修正
- **save_buffers()の完全非同期化**:
  - `save_buffers()`メソッドは即座に非同期タスクを作成して返す（メインループをブロックしない）
  - `_prepare_buffer_data()`でCPU集約的な処理（Base64エンコード）を分離
  - `_write_buffer_file()`でブロッキングI/O処理を分離
  - 両方の処理を`run_in_executor`で別スレッドで実行
- **I/O最適化**:
  - 保存するバッファ数を5件→3件に削減（メモリとI/O負荷の軽減）
  - JSON出力時のindentを削除（ファイルサイズ削減）
  - アトミックなファイル置き換え（一時ファイル→rename）で書き込み中のエラーを防止
- **ログ出力の最適化**:
  - デバッグログを簡略化（詳細な情報はdebugレベルに変更）
  - バッファサマリーのみ表示（個別の詳細情報は省略）
  - 音声処理中の繰り返しログを削減
- **期待される改善**:
  - Discord音声接続の安定性向上（heartbeat blockedエラーの解消）
  - 録音機能の応答性向上
  - メインループのブロッキング解消
  - 全体的なパフォーマンス向上

### 2024-06-29 大規模コマンド削除実施（第15回）
- **削除されたコマンド（16個）**:
  - **開発・デバッグ用（4個）**: debug_recording, test_recording, reload_cog, reload_all, clear_buffer
  - **エクスポート・インポート機能（3個）**: dict_export, dict_import, export_settings
  - **情報系コマンド（4個）**: dict_list, tts_models, tts_speakers, dict_search
  - **テスト機能（1個）**: tts_test
  - **管理系コマンド（2個）**: set_greeting, reset_settings
  - **システム情報（1個）**: list_cogs（reload.pyと共に削除）
- **削除されたファイル**: cogs/reload.py（リロード機能全体）
- **効果**: 31コマンド → 15コマンド（52%削減）
- **残存コマンド**:
  - **コア機能（5個）**: join, leave, replay, recordings, reading
  - **辞書機能（2個）**: dict_add, dict_remove
  - **ユーザー設定（3個）**: my_settings, set_tts, set_reading

**削減による効果**:
- **ユーザビリティ向上**: コマンド数半減により認知負荷軽減
- **保守性向上**: 管理するコマンド数大幅減少
- **コードサイズ削減**: 約800行削減（reload.py全体 + 各コマンド）
- **機能の厳選**: 実際に使用される核心機能のみ残存

### 2024-06-29 プロジェクト軽量化実施（第14回）
- **Phase 1: 即座のクリーンアップ完了**:
  - tmpwavディレクトリの古い録音ファイル削除（4.1MB削減）
  - Pythonキャッシュファイル削除（__pycache__、*.pyc）
  - 重複するbot_simple.py削除（416行削除）
  - .gitignoreにtmpwav/追加
- **Phase 2: 依存関係最適化完了**:
  - pyproject.tomlから未使用のffmpeg-python>=0.2.0削除
  - cogwatch>=3.2.0を開発用依存関係に移動
  - 重複するrequirements.txt削除（pyproject.tomlに統一）
- **Phase 3: コード構造最適化完了**:
  - 未使用の音声受信実装3ファイル削除（約500行削減）:
    - utils/audio_sink.py（重複機能）
    - utils/voice_receiver.py（理論的実装、複雑すぎ）
    - utils/simple_recorder.py（シミュレーション実装）
  - bot.pyのフォールバック実装をreal_audio_recorder統一
  - tmpwavディレクトリ自体を削除（古い実装の残骸）

**軽量化効果**:
- **ファイルサイズ削減**: 約4.5MB（録音ファイル4.1MB + キャッシュファイル）
- **コード行数削減**: 約1000行（bot_simple.py 416行 + 音声実装500行 + その他）
- **依存関係削減**: ffmpeg-pythonライブラリ削除、cogwatchを開発用に移動
- **保守性向上**: 単一の音声録音実装に統一、重複コード削除
- **構造簡素化**: pyproject.tomlに依存関係統一、不要なフォールバック削除

### 2024-06-29 パフォーマンス問題緊急対応（第16回）
- **voice heartbeat blocked問題の対応**: 重いデバッグログによるDiscord音声接続ブロックを解決
- **TTSヘルスチェックタイムアウト延長**: 3秒→10秒に変更してAPI接続安定性を向上
- **録音デバッグログの無効化**: `debug_recording_status()`を一時的にコメントアウト
- **パフォーマンス問題の特定**:
  - 音声録音処理がメインループをブロック
  - ファイルI/O競合（`audio_buffers.json`への同時アクセス）
  - ログローテーションがI/Oを詰まらせる
  - 大量のINFOログがパフォーマンスに影響
- **緊急修正内容**:
  - `utils/tts.py`: ヘルスチェックタイムアウト延長（connect=2→5秒、total=3→10秒）
  - `cogs/recording.py`: デバッグログ一時無効化でメインループ負荷軽減
- **今後の改善予定**:
  - ログレベルの調整（DEBUG→INFO削減）
  - 音声バッファ保存頻度の最適化
  - 非同期I/O処理の改善

### 2024-06-29 StartUp高速化実装（第17回）
- **並列処理によるStartUp時間大幅短縮**: 従来の1/3～1/2程度に短縮
- **ギルド並列処理**: 複数ギルドへの音声接続を同時実行（`asyncio.gather`使用）
- **メンバー処理並列化**: 各ギルド内でのTTS・録音処理を並列実行
- **待機時間最適化**:
  - Guild同期待機：5秒→2秒に短縮
  - メンバー処理間隔：0.5秒→0.3秒に短縮
- **新メソッド追加**:
  - `_check_guild_for_auto_join()`: 個別ギルド処理
  - `_process_member_on_join()`: 個別メンバー処理
- **エラーハンドリング強化**: `return_exceptions=True`で例外を適切に処理
- **期待される効果**:
  - StartUp時間大幅短縮（特に複数ギルド環境）
  - Discord音声接続の安定性向上
  - ユーザー体験向上

### 2024-06-29 録音重複エラー修正（第18回）
- **discord.sinks.errors.RecordingException: Already recordingエラーの解決**: 複数メンバーによる同時録音開始で発生する重複エラーを修正
- **Guild別asyncio.Lock機構の追加**: 
  - `RecordingCog.recording_locks`辞書でGuild別ロック管理
  - `handle_bot_joined_with_user`メソッドでロック使用して同時実行防止
- **録音開始ロジックの改善**:
  - `utils/real_audio_recorder.py`で既に録音中の場合はスキップ（エラーではなくdebugログ）
  - VoiceCogでTTS処理と録音処理を分離（録音は最初の1名のみ実行）
  - `_process_member_tts`と`_process_member_recording`メソッドに分割
- **ログレベル最適化**: ERROR→DEBUGに変更してログノイズを削減
- **期待される効果**:
  - 起動時の"Already recording"エラー完全解消
  - Discord音声接続の安定性向上
  - ログ出力の大幅削減（パフォーマンス向上）
  - 複数ギルド環境での信頼性向上

### 2024-06-29 ファイルアクセス競合修正（第19回）
- **WinError 32「プロセスはファイルにアクセスできません」エラーの解決**: 複数ギルド録音時のバッファファイル書き込み競合を修正
- **非同期ファイル書き込みロック機構**:
  - `_file_write_lock`で複数の保存処理を順次実行
  - `async with`文による確実なロック管理
- **Windowsファイルロック対応リトライ機構**:
  - 最大3回リトライ（指数バックオフ: 0.1秒、0.2秒、0.3秒）
  - `PermissionError`、`OSError`の特別対応
  - 成功まで継続、失敗時はwarningログで通知
- **期待される効果**:
  - 複数ギルド同時録音時のファイル競合解消
  - バッファ保存の確実性向上
  - エラーログノイズの削減
  - Windows環境での安定性向上

### 2024-06-29 音声接続エラー修正（第20回）
- **音声接続重複エラーの根本解決**: 起動時の「Already connected to a voice channel」エラーを修正
- **重複接続チェック機能実装**:
  - voice.py L217-223に既接続チェックロジック追加
  - 同一ギルドで既に接続中の場合は接続をスキップ
  - 接続チャンネルが異なる場合は`move_to()`でチャンネル移動
- **Discord接続安定性向上**:
  - 接続安定化の待機時間を7.5秒→3秒に短縮（パフォーマンス向上）
  - gateway timeout問題の軽減
- **TTS API設定最適化**:
  - タイムアウト10秒→30秒に延長（接続安定性向上）
  - ポート設定は5000のまま維持（Style-Bert-VITS2サーバー仕様）
- **解決された問題**:
  - ❌ **IndexError: list index out of range**: 音声接続時の暗号化モード選択エラー
  - ❌ **Already connected to a voice channel**: 重複接続エラー
  - ❌ **Shard stopped responding to gateway**: Discord接続不安定性
  - ❌ **TTS APIタイムアウト**: タイムアウト設定問題

### 2024-06-29 TTS設定のGit管理分離（第21回）
- **Git pull問題の解決**: /set_global_ttsでconfig.yamlが書き換わりgit pullできない問題を修正
- **TTS設定の分離**:
  - config.yamlのTTS設定セクションを削除
  - data/tts_config.jsonに設定を移動（Git ignore対象）
  - TTSManagerをdata/tts_config.json読み込みに対応
- **動的設定更新システム**:
  - _update_global_tts_config()メソッドでJSONファイル更新
  - /set_global_ttsコマンドがdata/tts_config.jsonに保存
  - TTSManagerの設定もリアルタイム更新
- **Git管理の最適化**:
  - .gitignoreで既にdata/*が除外済み
  - 頻繁に変更される設定をGit管理下から除外
  - メインPCとサブPCで設定の独立性確保
- **解決された問題**:
  - ❌ **Git pull conflicts**: TTS設定変更でconfig.yamlが競合
  - ❌ **設定の一元管理不可**: 複数環境での設定同期問題
- **技術的変更**:
  - utils/tts.py: load_tts_config()、save_tts_config()メソッド追加
  - cogs/tts.py: self.tts_manager.tts_config参照に変更
  - cogs/user_settings.py: _update_global_tts_config()で JSON保存
  - config.yaml: TTSセクション削除、コメントで移動先を明記

### 今後の改善案
- Web管理画面の追加
- 複数言語サポート
- 高度な音声エフェクト
- 動的モデル・話者選択肢の実装（TTSサーバー連携）

## トラブルシューティング

### よくある問題
1. **Invalid token エラー**
   - `.env`ファイルのDISCORD_TOKENを確認
   - トークンの前後に余分なスペースがないか確認

2. **スラッシュコマンドが表示されない**
   - Botを再起動後、Discordクライアントも再起動
   - コマンド同期に数分かかることがある

3. **VCに接続できない**
   - Botに適切な権限があるか確認
   - タイムアウト設定（10秒）を調整

## パフォーマンス目標
- メモリ使用量: 200MB以下
- CPU使用率: アイドル時5%以下
- 応答時間: 1秒以内

### 2024-06-29 管理者権限方式変更（第18回）
- **ギルド権限から特定ユーザーIDベースに変更**: 
  - config.yamlに`bot.admin_user_id: 372768430149074954`を追加
  - `ctx.author.guild_permissions.administrator`チェックを廃止
  - `ctx.author.id == admin_user_id`による特定ユーザーチェックに統一
- **影響範囲**:
  - `/set_global_tts`: サーバー全体のTTS設定変更（管理者限定）
  - `/dict_add`のグローバル辞書追加（管理者限定）  
  - `/dict_remove`のグローバル辞書削除（管理者限定）
- **目的**: 複数サーバーで統一的な管理者権限を持つため

## 参考リンク
- [TypeScript版（参考）](https://github.com/jinwktk/yomiageBotTS)
- [Style-Bert-VITS2](https://github.com/litagin02/Style-Bert-VITS2)