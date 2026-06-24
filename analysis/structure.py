"""
Swing point detection, BOS, and CHoCH.
All functions accept a pandas DataFrame with columns: open, high, low, close, time.
"""

from typing import Optional
import pandas as pd


def find_swing_points(df: pd.DataFrame, n: int = 5) -> "tuple[list, list]":
    """
    Find swing highs and lows using a rolling window of n candles on each side.
    Returns (swing_highs, swing_lows) where each item is (index, price).
    Requires at least 2*n+1 candles.
    """
    highs, lows = [], []
    for i in range(n, len(df) - n):
        window_high = df["high"].iloc[i - n: i + n + 1]
        window_low  = df["low"].iloc[i - n: i + n + 1]
        if df["high"].iloc[i] == window_high.max():
            highs.append((i, float(df["high"].iloc[i])))
        if df["low"].iloc[i] == window_low.min():
            lows.append((i, float(df["low"].iloc[i])))
    return highs, lows


def detect_bos(
    df: pd.DataFrame,
    swing_highs: list,
    swing_lows: list,
    direction: str,
) -> bool:
    """
    Check if the latest closed candle breaks the most recent swing point
    in the given direction, confirming trend continuation.
    direction: "bullish" → price breaks above last swing high
               "bearish" → price breaks below last swing low
    """
    if direction == "bullish" and swing_highs:
        last_sh = swing_highs[-1][1]
        return float(df["close"].iloc[-1]) > last_sh
    if direction == "bearish" and swing_lows:
        last_sl = swing_lows[-1][1]
        return float(df["close"].iloc[-1]) < last_sl
    return False


def detect_choch(
    df: pd.DataFrame,
    swing_highs: list,
    swing_lows: list,
    direction: str,
) -> bool:
    """
    Detect a Change of Character — price breaks the opposite structure,
    signalling a potential reversal. Used on M5 to confirm entry.
    direction: "bullish" → in a local downtrend, price breaks above last local swing high
               "bearish" → in a local uptrend, price breaks below last local swing low
    """
    if direction == "bullish" and swing_highs:
        last_sh = swing_highs[-1][1]
        return float(df["close"].iloc[-1]) > last_sh
    if direction == "bearish" and swing_lows:
        last_sl = swing_lows[-1][1]
        return float(df["close"].iloc[-1]) < last_sl
    return False


def get_last_swing_high(swing_highs: list) -> Optional[float]:
    return swing_highs[-1][1] if swing_highs else None


def get_last_swing_low(swing_lows: list) -> Optional[float]:
    return swing_lows[-1][1] if swing_lows else None
