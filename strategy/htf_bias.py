"""
Higher Timeframe Bias determination (H4 / D1).
Compares the last 2 confirmed swing highs and swing lows:
  Bullish : Higher High + Higher Low
  Bearish : Lower High  + Lower Low
  Ranging : mixed → do not trade
"""

import MetaTrader5 as mt5
import pandas as pd

from analysis.structure import find_swing_points
from connectors.mt5_connector import get_ohlcv

# How many candles to fetch for HTF analysis
HTF_CANDLE_COUNT = 200
SWING_N = 5  # lookback window on each side for swing detection


def get_bias(symbol: str = "XAUUSDc", timeframe: int = mt5.TIMEFRAME_H4) -> str:
    """
    Fetch HTF data and return "bullish", "bearish", or "ranging".
    """
    df = get_ohlcv(timeframe, HTF_CANDLE_COUNT, symbol)
    if df is None or len(df) < SWING_N * 2 + 1:
        return "ranging"
    return compute_bias_from_df(df)


def compute_bias_from_df(df: pd.DataFrame, n: int = SWING_N) -> str:
    """
    Compute bias directly from a DataFrame.
    Useful for backtesting (pass pre-loaded data).
    """
    swing_highs, swing_lows = find_swing_points(df, n=n)

    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return "ranging"

    sh1, sh2 = swing_highs[-2][1], swing_highs[-1][1]
    sl1, sl2 = swing_lows[-2][1],  swing_lows[-1][1]

    if sh2 > sh1 and sl2 > sl1:
        return "bullish"
    if sh2 < sh1 and sl2 < sl1:
        return "bearish"
    return "ranging"


def get_bias_with_levels(
    symbol: str = "XAUUSDc",
    timeframe: int = mt5.TIMEFRAME_H4,
) -> dict:
    """
    Extended version: returns bias + the swing levels used to determine it.
    Useful for logging and signal messages.
    """
    df = get_ohlcv(timeframe, HTF_CANDLE_COUNT, symbol)
    if df is None or len(df) < SWING_N * 2 + 1:
        return {"bias": "ranging"}

    swing_highs, swing_lows = find_swing_points(df, n=SWING_N)
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return {"bias": "ranging"}

    sh1, sh2 = swing_highs[-2][1], swing_highs[-1][1]
    sl1, sl2 = swing_lows[-2][1],  swing_lows[-1][1]

    if sh2 > sh1 and sl2 > sl1:
        bias = "bullish"
    elif sh2 < sh1 and sl2 < sl1:
        bias = "bearish"
    else:
        bias = "ranging"

    return {
        "bias":         bias,
        "last_sh":      sh2,
        "prev_sh":      sh1,
        "last_sl":      sl2,
        "prev_sl":      sl1,
        "swing_highs":  swing_highs,
        "swing_lows":   swing_lows,
    }
