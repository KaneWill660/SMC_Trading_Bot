"""
Entry Manager — combines all timeframes to produce a trade signal.

Flow:
  H4 bias (bullish/bearish)
    → H1 Liquidity Sweep (EQH/EQL swept — Liquidity Trap filter)
      → H1 Order Block + BOS confirmation
        → M15 FVG within OB (optional but preferred)
          → M5 CHoCH confirmation
            → Signal dict returned
"""

import os
from datetime import datetime, timezone

import MetaTrader5 as mt5
import pandas as pd
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

from analysis.fvg import find_fvgs, filter_unfilled_fvgs, get_fvgs_in_ob, price_in_fvg
from analysis.liquidity import get_buyside_liquidity, get_sellside_liquidity, detect_liquidity_sweep
from analysis.order_blocks import find_bullish_obs, find_bearish_obs, get_nearest_ob
from analysis.structure import find_swing_points, detect_bos, detect_mss, detect_choch
from connectors.mt5_connector import get_ohlcv
from risk.risk_manager import calculate_lot_size, calculate_tp
from strategy.htf_bias import get_bias_with_levels

# Candle counts per timeframe
COUNT_H1  = 100
COUNT_M15 = 100
COUNT_M5  = 50

# OB parameters
MIN_RR = 3.0

def _get_sl_buffer(symbol: str) -> float:
    val = os.getenv(f"SYMBOL_SL_BUFFER_{symbol}", "").strip()
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.50  # default fallback


def get_current_session() -> str:
    hour = datetime.now(timezone.utc).hour
    if 8 <= hour < 12:
        return "London"
    if 12 <= hour < 17:
        return "London/NY Overlap"
    if 17 <= hour < 21:
        return "New York"
    return "Off-session"


def is_trading_session() -> bool:
    """Trade all hours while market is open (XAUUSDc trades 24/5, Mon–Fri)."""
    now = datetime.now(timezone.utc)
    if now.weekday() == 5:          # Saturday — đóng cửa cả ngày
        return False
    if now.weekday() == 6 and now.hour < 21:  # Sunday trước 21:00 UTC
        return False
    return True


def check_for_signal(
    symbol: str,
    balance: float,
    risk_percent: float = 0.01,
    fixed_lot: "float | None" = None,
) -> "dict | None":
    """
    Run the full multi-timeframe analysis for the given symbol.
    fixed_lot: if set, use this lot size instead of calculating from risk_percent.
    Returns a signal dict if conditions are met, or None.
    """
    if not is_trading_session():
        logger.debug("Outside trading session — skipping")
        return None

    # ── Step 1: HTF Bias ──────────────────────────────────────────────────────
    htf = get_bias_with_levels(symbol, mt5.TIMEFRAME_H4)
    bias = htf.get("bias", "ranging")
    if bias == "ranging":
        logger.debug("HTF bias: ranging — no trade")
        return None
    logger.info(f"HTF bias: {bias}")

    # ── Step 2: H1 Liquidity Sweep (Liquidity Trap filter) ───────────────────
    # Chỉ vào lệnh sau khi giá đã quét EQH/EQL để tránh False Breakout Trap.
    # Bullish: cần sell-side liquidity (EQL) bị quét trước khi đảo chiều lên.
    # Bearish: cần buy-side liquidity (EQH) bị quét trước khi đảo chiều xuống.
    df_h1 = get_ohlcv(mt5.TIMEFRAME_H1, COUNT_H1, symbol)
    if df_h1 is None:
        return None

    sh_h1, sl_h1 = find_swing_points(df_h1, n=5)
    current_price = float(df_h1["close"].iloc[-1])

    liq_sweep_confirmed = False
    swept_level = None

    if bias == "bullish":
        eq_lows = get_sellside_liquidity(sl_h1)  # EQL clusters
        for (p1, p2) in eq_lows:
            level = min(p1[1], p2[1])
            if detect_liquidity_sweep(df_h1, level, sweep_type="low"):
                liq_sweep_confirmed = True
                swept_level = level
                logger.info(f"Sell-side liquidity swept at {level:.2f} — Liquidity Trap cleared")
                break
    else:
        eq_highs = get_buyside_liquidity(sh_h1)  # EQH clusters
        for (p1, p2) in eq_highs:
            level = max(p1[1], p2[1])
            if detect_liquidity_sweep(df_h1, level, sweep_type="high"):
                liq_sweep_confirmed = True
                swept_level = level
                logger.info(f"Buy-side liquidity swept at {level:.2f} — Liquidity Trap cleared")
                break

    if not liq_sweep_confirmed:
        logger.debug(f"No H1 liquidity sweep detected for {bias} — skipping (Liquidity Trap filter)")
        return None

    # Sau khi liquidity đã bị quét, yêu cầu MSS (strict — không có buffer)
    # thay vì BOS thông thường để tránh False Breakout Trap.
    if bias == "bullish":
        mss_confirmed = detect_mss(df_h1, sh_h1, sl_h1, "bullish")
        obs_h1 = find_bullish_obs(df_h1, sh_h1)
        ob = get_nearest_ob(obs_h1, current_price, "bullish")
    else:
        mss_confirmed = detect_mss(df_h1, sh_h1, sl_h1, "bearish")
        obs_h1 = find_bearish_obs(df_h1, sl_h1)
        ob = get_nearest_ob(obs_h1, current_price, "bearish")

    if not mss_confirmed:
        logger.debug(f"H1 MSS not confirmed for {bias} — False Breakout filter")
        return None
    if ob is None:
        logger.debug(f"No valid H1 OB found for {bias}")
        return None

    # Check price is near or in OB
    in_ob_zone = ob["bottom"] <= current_price <= ob["top"] * 1.005 if bias == "bullish" \
        else ob["bottom"] * 0.995 <= current_price <= ob["top"]
    if not in_ob_zone:
        logger.debug(f"Price {current_price} not yet in OB zone {ob['bottom']}–{ob['top']}")
        return None

    logger.info(f"H1 OB found: {ob['bottom']:.2f}–{ob['top']:.2f} ({bias})")

    # ── Step 3: M15 FVG (preferred, not required) ────────────────────────────
    df_m15 = get_ohlcv(mt5.TIMEFRAME_M15, COUNT_M15, symbol)
    fvg_in_ob = None
    if df_m15 is not None:
        fvgs = find_fvgs(df_m15)
        unfilled = filter_unfilled_fvgs(fvgs, df_m15)
        matching = get_fvgs_in_ob(unfilled, ob)
        if matching:
            fvg_in_ob = matching[-1]
            logger.info(f"M15 FVG in OB: {fvg_in_ob['bottom']:.2f}–{fvg_in_ob['top']:.2f}")

    # ── Step 4: M5 CHoCH confirmation ────────────────────────────────────────
    df_m5 = get_ohlcv(mt5.TIMEFRAME_M5, COUNT_M5, symbol)
    if df_m5 is None:
        return None

    sh_m5, sl_m5 = find_swing_points(df_m5, n=3)
    choch = detect_choch(df_m5, sh_m5, sl_m5, bias)
    if not choch:
        logger.debug(f"M5 CHoCH not confirmed for {bias} — 2-candle rule failed")
        return None

    # Sau CHoCH phải có MSS M5 cùng hướng để confirm đảo chiều thật,
    # không phải pullback trong trend cũ (Fake Reversal Trap filter).
    mss_m5 = detect_mss(df_m5, sh_m5, sl_m5, bias)
    if not mss_m5:
        logger.debug(f"M5 MSS not confirmed after CHoCH for {bias} — Fake Reversal filter")
        return None

    logger.info(f"M5 CHoCH + MSS confirmed ({bias}) — building signal")

    # ── Step 5: Build signal ──────────────────────────────────────────────────
    entry = current_price
    sl_buffer = _get_sl_buffer(symbol)

    if bias == "bullish":
        sl = round(ob["bottom"] - sl_buffer, 5)
        tp_target = htf["last_sh"]  # previous H4 swing high as TP target
    else:
        sl = round(ob["top"] + sl_buffer, 5)
        tp_target = htf["last_sl"]

    tp = calculate_tp(entry, sl, rr=MIN_RR, direction="BUY" if bias == "bullish" else "SELL")

    # Use HTF swing level as TP if it gives a better RR
    if tp_target:
        rr_from_htf = abs(tp_target - entry) / abs(entry - sl)
        if rr_from_htf >= MIN_RR:
            tp = round(tp_target, 2)

    direction = "BUY" if bias == "bullish" else "SELL"
    lot = fixed_lot if fixed_lot else calculate_lot_size(balance, entry, sl, risk_percent)

    signal = {
        "symbol":     symbol,
        "direction":  direction,
        "htf_bias":   bias,
        "ob_top":     ob["top"],
        "ob_bottom":  ob["bottom"],
        "entry":      round(entry, 2),
        "sl":         sl,
        "tp":         tp,
        "lot":        lot,
        "time":       datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "session":    get_current_session(),
    }

    if fvg_in_ob:
        signal["fvg_top"]    = fvg_in_ob["top"]
        signal["fvg_bottom"] = fvg_in_ob["bottom"]

    return signal
