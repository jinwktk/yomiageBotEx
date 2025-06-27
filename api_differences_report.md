# discord.py vs py-cord API 差分調査結果

## 調査環境
- **インストール済みライブラリ**: py-cord 2.6.1
- **プロジェクト設定**: pyproject.toml で py-cord[voice]>=2.4.0 を指定
- **既存コード**: discord.py の app_commands 形式で実装

## 主要な差分

### 1. Botクラスの違い

#### discord.py
```python
from discord.ext import commands

class Bot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="/", intents=intents)
        # self.tree が利用可能（CommandTree）
```

#### py-cord
```python
# 方法1: commands.Bot（app_commands非対応）
from discord.ext import commands
class Bot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="/", intents=intents)
        # self.tree は利用不可

# 方法2: discord.Bot（推奨）
import discord
class Bot(discord.Bot):
    def __init__(self):
        super().__init__(intents=intents)
```

### 2. スラッシュコマンドの実装

#### discord.py (現在のコード)
```python
from discord import app_commands

@app_commands.command(name="join", description="説明")
async def join_command(self, interaction: discord.Interaction):
    await interaction.response.send_message("...")
```

#### py-cord (必要な修正)
```python
import discord

# Cogの場合
@discord.slash_command(name="join", description="説明")
async def join_command(self, ctx):
    await ctx.respond("...")
```

### 3. コマンド同期

#### discord.py (現在のコード)
```python
# setup_hook で実行
synced = await self.tree.sync()
```

#### py-cord (修正不要)
```python
# discord.Bot 使用時は自動同期される
```

## 現在のコードで修正が必要な箇所

### 1. `/mnt/c/Users/mlove/OneDrive/ドキュメント/GitHub/yomiageBotEx/bot.py`
- **行97**: `await self.tree.sync()` → 削除またはコメントアウト
- **行67-81**: `commands.Bot` → `discord.Bot` への変更を検討

### 2. `/mnt/c/Users/mlove/OneDrive/ドキュメント/GitHub/yomiageBotEx/cogs/voice.py`
- **行15**: `from discord import app_commands` → 削除
- **行231, 302**: `@app_commands.command(...)` → `@discord.slash_command(...)`
- **パラメータ**: `interaction: discord.Interaction` → `ctx`
- **レスポンス**: `await interaction.response.send_message(...)` → `await ctx.respond(...)`

### 3. `/mnt/c/Users/mlove/OneDrive/ドキュメント/GitHub/yomiageBotEx/cogs/recording.py`
- **行14**: `from discord import app_commands` → 削除
- **行154, 239, 293**: `@app_commands.command(...)` → `@discord.slash_command(...)`
- **行155**: `@app_commands.describe(...)` → `@discord.option(...)`
- **レスポンス形式の変更**

### 4. その他のCogファイル
- message_reader.py でも同様の修正が必要

## VoiceChannel接続の互換性

✅ **互換性あり**: `channel.connect()` や `VoiceClient` の基本APIは同じ
✅ **互換性あり**: 音声受信機能も基本的に同じ

## 推奨修正アプローチ

### Option 1: 最小限修正 (commands.Bot維持)
- app_commands関連のコードを削除
- スラッシュコマンドを通常のテキストコマンドに変更

### Option 2: 完全py-cord対応 (推奨)
- `commands.Bot` → `discord.Bot` に変更
- すべてのスラッシュコマンドをpy-cord形式に変更
- より自然なpy-cordの機能活用

### Option 3: ハイブリッド対応
- 環境変数でライブラリを判定し、動的に切り替え

## テスト結果

### ✅ 動作確認済み
- py-cord 2.6.1 のインストール
- 基本的なBot クラスのインスタンス化
- Intents 設定
- VoiceClient の利用可能性

### ❌ 修正が必要
- app_commands の使用
- tree.sync() の実行
- スラッシュコマンドの定義方法

## 次のステップ

1. **Option 2**（完全py-cord対応）での修正を実施
2. 修正後の動作テスト
3. CLAUDE.md の更新