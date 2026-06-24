import os
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")
BASE_URL  = f"https://api.telegram.org/bot{BOT_TOKEN}"


def format_signal_message(signal: dict) -> str:
    direction      = signal["direction"]
    direction_emoji = "🟢" if direction == "BUY" else "🔴"
    bias_arrow     = "↑" if signal["htf_bias"] == "bullish" else "↓"

    entry = signal["entry"]
    sl    = signal["sl"]
    tp    = signal["tp"]
    rr    = round(abs(tp - entry) / abs(entry - sl), 2)

    sl_pts = round(abs(entry - sl) * 10)
    tp_pts = round(abs(tp - entry) * 10)

    time_str = signal.get("time") or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    fvg_line = ""
    if signal.get("fvg_top") and signal.get("fvg_bottom"):
        fvg_line = f"\n  M15 FVG    : {signal['fvg_bottom']:.2f} – {signal['fvg_top']:.2f}"

    return (
        f"{direction_emoji} <b>SIGNAL: {direction} XAUUSD</b>\n"
        f"\n"
        f"📊 <b>Timeframe Analysis:</b>\n"
        f"  H4 Bias    : {signal['htf_bias'].upper()} {bias_arrow}\n"
        f"  H1 OB      : {signal['ob_bottom']:.2f} – {signal['ob_top']:.2f}"
        f"{fvg_line}\n"
        f"  M5 CHoCH   : ✅ Confirmed\n"
        f"\n"
        f"💰 <b>Trade Setup:</b>\n"
        f"  Entry      : ~{entry:.2f}\n"
        f"  Stop Loss  : {sl:.2f}  (-{sl_pts} pts)\n"
        f"  Take Profit: {tp:.2f}  (+{tp_pts} pts)\n"
        f"  RR Ratio   : 1 : {rr}\n"
        f"\n"
        f"🕐 {time_str}\n"
        f"📍 Session: {signal.get('session', 'N/A')}"
    )


async def send_signal(signal: dict) -> bool:
    """Send entry signal notification to Telegram. Returns True on success."""
    if not BOT_TOKEN or BOT_TOKEN == "your_token_here":
        logger.warning("Telegram BOT_TOKEN not configured — skipping notification")
        return False

    msg = format_signal_message(signal)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{BASE_URL}/sendMessage",
                json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"},
            )
        if resp.status_code != 200:
            logger.error(f"Telegram send failed ({resp.status_code}): {resp.text}")
            return False
        logger.info(f"Telegram signal sent: {signal['direction']} @ {signal['entry']}")
        return True
    except httpx.RequestError as e:
        logger.error(f"Telegram network error: {e}")
        return False


async def send_message(text: str) -> bool:
    """Send a plain text message to Telegram."""
    if not BOT_TOKEN or BOT_TOKEN == "your_token_here":
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{BASE_URL}/sendMessage",
                json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
            )
        return resp.status_code == 200
    except httpx.RequestError as e:
        logger.error(f"Telegram network error: {e}")
        return False
