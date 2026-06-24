"""
Quick test: send a fake signal to Telegram to verify bot token and format.
Run: python -m tests.test_telegram
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from notifications.telegram_notifier import send_signal, send_message


FAKE_SIGNAL = {
    "direction":  "BUY",
    "htf_bias":   "bullish",
    "ob_top":     2320.10,
    "ob_bottom":  2318.50,
    "fvg_top":    2319.80,
    "fvg_bottom": 2319.00,
    "entry":      2319.50,
    "sl":         2317.80,
    "tp":         2323.20,
    "lot":        0.05,
    "time":       "2026-06-24 14:32 UTC",
    "session":    "London/NY Overlap",
}


async def main():
    print("Sending test signal to Telegram...")
    ok = await send_signal(FAKE_SIGNAL)
    if ok:
        print("✅ Signal sent successfully — check your Telegram!")
    else:
        print("❌ Failed — check BOT_TOKEN and CHAT_ID in .env")

    print("Sending plain text test...")
    ok2 = await send_message("🤖 <b>SMC Trading Bot</b> is online and ready.")
    if ok2:
        print("✅ Plain message sent successfully!")


if __name__ == "__main__":
    asyncio.run(main())
