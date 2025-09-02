# コードスタイル・規約

## コードフォーマット
- **フォーマッター**: Black
  - 行長制限: 88文字
  - ターゲットバージョン: Python 3.11

## 型ヒント
- `typing`モジュールからのタイプヒントを使用
- 例: `Dict[str, Any]`, `Optional[discord.Member]`

## docstring規約
- 関数・クラス・モジュールレベルでdocstringを記述
- 日本語でのdocstringを使用
- 例:
  ```python
  def rate_limit_delay(self):
      """レート制限対策の遅延"""
  ```

## インポート順序
1. 標準ライブラリ
2. サードパーティライブラリ  
3. ローカルインポート

例：
```python
import asyncio
import random
import logging
from typing import Dict, Any
import json
from pathlib import Path

import discord
from discord.ext import commands, tasks
```

## 命名規約
- **クラス名**: CamelCase（例: `VoiceCog`, `YomiageBot`）
- **関数名・変数名**: snake_case（例: `rate_limit_delay`, `saved_sessions`）
- **定数**: UPPER_SNAKE_CASE（例: `LOCK_FILE`, `VOICE_CLIENT_TYPE`）
- **プライベートメソッド**: アンダースコアプレフィックス（例: `_check_guild_for_auto_join`）

## ログメッセージ
- 詳細な処理状況をログ出力
- レベル別の使い分け:
  - `INFO`: 通常の処理状況
  - `WARNING`: 警告レベルの問題
  - `ERROR`: エラー情報（`exc_info=True`で詳細表示）
  - `DEBUG`: デバッグ用詳細情報

## 設定管理
- `config.yaml`による一元管理
- 環境変数は`.env`ファイル使用（Discord Token等の機密情報）
- デフォルト値をコード内に保持し、設定ファイルなしでも動作可能

## エラーハンドリング
- try-except文で例外を適切に処理
- グローバルエラーハンドラーで未捕捉例外を記録
- ボット全体を停止させない設計