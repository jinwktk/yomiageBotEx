#!/usr/bin/env python3
"""
SmoothAudioRelay status checker
Current relay sessions and RecordingCallbackManager status
"""

import asyncio
import discord
from dotenv import load_dotenv
import os
import yaml
import logging

async def main():
    print("SmoothAudioRelay Status Check")
    print("=" * 50)
    
    # Load environment and config
    load_dotenv()
    with open('config.yaml', 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    # Setup Discord bot (minimal)
    intents = discord.Intents.default()
    intents.message_content = True
    intents.voice_states = True
    
    bot = discord.Bot(intents=intents)
    logger = logging.getLogger('status_check')
    
    @bot.event
    async def on_ready():
        try:
            print(f"Bot logged in as: {bot.user}")
            
            # 1. Check SmoothAudioRelay status
            from utils.smooth_audio_relay import SmoothAudioRelay
            relay = SmoothAudioRelay(bot, config, logger)
            
            print(f"1. SmoothAudioRelay Status:")
            print(f"   - Enabled: {relay.enabled}")
            print(f"   - Recording Callback Enabled: {relay.recording_callback_enabled}")
            print(f"   - Active Sessions: {len(relay.active_sessions)}")
            
            if hasattr(relay, 'active_sessions') and relay.active_sessions:
                for session_id, session in relay.active_sessions.items():
                    print(f"   - Session {session_id[:8]}:")
                    print(f"     * Status: {session.status}")
                    print(f"     * Source: Guild {session.source_guild_id}")
                    print(f"     * Target: Guild {session.target_guild_id}")
            else:
                print("   - No active sessions found")
            
            # 2. Check RecordingCallbackManager status
            from utils.recording_callback_manager import recording_callback_manager
            
            print(f"2. RecordingCallbackManager Status:")
            status = recording_callback_manager.get_buffer_status()
            print(f"   - Initialized: {status.get('initialized', False)}")
            print(f"   - Total Guilds: {status.get('total_guilds', 0)}")
            print(f"   - Total Users: {status.get('total_users', 0)}")
            print(f"   - Total Chunks: {status.get('total_chunks', 0)}")
            
            # 3. Check active voice connections
            print(f"3. Voice Connections:")
            voice_count = 0
            for guild in bot.guilds:
                if guild.voice_client and guild.voice_client.is_connected():
                    voice_count += 1
                    channel = guild.voice_client.channel
                    print(f"   - Guild: {guild.name} ({guild.id})")
                    print(f"     * Channel: {channel.name} ({channel.id})")
                    print(f"     * Members: {len(channel.members)} ({[m.name for m in channel.members if not m.bot]})")
            
            if voice_count == 0:
                print("   - No active voice connections")
            
            # 4. Test specific guild configuration
            test_guild_id = 995627275074666568
            test_guild = bot.get_guild(test_guild_id)
            print(f"4. Test Guild ({test_guild_id}):")
            if test_guild:
                print(f"   - Name: {test_guild.name}")
                if test_guild.voice_client:
                    print(f"   - Connected: {test_guild.voice_client.is_connected()}")
                    if test_guild.voice_client.channel:
                        print(f"   - Channel: {test_guild.voice_client.channel.name}")
                        print(f"   - Members: {len(test_guild.voice_client.channel.members)}")
                else:
                    print("   - No voice connection")
            else:
                print("   - Guild not found")
            
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await bot.close()
    
    # Run bot briefly to check status
    try:
        await bot.start(os.getenv('DISCORD_TOKEN'))
    except Exception as e:
        print(f"Connection error (expected): {e}")

if __name__ == "__main__":
    asyncio.run(main())