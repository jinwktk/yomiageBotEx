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
│   └── voice.py       # ボイスチャンネル管理Cog
├── utils/             # ユーティリティモジュール
│   ├── __init__.py    # ユーティリティパッケージ初期化
│   └── logger.py      # ロギング設定ユーティリティ
├── scripts/           # 起動スクリプト
│   ├── start.sh       # Linux/macOS用起動スクリプト
│   └── start.bat      # Windows用起動スクリプト
├── pyproject.toml     # uv用プロジェクト設定
├── .python-version    # Python バージョン指定
├── uv.lock           # uv依存関係ロックファイル
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

### Phase 3: TTS統合（予定）
- [ ] Style-Bert-VITS2統合
- [ ] 挨拶機能（参加/退出）
- [ ] 音声キャッシュ

### Phase 4: 録音機能（予定）
- [ ] 録音・リプレイ機能
- [ ] バッファ管理

## 技術的詳細

### 使用ライブラリ
- discord.py 2.3.0以上（py-cordは使用しない）
- python-dotenv（環境変数管理）
- pyyaml（設定ファイル）
- aiofiles（非同期ファイル操作）
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

### 今後の課題
- Style-Bert-VITS2の統合方法を調査する必要あり
- TTS機能の設計（軽量化重視）
- 録音・リプレイ機能の実装方針決定

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