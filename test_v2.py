#!/usr/bin/env python3
"""
yomiageBotEx v2 テスト起動スクリプト
"""

import asyncio
import sys
from pathlib import Path

# パス設定
sys.path.insert(0, str(Path(__file__).parent))

from bot import main

if __name__ == "__main__":
    print("=== yomiageBotEx v2 Test Launch ===")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped by user")
    except Exception as e:
        print(f"Bot error: {e}")
        import traceback
        traceback.print_exc()