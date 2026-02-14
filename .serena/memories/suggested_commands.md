# 推奨コマンド・開発者向けガイド

## 基本セットアップ

### 依存関係のインストール
```bash
# 推奨: uv使用
uv sync --no-install-project

# または、pip使用
pip install -r requirements.txt           # 開発ツール込み
pip install -r requirements-minimal.txt   # 最小限のみ
```

### 開発環境セットアップ
```bash
# 開発用依存関係のインストール
uv sync --dev --no-install-project
```

## 開発用コマンド

### コードフォーマット
```bash
# Black使用（推奨設定: 行長88文字、Python 3.11対応）
uv run black .
```

### リンター実行
```bash
# flake8でコード品質チェック
uv run flake8 .
```

### テスト実行
```bash
# pytestでテスト実行（非同期対応）
uv run pytest
```

## アプリケーション実行

### 手動起動
```bash
# uv使用（推奨）
uv run --no-project python bot.py
```

### スクリプト使用（推奨）
```bash
# Windows
scripts\start.bat

# Linux/macOS
./scripts/start.sh
```

## Windowsシステムコマンド

### プロセス管理
```cmd
# Pythonプロセス確認
tasklist | findstr python

# プロセス強制終了
taskkill /f /im python.exe

# 特定PIDのプロセス終了
taskkill /PID [PID番号] /F
```

### ファイル・ディレクトリ操作
```cmd
# ディレクトリ内容表示
dir

# ファイル検索
findstr "検索文字列" *.py

# ディレクトリ移動
cd path\to\directory

# ファイルコピー
copy source.txt destination.txt
```

## Git操作
```bash
# 最新コード取得
git pull

# ステータス確認
git status

# 変更をコミット
git add .
git commit -m "コミットメッセージ"

# リモートにプッシュ
git push
```

## 設定ファイル管理

### 必要な設定
1. `.env`ファイル作成:
```env
DISCORD_TOKEN=your_discord_bot_token_here
```

2. `config.yaml`で各種設定調整（オプション）

### Style-Bert-VITS2セットアップ（オプション）
```bash
# APIサーバーが動作しているか確認
curl http://127.0.0.1:8000/status
```

## タスク完了時の実行コマンド
1. **コードフォーマット**: `uv run black .`
2. **リンター実行**: `uv run flake8 .` 
3. **テスト実行**: `uv run pytest`
4. **動作確認**: ボット起動してDiscordでコマンドテスト