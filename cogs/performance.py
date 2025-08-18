"""
パフォーマンス監視Cog
システムのパフォーマンス情報を表示
"""

import asyncio
import logging
from typing import Dict, Any

import discord
from discord.ext import commands

from utils.performance_monitor import performance_monitor


class PerformanceCog(commands.Cog):
    """パフォーマンス監視機能を提供するCog"""
    
    def __init__(self, bot: commands.Bot, config: Dict[str, Any]):
        self.bot = bot
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # 管理者ユーザーID（設定から取得）
        self.admin_user_id = config.get("bot", {}).get("admin_user_id")
        
        self.logger.info("Performance: Initializing performance monitoring Cog")
    
    def _is_admin(self, user_id: int) -> bool:
        """管理者権限チェック"""
        return self.admin_user_id and user_id == self.admin_user_id
    
    @discord.slash_command(name="performance", description="システムのパフォーマンス情報を表示します")
    async def performance_command(self, ctx: discord.ApplicationContext):
        """パフォーマンス情報を表示するコマンド"""
        await ctx.defer(ephemeral=True)
        
        try:
            if not performance_monitor:
                await ctx.followup.send("⚠️ パフォーマンス監視が無効になっています。", ephemeral=True)
                return
            
            # 現在の統計を取得
            current_stats = performance_monitor.get_current_stats()
            
            if not current_stats:
                await ctx.followup.send("⚠️ パフォーマンスデータがまだ収集されていません。", ephemeral=True)
                return
            
            # 統計をフォーマット
            stats_text = performance_monitor.format_stats_for_display(current_stats)
            
            # Embedで見やすく表示
            embed = discord.Embed(
                title="🔧 システムパフォーマンス",
                description=stats_text,
                color=discord.Color.blue()
            )
            
            # CPU使用率に応じて色を変更
            cpu_percent = current_stats['cpu']['total_percent']
            if cpu_percent > 80:
                embed.color = discord.Color.red()
            elif cpu_percent > 60:
                embed.color = discord.Color.orange()
            else:
                embed.color = discord.Color.green()
            
            embed.set_footer(text="パフォーマンス監視は1分間隔で更新されます")
            
            await ctx.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            self.logger.error(f"Failed to show performance stats: {e}")
            await ctx.followup.send(f"⚠️ パフォーマンス情報の取得に失敗しました: {str(e)}", ephemeral=True)
    
    @discord.slash_command(name="perf_report", description="詳細パフォーマンスレポートを表示します（管理者限定）")
    async def performance_report_command(self, ctx: discord.ApplicationContext):
        """詳細パフォーマンスレポートを表示するコマンド（管理者限定）"""
        await ctx.defer(ephemeral=True)
        
        # 管理者権限チェック
        if not self._is_admin(ctx.author.id):
            await ctx.followup.send("⚠️ この機能は管理者限定です。", ephemeral=True)
            return
        
        try:
            if not performance_monitor:
                await ctx.followup.send("⚠️ パフォーマンス監視が無効になっています。", ephemeral=True)
                return
            
            # 詳細レポートを生成
            report = await performance_monitor.generate_performance_report()
            
            # Embedで表示
            embed = discord.Embed(
                title="📊 詳細パフォーマンスレポート",
                description=report,
                color=discord.Color.purple()
            )
            
            # 現在の統計を取得して追加情報を表示
            current_stats = performance_monitor.get_current_stats()
            if current_stats:
                embed.add_field(
                    name="ネットワーク",
                    value=f"送信: {current_stats['network']['bytes_sent']//1024//1024}MB\\n"
                          f"受信: {current_stats['network']['bytes_recv']//1024//1024}MB",
                    inline=True
                )
                
                embed.add_field(
                    name="プロセス",
                    value=f"スレッド: {current_stats['process']['threads']}\\n"
                          f"接続: {current_stats['process']['connections']}",
                    inline=True
                )
            
            embed.set_footer(text=f"監視履歴: {len(performance_monitor.performance_history)}件")
            
            await ctx.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            self.logger.error(f"Failed to generate performance report: {e}")
            await ctx.followup.send(f"⚠️ パフォーマンスレポートの生成に失敗しました: {str(e)}", ephemeral=True)


def setup(bot):
    """Cogのセットアップ"""
    bot.add_cog(PerformanceCog(bot, bot.config))