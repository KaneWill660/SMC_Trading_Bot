"""
Order Block detection.
Bullish OB = last bearish candle before a bullish impulse that broke a swing high.
Bearish OB = last bullish candle before a bearish impulse that broke a swing low.
"""

import pandas as pd


def find_bullish_obs(df: pd.DataFrame, swing_highs: list, lookback: int = 20) -> list:
    """
    For each confirmed swing high, scan backward up to `lookback` candles
    and find the last bearish candle — that is the bullish OB.
    Returns list of OB dicts sorted oldest → newest.
    An OB is invalidated (mitigated) when price closes below its bottom.
    """
    obs = []
    for sh_idx, sh_price in swing_highs:
        start = max(0, sh_idx - lookback)
        window = df.iloc[start:sh_idx]
        for i in range(len(window) - 1, -1, -1):
            row = window.iloc[i]
            if row["close"] < row["open"]:  # bearish candle
                obs.append({
                    "index":   start + i,
                    "time":    row["time"],
                    "top":     float(row["open"]),
                    "bottom":  float(row["close"]),
                    "type":    "bullish",
                    "sh_price": sh_price,
                })
                break
    return obs


def find_bearish_obs(df: pd.DataFrame, swing_lows: list, lookback: int = 20) -> list:
    """
    For each confirmed swing low, scan backward up to `lookback` candles
    and find the last bullish candle — that is the bearish OB.
    """
    obs = []
    for sl_idx, sl_price in swing_lows:
        start = max(0, sl_idx - lookback)
        window = df.iloc[start:sl_idx]
        for i in range(len(window) - 1, -1, -1):
            row = window.iloc[i]
            if row["close"] > row["open"]:  # bullish candle
                obs.append({
                    "index":   start + i,
                    "time":    row["time"],
                    "top":     float(row["close"]),
                    "bottom":  float(row["open"]),
                    "type":    "bearish",
                    "sl_price": sl_price,
                })
                break
    return obs


def filter_valid_obs(obs: list, current_price: float, ob_type: str) -> list:
    """
    Remove mitigated OBs:
    - Bullish OB is mitigated if current price has closed below its bottom.
    - Bearish OB is mitigated if current price has closed above its top.
    Returns only valid (unmitigated) OBs below/above current price.
    """
    valid = []
    for ob in obs:
        if ob_type == "bullish":
            # OB must be below current price and not mitigated
            if current_price > ob["top"] and current_price > ob["bottom"]:
                valid.append(ob)
        else:
            # OB must be above current price and not mitigated
            if current_price < ob["bottom"] and current_price < ob["top"]:
                valid.append(ob)
    return valid


def price_in_ob(price: float, ob: dict, buffer: float = 0.5) -> bool:
    """Check if price is inside the OB zone (with optional buffer in price units)."""
    return ob["bottom"] - buffer <= price <= ob["top"] + buffer


def get_nearest_ob(obs: list, current_price: float, ob_type: str) -> "dict | None":
    """Return the OB closest to current price."""
    valid = filter_valid_obs(obs, current_price, ob_type)
    if not valid:
        return None
    if ob_type == "bullish":
        # nearest = highest top among OBs below price
        return max(valid, key=lambda x: x["top"])
    else:
        # nearest = lowest bottom among OBs above price
        return min(valid, key=lambda x: x["bottom"])
