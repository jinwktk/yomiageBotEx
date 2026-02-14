# タスク完了時の手順

## 必須実行コマンド

### 1. コードフォーマット
```bash
uv run black .
```
- Blackフォーマッターで統一的なコードスタイルを適用
- 行長88文字、Python 3.11対応の設定

### 2. リンター実行
```bash
uv run flake8 .
```
- コード品質チェック（構文エラー、スタイル違反等）
- エラーがある場合は修正が必要

### 3. テスト実行
```bash
uv run pytest
```
- 自動テスト実行（非同期テスト対応）
- 全テストが通過することを確認

## Git作業フロー

### 変更の確認
```bash
git status
git diff
```

### コミット作業
```bash
git add .
git commit -m "具体的な変更内容の説明"
git push
```

## 動作確認

### Bot起動テスト
```bash
# Windows
scripts\start.bat

# Linux/macOS  
./scripts/start.sh
```

### Discord動作確認
1. ボットがオンラインになることを確認
2. 主要なスラッシュコマンドが動作することを確認
   - `/join`
   - `/leave` 
   - `/reading`
   - `/replay`

## プロセス重複チェック（重要）

### Windows
```cmd
# 既存プロセス確認
tasklist | findstr python

# 必要に応じて既存プロセス終了
taskkill /f /im python.exe
```

**注意**: 複数のPythonプロセスでbot.pyが同時実行されることを防ぐため、起動前に必ず既存プロセスを確認・停止すること。

## ログ確認
```bash
# ログファイルの確認
tail -f logs/yomiage.log   # Linux/macOS
type logs\yomiage.log      # Windows
```

## 設定ファイル更新
変更内容に応じて以下を更新：
- `CLAUDE.md`: 作業内容の記録
- `README.md`: 機能追加等の場合
- `config.yaml`: 新しい設定項目追加の場合

## チェックリスト
- [ ] フォーマット実行（black）
- [ ] リンター通過（flake8）
- [ ] テスト実行（pytest）
- [ ] プロセス重複なし確認
- [ ] Bot正常起動確認
- [ ] Discord機能動作確認
- [ ] 変更内容コミット・プッシュ
- [ ] ドキュメント更新