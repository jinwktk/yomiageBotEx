# yomiageBotEx Windows環境セットアップガイド

## 概要
Windows環境（Python 3.13）でyomiageBotExを動作させるためのセットアップガイドです。

## 前提条件
- Windows 10/11
- Python 3.10以上（3.13推奨）
- Git for Windows
- インターネット接続
- Discord Bot Token

## 1. 必要なソフトウェアのインストール

### 1.1 Python 3.13
- [Python公式サイト](https://python.org)からダウンロード
- インストール時に「Add Python to PATH」にチェック
- コマンドプロンプトで確認：`python --version`

### 1.2 Git for Windows
- [Git公式サイト](https://git-scm.com)からダウンロード・インストール

### 1.3 FFmpeg（重要）
Windows版FFmpegのインストール方法：

#### 方法1: Chocolatey使用（推奨）
```powershell
# PowerShellを管理者権限で開く
Set-ExecutionPolicy Bypass -Scope Process -Force; 
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072; 
iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))

# FFmpegをインストール
choco install ffmpeg
```

#### 方法2: 手動インストール
1. [FFmpeg公式サイト](https://ffmpeg.org/download.html#build-windows)からWindows版をダウンロード
2. 解凍して`C:\ffmpeg`に配置
3. 環境変数PATHに`C:\ffmpeg\bin`を追加
4. コマンドプロンプトで確認：`ffmpeg -version`

#### 方法3: winget使用
```cmd
winget install Gyan.FFmpeg
```

### 1.4 Visual Studio Build Tools（Python 3.13でPyNaClビルド用）
- [Build Tools for Visual Studio](https://visualstudio.microsoft.com/visual-cpp-build-tools/)をダウンロード
- C++ build toolsをインストール

## 2. プロジェクトセットアップ

### 2.1 リポジトリクローン
```cmd
git clone https://github.com/yourusername/yomiageBotEx.git
cd yomiageBotEx
```

### 2.2 Python仮想環境構築
```cmd
# 仮想環境作成
python -m venv venv

# 仮想環境アクティベート
venv\Scripts\activate

# pipアップグレード
python -m pip install --upgrade pip setuptools wheel
```

### 2.3 Python依存関係インストール
```cmd
# Python 3.13対応の音声ライブラリ（順番重要）
pip install audioop-lts
pip install PyNaCl==1.5.0

# discord.py
pip install "discord.py[voice]>=2.3.0"

# その他の依存関係
pip install -r requirements.txt
```

## 3. 設定ファイル準備

### 3.1 .envファイル
```cmd
copy .env.example .env
notepad .env
```

内容を編集：
```
DISCORD_TOKEN=your_actual_discord_bot_token
APPLICATION_ID=your_actual_application_id
DEBUG_GUILD_ID=your_debug_guild_id
```

### 3.2 TTS設定ファイル
```cmd
mkdir data
notepad data\tts_config.json
```

内容：
```json
{
  "api_url": "http://192.168.0.99:5000",
  "timeout": 30,
  "cache_size": 5,
  "cache_hours": 24,
  "max_text_length": 100,
  "model_id": 7,
  "speaker_id": 0,
  "style": "Neutral",
  "greeting": {
    "enabled": false,
    "skip_on_startup": true,
    "startup_message": "おもちだよ",
    "join_message": "さん、こんちゃ！",
    "leave_message": "さん、またね！"
  }
}
```

## 4. Windows用起動スクリプト作成

### 4.1 start.bat
```cmd
mkdir scripts
notepad scripts\start.bat
```

内容：
```batch
@echo off
cd /d "%~dp0\.."

echo yomiageBotEx を起動中...

REM 仮想環境をアクティベート
call venv\Scripts\activate.bat

REM 必要なディレクトリを作成
if not exist logs mkdir logs
if not exist cache mkdir cache
if not exist recordings mkdir recordings
if not exist data mkdir data

REM Pythonパスを設定
set PYTHONPATH=%PYTHONPATH%;%CD%

REM 設定ファイル確認
if not exist .env (
    echo エラー: .envファイルが見つかりません
    pause
    exit /b 1
)

if not exist data\tts_config.json (
    echo エラー: TTS設定ファイルが見つかりません
    pause
    exit /b 1
)

REM ボット起動
python bot.py

echo ボットが停止しました
pause
```

### 4.2 start_daemon.bat
```cmd
notepad scripts\start_daemon.bat
```

内容：
```batch
@echo off
cd /d "%~dp0\.."

echo バックグラウンドでyomiageBotExを起動中...

REM 既存プロセス確認
tasklist /FI "IMAGENAME eq python.exe" /FO CSV | findstr "bot.py" >nul
if %ERRORLEVEL% == 0 (
    echo ボットは既に起動しています
    pause
    exit /b 1
)

REM バックグラウンド起動
start /B "" scripts\start.bat

echo ボットをバックグラウンドで起動しました
echo ログ確認: type logs\yomiage.log
echo 停止: scripts\stop_daemon.bat
pause
```

### 4.3 stop_daemon.bat
```cmd
notepad scripts\stop_daemon.bat
```

内容：
```batch
@echo off
echo yomiageBotExを停止中...

REM Pythonプロセスを終了
taskkill /F /IM python.exe /FI "COMMANDLINE:bot.py" >nul 2>&1

if %ERRORLEVEL% == 0 (
    echo ボットを停止しました
) else (
    echo 実行中のボットが見つかりませんでした
)

pause
```

## 5. 動作テスト

### 5.1 FFmpegテスト
```cmd
ffmpeg -version
```

### 5.2 Pythonモジュールテスト
```cmd
venv\Scripts\activate
python -c "import discord; import PyNaCl; import audioop_lts; print('すべてのモジュールOK')"
```

### 5.3 ボット起動
```cmd
scripts\start.bat
```

## 6. Windows固有のトラブルシューティング

### 6.1 FFmpegエラー
```
FileNotFoundError: [WinError 2] The system cannot find the file specified
```
- FFmpegがPATHに追加されているか確認
- コマンドプロンプトで`ffmpeg -version`が動作するか確認

### 6.2 PyNaClビルドエラー
```
Microsoft Visual C++ 14.0 is required
```
- Visual Studio Build Toolsをインストール
- または、プリビルド版を使用：`pip install --only-binary=all PyNaCl`

### 6.3 audioop エラー（Python 3.13）
```
ModuleNotFoundError: No module named 'audioop'
```
- `pip install audioop-lts`でLTSバージョンをインストール

### 6.4 権限エラー
- スクリプトを管理者権限で実行
- ウイルス対策ソフトの除外設定を確認

### 6.5 文字エンコーディングエラー
- コマンドプロンプト/PowerShellの文字コードを確認
- `chcp 65001`でUTF-8に変更

## 7. パフォーマンス最適化（Windows）

### 7.1 Windowsファイアウォール設定
- Python.exeをファイアウォール例外に追加

### 7.2 タスクスケジューラー設定（自動起動）
```cmd
# 管理者権限でコマンドプロンプトを開く
schtasks /create /tn "yomiageBotEx" /tr "C:\path\to\yomiageBotEx\scripts\start.bat" /sc onstart
```

### 7.3 Windowsサービス化（高度）
- NSSM（Non-Sucking Service Manager）を使用
- [NSSM公式サイト](https://nssm.cc/)からダウンロード

```cmd
# NSSMでサービス作成
nssm install yomiageBotEx "C:\path\to\yomiageBotEx\scripts\start.bat"
nssm start yomiageBotEx
```

## 8. 更新手順

```cmd
# 最新版取得
git pull origin main

# 仮想環境アクティベート
venv\Scripts\activate

# 依存関係更新
pip install --upgrade -r requirements.txt

# ボット再起動
scripts\stop_daemon.bat
scripts\start_daemon.bat
```

## 9. よくある問題（Windows版）

| 問題 | 原因 | 解決法 |
|------|------|--------|
| `ffmpeg not found` | FFmpeg未インストール | Chocolateyまたは手動インストール |
| `audioop not found` | Python 3.13互換性 | `pip install audioop-lts` |
| `PyNaCl build failed` | Visual Studio不足 | Build Toolsインストール |
| `Permission denied` | 管理者権限不足 | 管理者として実行 |
| `Encoding error` | 文字コード問題 | `chcp 65001` |

## サポート

Windows固有の問題については：
1. `logs\yomiage.log`でエラー確認
2. イベントビューアーでシステムエラー確認
3. GitHub Issuesで報告（OS情報も併記）