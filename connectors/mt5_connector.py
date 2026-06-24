import os
from datetime import datetime
from typing import Optional

import MetaTrader5 as mt5
import pandas as pd
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

SYMBOL   = "XAUUSDm"
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


def get_ohlcv(timeframe: int, count: int, symbol: str = SYMBOL) -> Optional[pd.DataFrame]:
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
    symbol: str = SYMBOL,
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


def get_open_positions(symbol: str = SYMBOL) -> list:
    positions = mt5.positions_get(symbol=symbol)
    return list(positions) if positions else []


def close_position(ticket: int, symbol: str = SYMBOL) -> bool:
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
        logger.warning(f"Position {ticket} not found")
        return False
    pos = pos[0]
    direction  = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
    price      = mt5.symbol_info_tick(symbol).bid if pos.type == mt5.ORDER_TYPE_BUY else mt5.symbol_info_tick(symbol).ask

    request = {
        "action":    mt5.TRADE_ACTION_DEAL,
        "symbol":    symbol,
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
