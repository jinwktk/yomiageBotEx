"""
ロギング設定ユーティリティ
"""

import logging
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any


def setup_logging(config: Dict[str, Any]) -> logging.Logger:
    """ロギングの初期設定"""
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    
    log_level = getattr(logging, config["logging"]["level"], logging.INFO)
    log_file = config["logging"]["file"]
    
    # フォーマッターの設定
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # ファイルハンドラー
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    
    # コンソールハンドラー
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    
    # ロガーの設定
    logger = logging.getLogger()
    logger.setLevel(log_level)
    
    # 既存のハンドラーをクリア
    logger.handlers.clear()
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger


async def cleanup_old_logs(config: Dict[str, Any]):
    """古いログファイルを削除"""
    try:
        log_dir = Path("logs")
        if not log_dir.exists():
            return
        
        cleanup_days = config["logging"]["cleanup_days"]
        cutoff_date = datetime.now() - timedelta(days=cleanup_days)
        
        deleted_count = 0
        for log_file in log_dir.glob("*.log"):
            if log_file.stat().st_mtime < cutoff_date.timestamp():
                log_file.unlink()
                deleted_count += 1
        
        if deleted_count > 0:
            logger = logging.getLogger(__name__)
            logger.info(f"Deleted {deleted_count} old log file(s)")
            
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to cleanup old logs: {e}")


async def start_log_cleanup_task(config: Dict[str, Any]):
    """ログクリーンアップの定期実行タスクを開始"""
    while True:
        try:
            await cleanup_old_logs(config)
            # 24時間待機
            await asyncio.sleep(86400)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Error in log cleanup task: {e}")
            # エラー時は1時間後にリトライ
            await asyncio.sleep(3600)