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
│   └── recording.py   # 録音・リプレイ機能Cog
├── utils/             # ユーティリティモジュール
│   ├── __init__.py    # ユーティリティパッケージ初期化
│   ├── logger.py      # ロギング設定ユーティリティ
│   ├── tts.py         # TTS機能ユーティリティ
│   └── recording.py   # 録音・リプレイ機能ユーティリティ
├── scripts/           # 起動スクリプト
│   ├── start.sh       # Linux/macOS用起動スクリプト
│   └── start.bat      # Windows用起動スクリプト
├── pyproject.toml     # uv用プロジェクト設定
├── .python-version    # Python バージョン指定
├── uv.lock           # uv依存関係ロックファイル
├── cache/             # TTSキャッシュディレクトリ（自動生成）
│   └── tts/          # TTS音声キャッシュ
├── recordings/        # 録音ファイルディレクトリ（自動生成）
│   └── *.wav         # 録音ファイル（1時間後自動削除）
└── logs/              # ログディレクトリ（自動生成）
    └── yomiage.log    # ボットのログ
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

### 今後の課題
- Style-Bert-VITS2 APIサーバーのセットアップ手順作成
- 実際の音声品質テストと最適化
- パフォーマンス監視とメモリ使用量の最適化
- Discord音声受信の詳細実装（現在は簡易版）

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

## 参考リンク
- [TypeScript版（参考）](https://github.com/jinwktk/yomiageBotTS)
- [Style-Bert-VITS2](https://github.com/litagin02/Style-Bert-VITS2)