"""
SMC Trading Bot — Main loop.
Checks for signals every 5 minutes during trading sessions.
Supports multiple symbols configured via .env.
"""

import asyncio
import os
from datetime import datetime, timezone

import MetaTrader5 as mt5
from dotenv import load_dotenv
from loguru import logger

from connectors.mt5_connector import (
    connect, disconnect, get_account_balance, get_all_positions, place_market_order
)
from notifications.telegram_commands import poll_commands
from notifications.telegram_notifier import send_signal, send_message
from risk.risk_manager import DailyRiskTracker
from strategy.entry_manager import check_for_signal, is_trading_session

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
SYMBOLS            = [s.strip() for s in os.getenv("SYMBOLS", "XAUUSDc").split(",") if s.strip()]
MAX_DAILY_LOSS_PCT = 0.03
CHECK_INTERVAL_SEC = 300  # 5 minutes

def _load_symbol_lots() -> dict:
    """Read per-symbol fixed lot sizes from .env. Returns {} if not set."""
    lots = {}
    for sym in SYMBOLS:
        val = os.getenv(f"SYMBOL_LOT_{sym}", "").strip()
        if val:
            try:
                lots[sym] = float(val)
            except ValueError:
                logger.warning(f"Invalid SYMBOL_LOT_{sym}={val!r} — will use risk% instead")
    return lots

SYMBOL_LOTS = _load_symbol_lots()


async def trading_loop(bot_state: dict):
    balance = get_account_balance()
    tracker = DailyRiskTracker(balance, MAX_DAILY_LOSS_PCT)
    last_reset_day = datetime.now(timezone.utc).date()
    open_tickets   = {}  # {ticket: {"symbol": str, "balance_before": float}}

    while True:
        now = datetime.now(timezone.utc)

        # Reset daily tracker at start of new day
        if now.date() != last_reset_day:
            balance = get_account_balance()
            tracker.reset(balance)
            last_reset_day = now.date()
            logger.info(f"New trading day — balance: {balance:.2f}")

        # Auto-resume after /pause N expires
        pause_until = bot_state.get("pause_until")
        if pause_until and now >= pause_until:
            bot_state["paused"] = False
            bot_state["pause_until"] = None
            await send_message("▶️ Hết thời gian tạm dừng — Bot tiếp tục quét tín hiệu.")

        # Kiểm tra lệnh đã đóng → record PnL
        current_open = {p.ticket for p in get_all_positions()}
        for ticket, info in list(open_tickets.items()):
            if ticket not in current_open:
                bal_after = get_account_balance()
                pnl = bal_after - info["balance_before"]
                tracker.record_trade(pnl)
                if pnl < 0:
                    await send_message(
                        f"❌ <b>Lệnh đóng — THUA</b>\n"
                        f"Symbol: {info['symbol']} | Ticket: <code>{ticket}</code>\n"
                        f"PnL: {pnl:+.2f} USD\n"
                        f"⛔ Dừng trade hôm nay."
                    )
                else:
                    await send_message(
                        f"✅ <b>Lệnh đóng — THẮNG</b>\n"
                        f"Symbol: {info['symbol']} | Ticket: <code>{ticket}</code>\n"
                        f"PnL: {pnl:+.2f} USD"
                    )
                del open_tickets[ticket]
                balance = get_account_balance()

        # Circuit breaker check
        if tracker.circuit_breaker_tripped():
            logger.warning("Circuit breaker active — waiting until next day")
            await asyncio.sleep(CHECK_INTERVAL_SEC)
            continue

        # Paused by /stop or /pause command
        if bot_state.get("paused"):
            logger.debug("Bot paused — skipping signal scan")
            await asyncio.sleep(CHECK_INTERVAL_SEC)
            continue

        # Only analyze during trading sessions
        if not is_trading_session():
            logger.debug("Outside session — sleeping")
            await asyncio.sleep(CHECK_INTERVAL_SEC)
            continue

        # Scan each symbol
        balance = get_account_balance()
        risk_percent = bot_state.get("risk_percent", 0.01)

        for symbol in SYMBOLS:
            fixed_lot = SYMBOL_LOTS.get(symbol)
            signal = check_for_signal(symbol, balance, risk_percent, fixed_lot)

            if signal:
                logger.info(f"Signal found: {symbol} {signal['direction']} @ {signal['entry']}")

                await send_signal(signal)

                ticket = place_market_order(
                    direction=signal["direction"],
                    lot=signal["lot"],
                    sl=signal["sl"],
                    tp=signal["tp"],
                    comment="SMC_Bot",
                    symbol=symbol,
                )

                if ticket:
                    open_tickets[ticket] = {"symbol": symbol, "balance_before": balance}
                    logger.info(f"Order placed | ticket={ticket} | {symbol}")
                    await send_message(
                        f"✅ <b>Order placed</b> — {symbol}\n"
                        f"Ticket: <code>{ticket}</code>\n"
                        f"{signal['direction']} {signal['lot']} lot @ {signal['entry']}"
                    )
                else:
                    logger.error(f"Order placement failed for {symbol}")
                    await send_message(f"❌ <b>Order failed</b> — {symbol}. Check logs.")

        await asyncio.sleep(CHECK_INTERVAL_SEC)


async def run_bot():
    logger.info("SMC Trading Bot starting...")
    logger.info(f"Symbols: {SYMBOLS}")
    logger.info(f"Fixed lots: {SYMBOL_LOTS if SYMBOL_LOTS else 'using risk% calculation'}")

    if not connect():
        logger.error("Failed to connect to MT5 — exiting")
        return

    await send_message(
        f"🤖 <b>SMC Trading Bot started</b>\n"
        f"Symbols: {', '.join(SYMBOLS)}\n"
        f"Gõ /help để xem danh sách lệnh."
    )

    bot_state = {
        "paused":       False,
        "pause_until":  None,
        "risk_percent": float(os.getenv("RISK_PERCENT", "0.01")),
    }

    try:
        await asyncio.gather(
            trading_loop(bot_state),
            poll_commands(bot_state),
        )
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        await send_message("🛑 <b>SMC Trading Bot stopped</b>")
    finally:
        disconnect()


if __name__ == "__main__":
    asyncio.run(run_bot())
