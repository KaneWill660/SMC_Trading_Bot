"""
SMC Trading Bot — Main loop.
Checks for signals every 5 minutes during trading sessions.
"""

import asyncio
import time
from datetime import datetime, timezone

import MetaTrader5 as mt5
from loguru import logger

from connectors.mt5_connector import (
    connect, disconnect, get_account_balance, place_market_order
)
from notifications.telegram_notifier import send_signal, send_message
from risk.risk_manager import DailyRiskTracker
from strategy.entry_manager import check_for_signal, is_trading_session

# ── Config ────────────────────────────────────────────────────────────────────
SYMBOL       = "XAUUSDm"
RISK_PERCENT = 0.01   # 1% per trade
MAX_DAILY_LOSS_PCT = 0.03
CHECK_INTERVAL_SEC = 300  # 5 minutes


async def run_bot():
    logger.info("SMC Trading Bot starting...")

    if not connect():
        logger.error("Failed to connect to MT5 — exiting")
        return

    await send_message("🤖 <b>SMC Trading Bot started</b>\nMonitoring XAUUSD...")

    balance = get_account_balance()
    tracker = DailyRiskTracker(balance, MAX_DAILY_LOSS_PCT)
    last_reset_day = datetime.now(timezone.utc).date()

    try:
        while True:
            now = datetime.now(timezone.utc)

            # Reset daily tracker at start of new day
            if now.date() != last_reset_day:
                balance = get_account_balance()
                tracker.reset(balance)
                last_reset_day = now.date()
                logger.info(f"New trading day — balance: {balance:.2f}")

            # Circuit breaker check
            if tracker.circuit_breaker_tripped():
                logger.warning("Circuit breaker active — waiting until next day")
                await asyncio.sleep(CHECK_INTERVAL_SEC)
                continue

            # Only analyze during trading sessions
            if not is_trading_session():
                logger.debug("Outside session — sleeping")
                await asyncio.sleep(CHECK_INTERVAL_SEC)
                continue

            # Check for signal
            balance = get_account_balance()
            signal  = check_for_signal(balance, RISK_PERCENT)

            if signal:
                logger.info(f"Signal found: {signal['direction']} @ {signal['entry']}")

                # Send Telegram notification first
                await send_signal(signal)

                # Place order
                ticket = place_market_order(
                    direction=signal["direction"],
                    lot=signal["lot"],
                    sl=signal["sl"],
                    tp=signal["tp"],
                    comment="SMC_Bot",
                    symbol=SYMBOL,
                )

                if ticket:
                    logger.info(f"Order placed successfully | ticket={ticket}")
                    await send_message(
                        f"✅ <b>Order placed</b>\n"
                        f"Ticket: <code>{ticket}</code>\n"
                        f"{signal['direction']} {signal['lot']} lot @ {signal['entry']}"
                    )
                else:
                    logger.error("Order placement failed")
                    await send_message("❌ <b>Order placement failed</b> — check logs")

            await asyncio.sleep(CHECK_INTERVAL_SEC)

    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        await send_message("🛑 <b>SMC Trading Bot stopped</b>")
    finally:
        disconnect()


if __name__ == "__main__":
    asyncio.run(run_bot())
