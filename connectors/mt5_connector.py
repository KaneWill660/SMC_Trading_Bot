import os
from datetime import datetime, timezone, timedelta
from typing import Optional, List

import MetaTrader5 as mt5
import pandas as pd
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

DEVIATION = 20  # max price deviation in points for market orders


def connect() -> bool:
    if not mt5.initialize():
        logger.error(f"MT5 initialize failed: {mt5.last_error()}")
        return False
    login    = int(os.getenv("MT5_LOGIN", 0))
    password = os.getenv("MT5_PASSWORD", "")
    server   = os.getenv("MT5_SERVER", "")
    if login and password and server:
        ok = mt5.login(login, password=password, server=server)
        if not ok:
            logger.error(f"MT5 login failed: {mt5.last_error()}")
            return False
    info = mt5.account_info()
    logger.info(f"MT5 connected | Account: {info.login} | Balance: {info.balance}")
    return True


def disconnect():
    mt5.shutdown()
    logger.info("MT5 disconnected")


def get_ohlcv(timeframe: int, count: int, symbol: str = "XAUUSDc") -> Optional[pd.DataFrame]:
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
    if rates is None or len(rates) == 0:
        logger.error(f"Failed to get OHLCV {symbol} tf={timeframe}: {mt5.last_error()}")
        return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df.rename(columns={"tick_volume": "volume"})[
        ["time", "open", "high", "low", "close", "volume"]
    ].reset_index(drop=True)
    return df


def get_account_balance() -> float:
    info = mt5.account_info()
    return info.balance if info else 0.0


def place_market_order(
    direction: str,
    lot: float,
    sl: float,
    tp: float,
    comment: str = "SMC_Bot",
    symbol: str = "XAUUSDc",
) -> Optional[int]:
    """
    Place a market order.
    direction: "BUY" or "SELL"
    Returns order ticket on success, None on failure.
    """
    order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
    price      = mt5.symbol_info_tick(symbol).ask if direction == "BUY" else mt5.symbol_info_tick(symbol).bid

    request = {
        "action":    mt5.TRADE_ACTION_DEAL,
        "symbol":    symbol,
        "volume":    lot,
        "type":      order_type,
        "price":     price,
        "sl":        sl,
        "tp":        tp,
        "deviation": DEVIATION,
        "magic":     20260624,
        "comment":   comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        logger.error(f"Order failed: retcode={result.retcode} | {result.comment}")
        return None

    logger.info(f"Order placed: {direction} {lot} {symbol} @ {price} | ticket={result.order}")
    return result.order


def get_open_positions(symbol: str = None) -> list:
    positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
    return list(positions) if positions else []


def get_all_positions() -> list:
    """Return all open positions across all symbols."""
    positions = mt5.positions_get()
    return list(positions) if positions else []


def get_pending_orders() -> list:
    """Return all pending orders (limit/stop orders not yet triggered)."""
    orders = mt5.orders_get()
    return list(orders) if orders else []


def get_deal_history(days: int = 1) -> list:
    """Return closed deals from the last N days."""
    now   = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    deals = mt5.history_deals_get(start, now)
    if deals is None:
        return []
    return [d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT]


def move_sl_to_entry(ticket: int) -> bool:
    """Move SL to entry price (breakeven) for a position."""
    positions = mt5.positions_get(ticket=ticket)
    if not positions:
        logger.warning(f"Position {ticket} not found for breakeven")
        return False
    pos = positions[0]
    if pos.sl == pos.price_open:
        return True  # already at breakeven
    request = {
        "action":   mt5.TRADE_ACTION_SLTP,
        "position": ticket,
        "sl":       pos.price_open,
        "tp":       pos.tp,
    }
    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        logger.error(f"Breakeven failed ticket={ticket}: {result.retcode} {result.comment}")
        return False
    logger.info(f"Breakeven set for ticket={ticket} @ {pos.price_open}")
    return True


def close_position(ticket: int, symbol: str = None) -> bool:
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
        logger.warning(f"Position {ticket} not found")
        return False
    pos = pos[0]
    sym        = symbol or pos.symbol
    direction  = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
    price      = mt5.symbol_info_tick(sym).bid if pos.type == mt5.ORDER_TYPE_BUY else mt5.symbol_info_tick(sym).ask

    request = {
        "action":    mt5.TRADE_ACTION_DEAL,
        "symbol":    sym,
        "volume":    pos.volume,
        "type":      direction,
        "position":  ticket,
        "price":     price,
        "deviation": DEVIATION,
        "magic":     20260624,
        "comment":   "SMC_Bot_Close",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        logger.error(f"Close failed: {result.retcode} | {result.comment}")
        return False

    logger.info(f"Position {ticket} closed")
    return True
