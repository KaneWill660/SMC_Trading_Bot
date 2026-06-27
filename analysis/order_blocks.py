"""
Order Block detection.
Bullish OB = last bearish candle before a bullish impulse that broke a swing high.
Bearish OB = last bullish candle before a bearish impulse that broke a swing low.
"""

import pandas as pd


def find_bullish_obs(df: pd.DataFrame, swing_highs: list, lookback: int = 20) -> list:
    """
    For each confirmed swing high, scan backward and collect ALL consecutive
    bearish candles immediately before the impulse — merge them into one OB zone.
    OB top = open of first bearish candle, OB bottom = close of last bearish candle.
    """
    obs = []
    for sh_idx, sh_price in swing_highs:
        start = max(0, sh_idx - lookback)
        window = df.iloc[start:sh_idx]
        # Collect consecutive bearish candles from the right
        seq = []
        for i in range(len(window) - 1, -1, -1):
            row = window.iloc[i]
            if row["close"] < row["open"]:
                seq.append(start + i)
            else:
                break
        if not seq:
            continue
        seq_sorted = sorted(seq)
        first_idx = seq_sorted[0]
        last_idx  = seq_sorted[-1]
        obs.append({
            "index":   last_idx,
            "time":    df.iloc[last_idx]["time"],
            "top":     float(df.iloc[first_idx]["open"]),
            "bottom":  float(df.iloc[last_idx]["close"]),
            "type":    "bullish",
            "sh_price": sh_price,
        })
    return obs


def find_bearish_obs(df: pd.DataFrame, swing_lows: list, lookback: int = 20) -> list:
    """
    For each confirmed swing low, scan backward and collect ALL consecutive
    bullish candles immediately before the impulse — merge them into one OB zone.
    OB top = close of last bullish candle, OB bottom = open of first bullish candle.
    """
    obs = []
    for sl_idx, sl_price in swing_lows:
        start = max(0, sl_idx - lookback)
        window = df.iloc[start:sl_idx]
        seq = []
        for i in range(len(window) - 1, -1, -1):
            row = window.iloc[i]
            if row["close"] > row["open"]:
                seq.append(start + i)
            else:
                break
        if not seq:
            continue
        seq_sorted = sorted(seq)
        first_idx = seq_sorted[0]
        last_idx  = seq_sorted[-1]
        obs.append({
            "index":   last_idx,
            "time":    df.iloc[last_idx]["time"],
            "top":     float(df.iloc[last_idx]["close"]),
            "bottom":  float(df.iloc[first_idx]["open"]),
            "type":    "bearish",
            "sl_price": sl_price,
        })
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
