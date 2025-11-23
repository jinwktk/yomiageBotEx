"""
ロギング設定ユーティリティ
ログファイルの管理と設定（ローテーション機能付き）
"""

import logging
import logging.handlers
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any
import os
import gzip
import shutil
import threading
import time


class CompressedRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """圧縮機能付きローテーティングファイルハンドラー"""
    
    def doRollover(self):
        """ログローテーション時の処理（圧縮付き）"""
        if self.stream:
            self.stream.close()
            self.stream = None
        
        if self.backupCount > 0:
            for i in range(self.backupCount - 1, 0, -1):
                sfn = f"{self.baseFilename}.{i}.gz"
                dfn = f"{self.baseFilename}.{i + 1}.gz"
                if os.path.exists(sfn):
                    if os.path.exists(dfn):
                        os.remove(dfn)
                    os.rename(sfn, dfn)
            
            # 現在のファイルを非同期で圧縮
            dfn = f"{self.baseFilename}.1.gz"
            if os.path.exists(dfn):
                os.remove(dfn)

            source_path = f"{self.baseFilename}.{int(time.time())}.tmp"
            if os.path.exists(self.baseFilename):
                os.replace(self.baseFilename, source_path)

                def _compress():
                    try:
                        with open(source_path, 'rb') as f_in:
                            with gzip.open(dfn, 'wb') as f_out:
                                shutil.copyfileobj(f_in, f_out)
                    except Exception as exc:
                        logging.getLogger(__name__).warning(f"Log compression failed: {exc}")
                    finally:
                        try:
                            if os.path.exists(source_path):
                                os.remove(source_path)
                        except Exception:
                            pass

                threading.Thread(target=_compress, name="LogCompressor", daemon=True).start()
        
        if not self.delay:
            self.stream = self._open()


def rotate_log_on_startup(log_file: str):
    """起動時にログをローテーションする"""
    try:
        log_path = Path(log_file)
        if not log_path.exists():
            return
        
        # 現在のログファイルのサイズをチェック
        file_size = log_path.stat().st_size
        
        # ファイルが存在し、サイズが0より大きい場合のみローテーション
        if file_size > 0:
            # タイムスタンプ付きのバックアップファイル名を生成
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_file = log_path.parent / f"{log_path.stem}_{timestamp}.log"
            
            # 現在のログファイルをリネーム
            log_path.rename(backup_file)
            
            # バックアップファイルを圧縮
            compressed_file = backup_file.with_suffix('.log.gz')
            with open(backup_file, 'rb') as f_in:
                with gzip.open(compressed_file, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            
            # 元のファイルを削除
            backup_file.unlink()
            
            print(f"[OK] Log rotated on startup: {compressed_file}")
        
    except Exception as e:
        print(f"[WARNING] Failed to rotate log on startup: {e}")


def setup_logging(config: Dict[str, Any]) -> logging.Logger:
    """ロギングの設定（ローテーション機能付き）"""
    log_config = config.get("logging", {})
    log_level = getattr(logging, log_config.get("level", "INFO").upper())
    log_file = log_config.get("file", "logs/yomiage.log")
    
    # ローテーション設定
    rotation_config = log_config.get("rotation", {})
    max_bytes = rotation_config.get("max_bytes", 10 * 1024 * 1024)  # 10MB
    backup_count = rotation_config.get("backup_count", 5)
    use_compression = rotation_config.get("compression", True)
    rotate_on_startup = rotation_config.get("rotate_on_startup", True)
    
    # ログディレクトリの作成
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 起動時のログローテーション
    if rotate_on_startup:
        rotate_log_on_startup(log_file)
    
    # ロガーの設定
    logger = logging.getLogger()
    logger.setLevel(log_level)
    
    # 既存のハンドラーをクリア
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # ファイルハンドラー（ローテーション機能付き）
    if use_compression:
        file_handler = CompressedRotatingFileHandler(
            log_file, 
            maxBytes=max_bytes, 
            backupCount=backup_count,
            encoding='utf-8'
        )
    else:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, 
            maxBytes=max_bytes, 
            backupCount=backup_count,
            encoding='utf-8'
        )
    
    file_handler.setLevel(log_level)
    
    # コンソールハンドラー
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    
    # フォーマッター
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # ハンドラーを追加
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    logger.info(f"Logging setup complete - Level: {log_level}, File: {log_file}")
    logger.info(f"Log rotation - MaxBytes: {max_bytes}, BackupCount: {backup_count}, Compression: {use_compression}")
    
    return logger


async def start_log_cleanup_task(config: Dict[str, Any]):
    """ログクリーンアップタスクを開始"""
    cleanup_config = config.get("logging", {}).get("cleanup", {})
    enabled = cleanup_config.get("enabled", True)
    
    if not enabled:
        logging.info("Log cleanup disabled")
        return
    
    logging.info("Starting log cleanup task")
    
    # 1日ごとにクリーンアップを実行
    while True:
        try:
            await cleanup_old_logs(config)
            await asyncio.sleep(24 * 60 * 60)  # 24時間待機
        except Exception as e:
            logging.error(f"Log cleanup task error: {e}")
            await asyncio.sleep(60 * 60)  # エラー時は1時間後に再試行


async def cleanup_old_logs(config: Dict[str, Any]):
    """古いログファイルを削除"""
    try:
        cleanup_config = config.get("logging", {}).get("cleanup", {})
        max_days = cleanup_config.get("max_days", 30)  # デフォルト30日
        log_dir = Path(config.get("logging", {}).get("file", "logs/yomiage.log")).parent
        
        if not log_dir.exists():
            return
        
        cutoff_date = datetime.now() - timedelta(days=max_days)
        deleted_count = 0
        
        # ログファイル（.log, .gz）を検索
        for pattern in ["*.log.*", "*.gz"]:
            for log_file in log_dir.glob(pattern):
                try:
                    # 現在使用中のファイルはスキップ
                    if log_file.name.endswith('.log') and not any(char.isdigit() for char in log_file.name):
                        continue
                    
                    # ファイルの更新日時をチェック
                    file_mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
                    
                    if file_mtime < cutoff_date:
                        file_size = log_file.stat().st_size
                        log_file.unlink()
                        deleted_count += 1
                        logging.info(f"Deleted old log file: {log_file} ({file_size} bytes)")
                        
                except Exception as e:
                    logging.error(f"Failed to process log file {log_file}: {e}")
        
        if deleted_count > 0:
            logging.info(f"Log cleanup completed: {deleted_count} files deleted")
        else:
            logging.debug("No old log files to delete")
                
    except Exception as e:
        logging.error(f"Log cleanup failed: {e}")


def get_log_stats(config: Dict[str, Any]) -> Dict[str, Any]:
    """ログファイルの統計情報を取得"""
    try:
        log_file = config.get("logging", {}).get("file", "logs/yomiage.log")
        log_dir = Path(log_file).parent
        
        if not log_dir.exists():
            return {"error": "Log directory not found"}
        
        stats = {
            "current_log": None,
            "rotated_logs": [],
            "total_size": 0,
            "total_files": 0
        }
        
        # 現在のログファイル
        current_log = Path(log_file)
        if current_log.exists():
            stats["current_log"] = {
                "name": current_log.name,
                "size": current_log.stat().st_size,
                "modified": datetime.fromtimestamp(current_log.stat().st_mtime).isoformat()
            }
            stats["total_size"] += current_log.stat().st_size
            stats["total_files"] += 1
        
        # ローテーションされたログファイル
        for log_file_path in sorted(log_dir.glob("*.log.*")):
            file_info = {
                "name": log_file_path.name,
                "size": log_file_path.stat().st_size,
                "modified": datetime.fromtimestamp(log_file_path.stat().st_mtime).isoformat(),
                "compressed": log_file_path.suffix == ".gz"
            }
            stats["rotated_logs"].append(file_info)
            stats["total_size"] += log_file_path.stat().st_size
            stats["total_files"] += 1
        
        return stats
        
    except Exception as e:
        return {"error": str(e)}
