# CLAUDE.md - yomiageBotEx プロジェクトドキュメント

## プロジェクト概要
Discord読み上げボット（Python版）の実装。TypeScript版の失敗を踏まえ、段階的に機能を追加していく方針で開発。

## フォルダ構成

### Phase 1 (現在の構成)
```
yomiageBotEx/
├── bot.py              # メインボットファイル
├── config.yaml         # 設定ファイル
├── .env               # Discordトークン（Gitignore対象）
├── .gitignore         # Git除外設定
├── requirements.txt    # 依存関係
├── CLAUDE.md          # このファイル
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

### Phase 2: 自動機能（予定）
- [ ] Cog構造の導入
- [ ] 自動参加・退出（0人チェック付き）
- [ ] 5分ごとの空チャンネルチェック

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
- ffmpeg-python（音声処理用、Phase 3以降）

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

### 今後の課題
- Phase 2でCog構造に移行（コードの整理）
- 自動参加・退出の実装時は0人チェックを忘れずに
- Style-Bert-VITS2の統合方法を調査する必要あり

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