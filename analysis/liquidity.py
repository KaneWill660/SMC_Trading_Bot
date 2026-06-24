"""
Liquidity analysis: equal highs/lows and sweep detection.
Equal highs/lows are clusters of stop losses that market makers target before reversing.
"""

import pandas as pd


def find_equal_levels(
    swing_points: list,
    tolerance: float = 0.5,
) -> list:
    """
    Find clusters of swing points at similar price levels (within tolerance).
    These are liquidity pools (stop loss clusters).
    Returns list of (price1, price2) tuples representing equal levels.
    tolerance: price distance in raw price units (e.g. 0.5 = 50 cents on XAUUSD)
    """
    levels = []
    for i in range(len(swing_points) - 1):
        for j in range(i + 1, len(swing_points)):
            diff = abs(swing_points[i][1] - swing_points[j][1])
            if diff <= tolerance:
                levels.append((swing_points[i], swing_points[j]))
    return levels


def detect_liquidity_sweep(
    df: pd.DataFrame,
    level: float,
    sweep_type: str,
    lookback: int = 3,
) -> bool:
    """
    Detect if price has swept a liquidity level and reversed.
    sweep_type: "high"  → price spiked above level then closed back below (sell-side sweep)
                "low"   → price spiked below level then closed back above (buy-side sweep)
    lookback: number of recent candles to check for the sweep.
    """
    recent = df.iloc[-lookback:]
    if sweep_type == "high":
        # Wick pierced above level but body (close) is back below
        swept = (recent["high"] > level).any()
        closed_back = float(df["close"].iloc[-1]) < level
        return swept and closed_back
    else:
        swept = (recent["low"] < level).any()
        closed_back = float(df["close"].iloc[-1]) > level
        return swept and closed_back


def get_buyside_liquidity(swing_highs: list) -> list:
    """Equal highs = buy-side liquidity (stops above highs)."""
    return find_equal_levels(swing_highs)


def get_sellside_liquidity(swing_lows: list) -> list:
    """Equal lows = sell-side liquidity (stops below lows)."""
    return find_equal_levels(swing_lows)
