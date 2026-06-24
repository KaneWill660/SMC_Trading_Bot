"""
Fair Value Gap (FVG) detection.
A FVG is a 3-candle pattern where there is a gap between candle[i-2] and candle[i].
Price tends to return to fill these gaps before continuing.
"""

import pandas as pd


def find_fvgs(df: pd.DataFrame) -> list:
    """
    Scan all candles and return all FVGs found.
    Bullish FVG : low[i] > high[i-2]  → gap above candle i-2
    Bearish FVG : high[i] < low[i-2]  → gap below candle i-2
    """
    fvgs = []
    for i in range(2, len(df)):
        low_i      = float(df["low"].iloc[i])
        high_i     = float(df["high"].iloc[i])
        low_i2     = float(df["low"].iloc[i - 2])
        high_i2    = float(df["high"].iloc[i - 2])

        if low_i > high_i2:
            fvgs.append({
                "type":    "bullish",
                "top":     low_i,
                "bottom":  high_i2,
                "index":   i,
                "time":    df["time"].iloc[i],
                "filled":  False,
            })

        elif high_i < low_i2:
            fvgs.append({
                "type":    "bearish",
                "top":     low_i2,
                "bottom":  high_i,
                "index":   i,
                "time":    df["time"].iloc[i],
                "filled":  False,
            })

    return fvgs


def filter_unfilled_fvgs(fvgs: list, df: pd.DataFrame) -> list:
    """
    Mark FVGs as filled if subsequent price action has entered the gap zone.
    Returns only unfilled FVGs.
    """
    result = []
    for fvg in fvgs:
        idx = fvg["index"]
        if idx + 1 >= len(df):
            result.append(fvg)
            continue

        # Check candles after the FVG formed
        subsequent = df.iloc[idx + 1:]
        if fvg["type"] == "bullish":
            filled = (subsequent["low"] <= fvg["top"]).any()
        else:
            filled = (subsequent["high"] >= fvg["bottom"]).any()

        if not filled:
            result.append(fvg)

    return result


def get_fvgs_in_ob(fvgs: list, ob: dict) -> list:
    """Return FVGs that overlap with an Order Block zone."""
    result = []
    for fvg in fvgs:
        if fvg["type"] != ob["type"]:
            continue
        # Check for overlap between FVG and OB
        overlap = fvg["bottom"] < ob["top"] and fvg["top"] > ob["bottom"]
        if overlap:
            result.append(fvg)
    return result


def price_in_fvg(price: float, fvg: dict) -> bool:
    return fvg["bottom"] <= price <= fvg["top"]
