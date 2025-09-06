#!/usr/bin/env python3
"""
リアルタイム音声データ收集テストスクリプト
SmoothAudioRelayとRecordingCallbackManagerの連携をテストする
"""

import asyncio
import logging
import time
from utils.recording_callback_manager import recording_callback_manager

async def main():
    print("RecordingCallbackManager Real-time Audio Data Collection Test Starting")
    print("=" * 60)
    
    # Logger setup
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    
    # RecordingCallbackManager initialization
    print("1. Initializing RecordingCallbackManager...")
    await recording_callback_manager.initialize()
    print("Initialization completed")
    
    # Guild registration
    guild_id = 995627275074666568  # Valworld
    print(f"2. Registering Guild {guild_id}...")
    success = await recording_callback_manager.register_guild(guild_id)
    print(f"Guild registration: {'Success' if success else 'Failed'}")
    
    # Initial state display
    status = recording_callback_manager.get_buffer_status()
    print(f"3. Initial buffer state:")
    print(f"   - Total guilds: {status['total_guilds']}")
    print(f"   - Total users: {status['total_users']}")
    print(f"   - Total chunks: {status['total_chunks']}")
    print(f"   - Buffer duration: {status['buffer_duration']} seconds")
    
    # 30-second real-time monitoring
    print("4. Starting 30-second real-time monitoring...")
    print("   If audio relay is active, audio data should accumulate.")
    print("   (Monitoring audio data transfer from SmoothAudioRelay)")
    print()
    
    for i in range(30):
        await asyncio.sleep(1)
        
        # バッファ状況を毎秒チェック
        current_status = recording_callback_manager.get_buffer_status()
        
        if current_status['total_chunks'] > 0:
            print(f"   [+] {i+1}s: Audio data detected! Chunks: {current_status['total_chunks']}")
            
            # Get latest audio data
            chunks = await recording_callback_manager.get_recent_audio(guild_id, 5.0)
            if chunks:
                print(f"      Audio chunks in last 5s: {len(chunks)}")
                for j, chunk in enumerate(chunks[-3:]):  # Show latest 3
                    print(f"         #{j+1}: User {chunk.user_id}, {len(chunk.data)} bytes, {chunk.duration:.1f}s")
                break
        else:
            if i % 5 == 4:  # Show status every 5 seconds
                print(f"   [-] {i+1}s: Waiting for audio data...")
    
    # Final results
    final_status = recording_callback_manager.get_buffer_status()
    print()
    print("5. Final Results:")
    print(f"   - Final chunks: {final_status['total_chunks']}")
    print(f"   - Users: {final_status['total_users']}")
    print(f"   - Guilds: {final_status['total_guilds']}")
    
    if final_status['total_chunks'] > 0:
        print("   SUCCESS: Real audio data collection successful!")
        
        # Real audio data replay test
        print("6. Real audio data replay test...")
        chunks = await recording_callback_manager.get_recent_audio(guild_id, 10.0)
        
        if chunks:
            print(f"   Replay audio chunks retrieved: {len(chunks)}")
            total_duration = sum(chunk.duration for chunk in chunks)
            total_size = sum(len(chunk.data) for chunk in chunks)
            print(f"   Total duration: {total_duration:.1f}s, Total size: {total_size:,} bytes")
            
            # Simulate actual WAV file generation
            combined_data = bytearray()
            for chunk in chunks:
                if chunk.data and len(chunk.data) > 44:
                    combined_data.extend(chunk.data)
            
            if combined_data:
                print(f"   Combined WAV data: {len(combined_data):,} bytes")
                print("   Real audio data ready for replay function!")
        else:
            print("   WARNING: No replay data found.")
    else:
        print("   FAILURE: Could not obtain audio data.")
        print("   Possible causes:")
        print("   - SmoothAudioRelay is not running")
        print("   - Audio relay session is not started")
        print("   - No actual audio in source channel")
    
    # Cleanup
    print("7. Cleanup...")
    await recording_callback_manager.shutdown()
    print("Test completed")
    
    print("=" * 60)
    print("RecordingCallbackManager Real-time Audio Data Collection Test Finished")

if __name__ == "__main__":
    asyncio.run(main())