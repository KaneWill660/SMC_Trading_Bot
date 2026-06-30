"""
Telegram command listener — long-polls getUpdates and dispatches bot commands.
Runs as a separate asyncio task alongside the main trading loop.

Commands:
  /balance        — Account balance & equity
  /status         — Open positions with current P&L
  /report N       — Summary of last N days
  /stop           — Pause signal scanning
  /start          — Resume signal scanning
  /be             — Move SL to entry for all profitable positions
  /closeall       — Close all open positions
  /risk 0.5       — Set risk % per trade (e.g. 0.5 = 0.5%)
  /pause 30m      — Pause for N minutes then auto-resume (m=minutes, h=hours)
  /help           — List commands
"""

import asyncio
import os
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv
from loguru import logger

from connectors.mt5_connector import (
    get_account_balance,
    get_all_positions,
    get_pending_orders,
    get_deal_history,
    move_sl_to_entry,
    close_position,
)

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
BASE_URL  = f"https://api.telegram.org/bot{BOT_TOKEN}"


async def _api(client: httpx.AsyncClient, method: str, **kwargs) -> dict:
    try:
        resp = await client.post(f"{BASE_URL}/{method}", json=kwargs, timeout=10)
        return resp.json()
    except httpx.TimeoutException:
        logger.debug(f"Telegram timeout ({method}) — retrying")
        return {}
    except Exception as e:
        logger.error(f"Telegram API error ({method}): {e}")
        return {}


async def _reply(chat_id: int, text: str):
    async with httpx.AsyncClient() as client:
        await _api(client, "sendMessage", chat_id=chat_id, text=text, parse_mode="HTML")


# ── Command handlers ──────────────────────────────────────────────────────────

async def cmd_balance(chat_id: int):
    info = None
    try:
        import MetaTrader5 as mt5
        info = mt5.account_info()
    except Exception:
        pass

    if info:
        msg = (
            f"💰 <b>Account Info</b>\n"
            f"  Balance  : <b>{info.balance:.2f} {info.currency}</b>\n"
            f"  Equity   : {info.equity:.2f} {info.currency}\n"
            f"  Margin   : {info.margin:.2f}\n"
            f"  Free Margin: {info.margin_free:.2f}\n"
            f"  Profit   : {info.profit:+.2f}"
        )
    else:
        msg = "❌ Không lấy được thông tin tài khoản"
    await _reply(chat_id, msg)


async def cmd_status(chat_id: int):
    positions = get_all_positions()

    if not positions:
        await _reply(chat_id, "📭 Không có lệnh nào đang chạy.")
        return

    lines = ["📊 <b>Lệnh đang chạy:</b>\n"]
    for p in positions:
        direction = "BUY 🟢" if p.type == 0 else "SELL 🔴"
        pnl_sign  = "+" if p.profit >= 0 else ""
        lines.append(
            f"• <b>{p.symbol}</b> {direction}\n"
            f"  Lot: {p.volume} | Entry: {p.price_open:.2f}\n"
            f"  SL: {p.sl:.2f} | TP: {p.tp:.2f}\n"
            f"  P&L: <b>{pnl_sign}{p.profit:.2f} USD</b>\n"
            f"  Ticket: <code>{p.ticket}</code>"
        )

    await _reply(chat_id, "\n".join(lines))


async def cmd_pending(chat_id: int):
    pending = get_pending_orders()

    if not pending:
        await _reply(chat_id, "📭 Không có lệnh pending nào.")
        return

    order_type_map = {
        2: "BUY LIMIT", 3: "SELL LIMIT",
        4: "BUY STOP",  5: "SELL STOP",
        6: "BUY STOP LIMIT", 7: "SELL STOP LIMIT",
    }
    lines = ["⏳ <b>Lệnh đang chờ (Pending):</b>\n"]
    for o in pending:
        order_type = order_type_map.get(o.type, f"TYPE_{o.type}")
        lines.append(
            f"• <b>{o.symbol}</b> {order_type}\n"
            f"  Lot: {o.volume_current} | Price: {o.price_open:.2f}\n"
            f"  SL: {o.sl:.2f} | TP: {o.tp:.2f}\n"
            f"  Ticket: <code>{o.ticket}</code>"
        )

    await _reply(chat_id, "\n".join(lines))


async def cmd_report(chat_id: int, text: str):
    parts = text.strip().split()
    days = 1
    if len(parts) >= 2:
        try:
            days = int(parts[1])
        except ValueError:
            pass

    deals = get_deal_history(days)
    if not deals:
        await _reply(chat_id, f"📭 Không có lệnh nào trong {days} ngày qua.")
        return

    wins   = [d for d in deals if d.profit > 0]
    losses = [d for d in deals if d.profit < 0]
    total  = sum(d.profit for d in deals)

    lines = [
        f"📈 <b>Report {days} ngày gần nhất</b>\n",
        f"  Tổng lệnh : {len(deals)}",
        f"  Thắng     : {len(wins)} (+{sum(d.profit for d in wins):.2f} USD)",
        f"  Thua      : {len(losses)} ({sum(d.profit for d in losses):.2f} USD)",
        f"  NET P&L   : <b>{total:+.2f} USD</b>",
        f"  Winrate   : {100*len(wins)/len(deals):.1f}%" if deals else "",
    ]
    await _reply(chat_id, "\n".join(lines))


async def cmd_breakeven(chat_id: int):
    positions = get_all_positions()
    if not positions:
        await _reply(chat_id, "📭 Không có lệnh nào đang mở.")
        return

    count = 0
    for p in positions:
        if p.profit > 0:
            if move_sl_to_entry(p.ticket):
                count += 1

    if count:
        await _reply(chat_id, f"✅ Đã BE <b>{count}</b> lệnh có lãi (tất cả lệnh, kể cả lệnh thủ công).")
    else:
        await _reply(chat_id, "⚠️ Không có lệnh nào đang có lãi để chuyển breakeven.")


async def cmd_closeall(chat_id: int):
    positions = get_all_positions()
    if not positions:
        await _reply(chat_id, "📭 Không có lệnh nào để đóng.")
        return

    count = 0
    for p in positions:
        if close_position(p.ticket):
            count += 1

    await _reply(chat_id, f"🛑 Đã đóng <b>{count}/{len(positions)}</b> lệnh.")


async def cmd_help(chat_id: int):
    msg = (
        "🤖 <b>SMC Bot — Danh sách lệnh:</b>\n\n"
        "/balance — Số dư tài khoản\n"
        "/status — Lệnh đang chạy & P&L\n"
        "/pending — Lệnh đang chờ (Pending)\n"
        "/report N — Tổng kết N ngày gần nhất\n"
        "/stop — Dừng quét tín hiệu\n"
        "/start — Tiếp tục quét tín hiệu\n"
        "/be — Chuyển SL về entry (breakeven)\n"
        "/closeall — Đóng tất cả lệnh\n"
        "/risk 0.5 — Đổi risk thành 0.5%/lệnh\n"
        "/pause 30m — Tạm dừng 30 phút (dùng h cho giờ)\n"
        "/help — Xem danh sách lệnh"
    )
    await _reply(chat_id, msg)


# ── Main polling loop ─────────────────────────────────────────────────────────

async def poll_commands(bot_state: dict):
    """
    Long-poll Telegram getUpdates and dispatch commands.
    bot_state keys used: paused (bool), risk_percent (float), pause_until (datetime|None)
    """
    if not BOT_TOKEN or BOT_TOKEN == "your_token_here":
        logger.warning("Telegram token not set — command listener disabled")
        return

    offset = 0
    logger.info("Telegram command listener started")

    async with httpx.AsyncClient(timeout=45) as client:
        while True:
            try:
                data = await _api(
                    client, "getUpdates",
                    offset=offset, timeout=30, allowed_updates=["message"]
                )
                updates = data.get("result", [])
            except Exception as e:
                logger.warning(f"getUpdates error: {e}")
                await asyncio.sleep(5)
                continue

            for update in updates:
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                chat_id = msg.get("chat", {}).get("id")
                text    = (msg.get("text") or "").strip()

                if not text or not chat_id:
                    continue

                # Security: only respond to configured CHAT_ID
                if str(chat_id) != str(CHAT_ID):
                    continue

                logger.info(f"Telegram command: {text}")

                if text.startswith("/balance"):
                    await cmd_balance(chat_id)

                elif text.startswith("/status"):
                    await cmd_status(chat_id)

                elif text.startswith("/pending"):
                    await cmd_pending(chat_id)

                elif text.startswith("/report"):
                    await cmd_report(chat_id, text)

                elif text.startswith("/stop"):
                    bot_state["paused"] = True
                    await _reply(chat_id, "⏸ Bot đã <b>dừng quét tín hiệu</b>. Gõ /start để tiếp tục.")

                elif text.startswith("/start"):
                    bot_state["paused"] = False
                    bot_state["pause_until"] = None
                    await _reply(chat_id, "▶️ Bot đã <b>tiếp tục quét tín hiệu</b>.")

                elif text.startswith("/be"):
                    await cmd_breakeven(chat_id)

                elif text.startswith("/closeall"):
                    await cmd_closeall(chat_id)

                elif text.startswith("/risk"):
                    parts = text.split()
                    if len(parts) >= 2:
                        try:
                            new_risk = float(parts[1]) / 100
                            old_risk = bot_state.get("risk_percent", 0.01)
                            bot_state["risk_percent"] = new_risk
                            await _reply(
                                chat_id,
                                f"✅ Risk/trade đã đổi từ <b>{old_risk*100:.2f}%</b> → <b>{new_risk*100:.2f}%</b>"
                            )
                        except ValueError:
                            await _reply(chat_id, "❌ Dùng: /risk 0.5 (nhập số %)")
                    else:
                        current = bot_state.get("risk_percent", 0.01) * 100
                        await _reply(chat_id, f"ℹ️ Risk hiện tại: <b>{current:.2f}%</b>/lệnh")

                elif text.startswith("/pause"):
                    parts = text.split()
                    if len(parts) >= 2:
                        raw = parts[1].lower()
                        try:
                            if raw.endswith("h"):
                                minutes = int(raw[:-1]) * 60
                            elif raw.endswith("m"):
                                minutes = int(raw[:-1])
                            else:
                                minutes = int(raw)

                            from datetime import timedelta
                            resume_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)
                            bot_state["paused"] = True
                            bot_state["pause_until"] = resume_at
                            await _reply(
                                chat_id,
                                f"⏸ Tạm dừng <b>{minutes} phút</b> — resume lúc {resume_at.strftime('%H:%M UTC')}"
                            )
                        except ValueError:
                            await _reply(chat_id, "❌ Dùng: /pause 30m hoặc /pause 2h")
                    else:
                        await _reply(chat_id, "❌ Dùng: /pause 30m hoặc /pause 2h")

                elif text.startswith("/help"):
                    await cmd_help(chat_id)

            await asyncio.sleep(2)
