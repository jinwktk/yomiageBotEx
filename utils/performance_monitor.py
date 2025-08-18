"""
パフォーマンス監視ユーティリティ
CPU、メモリ、ネットワークの使用状況を監視
"""

import asyncio
import logging
import time
import psutil
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import json

logger = logging.getLogger(__name__)


class PerformanceMonitor:
    """パフォーマンス監視クラス"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.monitoring_enabled = config.get("performance", {}).get("monitoring_enabled", True)
        self.monitoring_interval = config.get("performance", {}).get("monitoring_interval", 60)  # 60秒間隔
        self.alert_thresholds = {
            "cpu_percent": config.get("performance", {}).get("cpu_alert_threshold", 80.0),
            "memory_percent": config.get("performance", {}).get("memory_alert_threshold", 85.0),
            "disk_usage_percent": config.get("performance", {}).get("disk_alert_threshold", 90.0),
        }
        
        self.performance_history = []
        self.max_history_size = 100  # 最新100件まで保持
        self.last_alert_time = {}
        self.alert_cooldown = 300  # 5分間のアラートクールダウン
        
        self._monitoring_task: Optional[asyncio.Task] = None
        self._is_monitoring = False
    
    async def start_monitoring(self):
        """パフォーマンス監視を開始"""
        if not self.monitoring_enabled or self._is_monitoring:
            return
            
        self._is_monitoring = True
        self._monitoring_task = asyncio.create_task(self._monitoring_loop())
        logger.info("Performance monitoring started")
    
    async def stop_monitoring(self):
        """パフォーマンス監視を停止"""
        self._is_monitoring = False
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
        logger.info("Performance monitoring stopped")
    
    async def _monitoring_loop(self):
        """監視ループ"""
        try:
            while self._is_monitoring:
                try:
                    # パフォーマンス情報を収集
                    perf_data = await self.collect_performance_data()
                    
                    # 履歴に追加
                    self.performance_history.append(perf_data)
                    if len(self.performance_history) > self.max_history_size:
                        self.performance_history.pop(0)
                    
                    # アラートをチェック
                    await self._check_alerts(perf_data)
                    
                    # 設定された間隔で待機
                    await asyncio.sleep(self.monitoring_interval)
                    
                except Exception as e:
                    logger.error(f"Error in performance monitoring loop: {e}")
                    await asyncio.sleep(10)  # エラー時は10秒待機
                    
        except asyncio.CancelledError:
            logger.debug("Performance monitoring loop cancelled")
    
    async def collect_performance_data(self) -> Dict[str, Any]:
        """パフォーマンスデータを収集"""
        current_time = time.time()
        
        # CPU使用率
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_per_core = psutil.cpu_percent(interval=1, percpu=True)
        
        # メモリ使用量
        memory = psutil.virtual_memory()
        memory_percent = memory.percent
        memory_available_gb = memory.available / (1024**3)
        
        # ディスク使用量
        disk = psutil.disk_usage('/')
        disk_usage_percent = disk.percent
        disk_free_gb = disk.free / (1024**3)
        
        # ネットワーク統計
        network = psutil.net_io_counters()
        
        # プロセス情報（現在のPythonプロセス）
        process = psutil.Process()
        process_memory = process.memory_info().rss / (1024**2)  # MB
        process_cpu = process.cpu_percent()
        
        return {
            "timestamp": current_time,
            "datetime": datetime.now().isoformat(),
            "cpu": {
                "total_percent": cpu_percent,
                "per_core": cpu_per_core,
                "core_count": psutil.cpu_count()
            },
            "memory": {
                "percent": memory_percent,
                "available_gb": round(memory_available_gb, 2),
                "total_gb": round(memory.total / (1024**3), 2),
                "used_gb": round(memory.used / (1024**3), 2)
            },
            "disk": {
                "usage_percent": disk_usage_percent,
                "free_gb": round(disk_free_gb, 2),
                "total_gb": round(disk.total / (1024**3), 2)
            },
            "network": {
                "bytes_sent": network.bytes_sent,
                "bytes_recv": network.bytes_recv,
                "packets_sent": network.packets_sent,
                "packets_recv": network.packets_recv
            },
            "process": {
                "memory_mb": round(process_memory, 2),
                "cpu_percent": process_cpu,
                "threads": process.num_threads(),
                "connections": len(process.connections())
            }
        }
    
    async def _check_alerts(self, perf_data: Dict[str, Any]):
        """アラート条件をチェック"""
        current_time = time.time()
        alerts = []
        
        # CPU使用率チェック
        if perf_data["cpu"]["total_percent"] > self.alert_thresholds["cpu_percent"]:
            if self._should_send_alert("cpu", current_time):
                alerts.append(f"High CPU usage: {perf_data['cpu']['total_percent']:.1f}%")
                self.last_alert_time["cpu"] = current_time
        
        # メモリ使用率チェック
        if perf_data["memory"]["percent"] > self.alert_thresholds["memory_percent"]:
            if self._should_send_alert("memory", current_time):
                alerts.append(f"High memory usage: {perf_data['memory']['percent']:.1f}%")
                self.last_alert_time["memory"] = current_time
        
        # ディスク使用率チェック
        if perf_data["disk"]["usage_percent"] > self.alert_thresholds["disk_usage_percent"]:
            if self._should_send_alert("disk", current_time):
                alerts.append(f"High disk usage: {perf_data['disk']['usage_percent']:.1f}%")
                self.last_alert_time["disk"] = current_time
        
        # アラートをログ出力
        for alert in alerts:
            logger.warning(f"Performance Alert: {alert}")
    
    def _should_send_alert(self, alert_type: str, current_time: float) -> bool:
        """アラート送信の可否を判定（クールダウン考慮）"""
        last_alert = self.last_alert_time.get(alert_type, 0)
        return current_time - last_alert > self.alert_cooldown
    
    def get_current_stats(self) -> Optional[Dict[str, Any]]:
        """現在のパフォーマンス統計を取得"""
        if not self.performance_history:
            return None
        return self.performance_history[-1]
    
    def get_average_stats(self, minutes: int = 5) -> Optional[Dict[str, Any]]:
        """指定された分数の平均統計を取得"""
        if not self.performance_history:
            return None
        
        cutoff_time = time.time() - (minutes * 60)
        recent_data = [
            data for data in self.performance_history
            if data["timestamp"] > cutoff_time
        ]
        
        if not recent_data:
            return None
        
        # 平均値を計算
        avg_stats = {
            "timestamp": time.time(),
            "datetime": datetime.now().isoformat(),
            "sample_count": len(recent_data),
            "time_range_minutes": minutes,
            "cpu": {
                "avg_total_percent": sum(d["cpu"]["total_percent"] for d in recent_data) / len(recent_data),
                "max_total_percent": max(d["cpu"]["total_percent"] for d in recent_data),
                "min_total_percent": min(d["cpu"]["total_percent"] for d in recent_data)
            },
            "memory": {
                "avg_percent": sum(d["memory"]["percent"] for d in recent_data) / len(recent_data),
                "max_percent": max(d["memory"]["percent"] for d in recent_data),
                "min_available_gb": min(d["memory"]["available_gb"] for d in recent_data)
            },
            "process": {
                "avg_memory_mb": sum(d["process"]["memory_mb"] for d in recent_data) / len(recent_data),
                "max_memory_mb": max(d["process"]["memory_mb"] for d in recent_data),
                "avg_cpu_percent": sum(d["process"]["cpu_percent"] for d in recent_data) / len(recent_data)
            }
        }
        
        return avg_stats
    
    def format_stats_for_display(self, stats: Dict[str, Any]) -> str:
        """統計を表示用にフォーマット"""
        if not stats:
            return "パフォーマンス統計が利用できません"
        
        lines = [
            f"📊 **パフォーマンス統計** ({stats.get('datetime', 'Unknown')})",
            "",
            f"🖥️ **CPU**: {stats['cpu']['total_percent']:.1f}% ({stats['cpu']['core_count']}コア)",
            f"🧠 **メモリ**: {stats['memory']['percent']:.1f}% ({stats['memory']['used_gb']:.1f}GB / {stats['memory']['total_gb']:.1f}GB)",
            f"💾 **ディスク**: {stats['disk']['usage_percent']:.1f}% (空き: {stats['disk']['free_gb']:.1f}GB)",
            f"🔄 **プロセス**: {stats['process']['memory_mb']:.1f}MB, CPU {stats['process']['cpu_percent']:.1f}%",
            f"🌐 **ネットワーク**: 送信 {stats['network']['bytes_sent']//1024//1024}MB, 受信 {stats['network']['bytes_recv']//1024//1024}MB"
        ]
        
        return "\n".join(lines)
    
    async def generate_performance_report(self) -> str:
        """パフォーマンスレポートを生成"""
        current = self.get_current_stats()
        avg_5min = self.get_average_stats(5)
        avg_15min = self.get_average_stats(15)
        
        lines = [
            "📈 **詳細パフォーマンスレポート**",
            "",
            "**現在の状況:**"
        ]
        
        if current:
            lines.extend([
                f"CPU: {current['cpu']['total_percent']:.1f}%",
                f"メモリ: {current['memory']['percent']:.1f}%",
                f"プロセス: {current['process']['memory_mb']:.1f}MB"
            ])
        
        if avg_5min:
            lines.extend([
                "",
                "**5分間平均:**",
                f"CPU: {avg_5min['cpu']['avg_total_percent']:.1f}% (最大: {avg_5min['cpu']['max_total_percent']:.1f}%)",
                f"メモリ: {avg_5min['memory']['avg_percent']:.1f}% (最大: {avg_5min['memory']['max_percent']:.1f}%)",
                f"プロセスメモリ: {avg_5min['process']['avg_memory_mb']:.1f}MB (最大: {avg_5min['process']['max_memory_mb']:.1f}MB)"
            ])
        
        if avg_15min:
            lines.extend([
                "",
                "**15分間平均:**",
                f"CPU: {avg_15min['cpu']['avg_total_percent']:.1f}%",
                f"メモリ: {avg_15min['memory']['avg_percent']:.1f}%",
                f"プロセスメモリ: {avg_15min['process']['avg_memory_mb']:.1f}MB"
            ])
        
        return "\n".join(lines)


# グローバルなパフォーマンスモニターインスタンス
performance_monitor: Optional[PerformanceMonitor] = None


async def initialize_performance_monitor(config: Dict[str, Any]):
    """パフォーマンスモニターを初期化"""
    global performance_monitor
    
    try:
        performance_monitor = PerformanceMonitor(config)
        await performance_monitor.start_monitoring()
        logger.info("Performance monitor initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize performance monitor: {e}")


async def cleanup_performance_monitor():
    """パフォーマンスモニターをクリーンアップ"""
    global performance_monitor
    
    if performance_monitor:
        try:
            await performance_monitor.stop_monitoring()
            logger.info("Performance monitor cleaned up successfully")
        except Exception as e:
            logger.error(f"Error during performance monitor cleanup: {e}")