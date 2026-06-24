"""
Backtest the SMC strategy using backtesting.py library.
Fetches historical data from MT5, runs the full SMC logic on each bar.

Usage:
  python -m tests.backtest --months 3
"""

import argparse
import sys
import os
from datetime import datetime, timezone
from typing import Tuple

import MetaTrader5 as mt5
import pandas as pd
from backtesting import Backtest, Strategy
from loguru import logger

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from connectors.mt5_connector import connect, disconnect, get_ohlcv
from analysis.structure import find_swing_points, detect_bos, detect_choch
from analysis.order_blocks import find_bullish_obs, find_bearish_obs, get_nearest_ob
from strategy.htf_bias import compute_bias_from_df
from risk.risk_manager import calculate_tp

SYMBOL      = "XAUUSDm"
MIN_RR      = 2.0
OB_BUFFER   = 0.50
MAX_SL_ABS  = 25.0   # max SL distance tuyệt đối (price units)
ATR_MULT    = 1.5    # max SL distance = ATR_MULT × ATR(14)
ATR_PERIOD  = 14


def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Tính ATR(period) từ DataFrame OHLCV."""
    high  = df["high"] if "high" in df.columns else df["High"]
    low   = df["low"]  if "low"  in df.columns else df["Low"]
    close = df["close"] if "close" in df.columns else df["Close"]

    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])


class SMCStrategy(Strategy):
    df_h4: pd.DataFrame = None
    df_h1: pd.DataFrame = None
    trade_log: list = []  # log từng entry

    def init(self):
        SMCStrategy.trade_log = []

    def next(self):
        i = len(self.data) - 1
        if i < 20:
            return

        current_time  = self.data.index[i]
        current_price = float(self.data.Close[-1])

        # ── H4 Bias ──
        h4_slice = self.df_h4[self.df_h4["time"] <= current_time]
        if len(h4_slice) < 20:
            return
        bias = compute_bias_from_df(h4_slice.reset_index(drop=True), n=5)
        if bias == "ranging":
            return

        # ── H1 OB + BOS ──
        h1_slice = self.df_h1[self.df_h1["time"] <= current_time].tail(100).reset_index(drop=True)
        if len(h1_slice) < 20:
            return

        sh_h1, sl_h1 = find_swing_points(h1_slice, n=5)

        if bias == "bullish":
            if not detect_bos(h1_slice, sh_h1, sl_h1, "bullish"):
                return
            obs = find_bullish_obs(h1_slice, sh_h1)
            ob  = get_nearest_ob(obs, current_price, "bullish")
        else:
            if not detect_bos(h1_slice, sh_h1, sl_h1, "bearish"):
                return
            obs = find_bearish_obs(h1_slice, sl_h1)
            ob  = get_nearest_ob(obs, current_price, "bearish")

        if ob is None:
            return

        if bias == "bullish" and not (ob["bottom"] <= current_price <= ob["top"] * 1.005):
            return
        if bias == "bearish" and not (ob["bottom"] * 0.995 <= current_price <= ob["top"]):
            return

        # ── M5 CHoCH ──
        m5_slice = pd.DataFrame({
            "time":  list(self.data.index[:i+1]),
            "open":  list(self.data.Open[:i+1]),
            "high":  list(self.data.High[:i+1]),
            "low":   list(self.data.Low[:i+1]),
            "close": list(self.data.Close[:i+1]),
        }).tail(30).reset_index(drop=True)

        sh_m5, sl_m5 = find_swing_points(m5_slice, n=3)
        if not detect_choch(m5_slice, sh_m5, sl_m5, bias):
            return

        # ── Place trade + log entry ──
        if self.position:
            return  # chỉ 1 lệnh cùng lúc

        if bias == "bullish":
            sl = round(ob["bottom"] - OB_BUFFER, 2)
            tp = calculate_tp(current_price, sl, rr=MIN_RR, direction="BUY")
            direction = "BUY"
        else:
            sl = round(ob["top"] + OB_BUFFER, 2)
            tp = calculate_tp(current_price, sl, rr=MIN_RR, direction="SELL")
            direction = "SELL"

        # ── SL Filter: max tuyệt đối + ATR ──
        sl_distance = abs(current_price - sl)
        atr = calculate_atr(h1_slice, ATR_PERIOD)
        max_sl_atr = ATR_MULT * atr if atr and atr > 0 else MAX_SL_ABS

        if sl_distance > MAX_SL_ABS:
            print(f"  ⛔ SKIPPED (SL {sl_distance:.2f} > max {MAX_SL_ABS})")
            return
        if sl_distance > max_sl_atr:
            print(f"  ⛔ SKIPPED (SL {sl_distance:.2f} > 1.5×ATR {max_sl_atr:.2f})")
            return

        if bias == "bullish":
            self.buy(sl=sl, tp=tp)
        else:
            self.sell(sl=sl, tp=tp)

        entry_info = {
            "time":      str(current_time),
            "direction": direction,
            "bias":      bias,
            "entry":     round(current_price, 2),
            "sl":        sl,
            "tp":        tp,
            "ob_zone":   f"{ob['bottom']:.2f}–{ob['top']:.2f}",
            "rr":        MIN_RR,
        }
        SMCStrategy.trade_log.append(entry_info)

        print(
            f"\n{'='*55}\n"
            f"  ENTRY SIGNAL\n"
            f"  Time     : {current_time}\n"
            f"  Direction: {direction}  |  Bias: {bias.upper()}\n"
            f"  Entry    : {current_price:.2f}\n"
            f"  SL       : {sl:.2f}  |  TP: {tp:.2f}  |  RR: 1:{MIN_RR}\n"
            f"  H1 OB    : {ob['bottom']:.2f}–{ob['top']:.2f}\n"
            f"{'='*55}"
        )


def fetch_backtest_data(months: int = 3) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    candles_h4 = months * 30 * 6
    candles_h1 = months * 30 * 24
    candles_m5 = months * 30 * 24 * 12

    logger.info(f"Fetching {months} months of data...")
    df_h4 = get_ohlcv(mt5.TIMEFRAME_H4, candles_h4, SYMBOL)
    df_h1 = get_ohlcv(mt5.TIMEFRAME_H1, candles_h1, SYMBOL)
    df_m5 = get_ohlcv(mt5.TIMEFRAME_M5, candles_m5, SYMBOL)
    return df_h4, df_h1, df_m5


def print_summary(stats, trade_log: list):
    trades = stats._trades  # DataFrame của từng trade

    print("\n" + "="*60)
    print("  BACKTEST SUMMARY")
    print("="*60)
    print(f"  Period        : {stats['Start']} → {stats['End']}")
    print(f"  Total trades  : {stats['# Trades']}")
    print(f"  Win rate      : {stats['Win Rate [%]']:.1f}%")
    print(f"  Return        : {stats['Return [%]']:.2f}%")
    print(f"  Max drawdown  : {stats['Max. Drawdown [%]']:.2f}%")
    print(f"  Sharpe ratio  : {stats['Sharpe Ratio']:.2f}")
    print(f"  Best trade    : {stats['Best Trade [%]']:.2f}%")
    print(f"  Worst trade   : {stats['Worst Trade [%]']:.2f}%")
    print(f"  Avg trade     : {stats['Avg. Trade [%]']:.2f}%")
    print("="*60)

    if trades.empty:
        print("  No trades found.")
        return

    # Tìm đúng tên cột PnL của backtesting.py
    pnl_col   = "PnL"   if "PnL"   in trades.columns else "ReturnPct"
    entry_col = "EntryPrice" if "EntryPrice" in trades.columns else "Entry"
    time_col  = "EntryTime"  if "EntryTime"  in trades.columns else "Entry Time"

    pnl_values = trades[pnl_col]
    wins   = trades[pnl_values > 0]
    losses = trades[pnl_values <= 0]

    total_usd = pnl_values.sum()
    win_usd   = wins[pnl_col].sum()   if len(wins)   else 0.0
    loss_usd  = losses[pnl_col].sum() if len(losses) else 0.0

    print(f"\n  Wins   : {len(wins)}  |  Losses: {len(losses)}")
    if len(wins):
        print(f"  Avg win  : ${wins[pnl_col].mean():.2f}")
    if len(losses):
        print(f"  Avg loss : ${losses[pnl_col].mean():.2f}")

    sign = "+" if total_usd >= 0 else ""
    print(f"\n  ── Tổng kết USD ────────────────────────────")
    print(f"  Tổng thắng  : +${win_usd:.2f}")
    print(f"  Tổng thua   :  -${abs(loss_usd):.2f}")
    print(f"  NET P&L     : {sign}${total_usd:.2f}  {'✅ PROFIT' if total_usd >= 0 else '❌ LOSS'}")
    print(f"  ─────────────────────────────────────────────")

    print(f"\n  {'#':<4} {'Entry Time':<20} {'Dir':<5} {'Entry':>8} {'SL':>8} {'TP':>8} {'PnL':>8}  Result")
    print(f"  {'-'*70}")

    for i, (_, row) in enumerate(trades.iterrows()):
        pnl       = row[pnl_col]
        result    = "✅ WIN " if pnl > 0 else "❌ LOSS"
        log       = trade_log[i] if i < len(trade_log) else {}
        direction = log.get("direction", "?")
        entry_p   = log.get("entry", row.get(entry_col, 0))
        sl_p      = log.get("sl", "?")
        tp_p      = log.get("tp", "?")
        time_str  = str(row.get(time_col, ""))[:16]
        print(f"  {i+1:<4} {time_str:<20} {direction:<5} {entry_p:>8.2f} {sl_p!s:>8} {tp_p!s:>8} {pnl:>8.2f}  {result}")

    print("="*60)
    print("  Chart → backtest_result.html  (mở bằng browser)\n")

    # Ghi ra file text
    save_summary(stats, trades, trade_log, pnl_col, time_col, entry_col)


def save_summary(stats, trades, trade_log: list, pnl_col: str, time_col: str, entry_col: str):
    from datetime import datetime
    filename = f"backtest_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    lines = []

    lines.append("=" * 60)
    lines.append("  BACKTEST SUMMARY — SMC Bot XAUUSDm")
    lines.append("=" * 60)
    lines.append(f"  Period        : {stats['Start']} → {stats['End']}")
    lines.append(f"  Total trades  : {stats['# Trades']}")
    lines.append(f"  Win rate      : {stats['Win Rate [%]']:.1f}%")
    lines.append(f"  Return        : {stats['Return [%]']:.2f}%")
    lines.append(f"  Max drawdown  : {stats['Max. Drawdown [%]']:.2f}%")
    lines.append(f"  Sharpe ratio  : {stats['Sharpe Ratio']:.2f}")
    lines.append(f"  Best trade    : {stats['Best Trade [%]']:.2f}%")
    lines.append(f"  Worst trade   : {stats['Worst Trade [%]']:.2f}%")
    lines.append(f"  Avg trade     : {stats['Avg. Trade [%]']:.2f}%")
    lines.append("=" * 60)

    if not trades.empty:
        pnl_values = trades[pnl_col]
        wins       = trades[pnl_values > 0]
        losses     = trades[pnl_values <= 0]
        total_usd  = pnl_values.sum()
        win_usd    = wins[pnl_col].sum()   if len(wins)   else 0.0
        loss_usd   = losses[pnl_col].sum() if len(losses) else 0.0

        lines.append(f"\n  Wins   : {len(wins)}  |  Losses: {len(losses)}")
        lines.append(f"  Avg win  : ${wins[pnl_col].mean():.2f}"   if len(wins)   else "  Avg win  : N/A")
        lines.append(f"  Avg loss : ${losses[pnl_col].mean():.2f}" if len(losses) else "  Avg loss : N/A")
        lines.append(f"\n  ── Tổng kết USD ──────────────────────────────")
        lines.append(f"  Tổng thắng  : +${win_usd:.2f}")
        lines.append(f"  Tổng thua   :  -${abs(loss_usd):.2f}")
        sign = "+" if total_usd >= 0 else ""
        lines.append(f"  NET P&L     : {sign}${total_usd:.2f}  {'PROFIT' if total_usd >= 0 else 'LOSS'}")
        lines.append(f"  ────────────────────────────────────────────────")

        lines.append(f"\n  {'#':<4} {'Entry Time':<20} {'Dir':<5} {'Entry':>8} {'SL':>8} {'TP':>8} {'PnL':>8}  Result")
        lines.append(f"  {'-'*70}")
        for i, (_, row) in enumerate(trades.iterrows()):
            pnl       = row[pnl_col]
            result    = "WIN " if pnl > 0 else "LOSS"
            log       = trade_log[i] if i < len(trade_log) else {}
            direction = log.get("direction", "?")
            entry_p   = log.get("entry", row.get(entry_col, 0))
            sl_p      = log.get("sl", "?")
            tp_p      = log.get("tp", "?")
            time_str  = str(row.get(time_col, ""))[:16]
            lines.append(f"  {i+1:<4} {time_str:<20} {direction:<5} {entry_p:>8.2f} {sl_p!s:>8} {tp_p!s:>8} {pnl:>8.2f}  {result}")

    lines.append("=" * 60)

    output_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), filename)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"  Summary saved → {output_path}")


def run_backtest(months: int = 3, cash: float = 10_000):
    if not connect():
        logger.error("MT5 connection failed")
        return

    df_h4, df_h1, df_m5 = fetch_backtest_data(months)
    disconnect()

    if df_m5 is None or df_h4 is None or df_h1 is None:
        logger.error("Failed to fetch data")
        return

    logger.info(f"Data loaded — H4: {len(df_h4)} | H1: {len(df_h1)} | M5: {len(df_m5)} candles")

    df_m5_bt = df_m5.rename(columns={
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "volume": "Volume"
    }).set_index("time")

    SMCStrategy.df_h4 = df_h4
    SMCStrategy.df_h1 = df_h1

    logger.info("Running backtest...")
    bt    = Backtest(df_m5_bt, SMCStrategy, cash=cash, commission=0.0002, exclusive_orders=True)
    stats = bt.run()

    print_summary(stats, SMCStrategy.trade_log)
    try:
        bt.plot(filename="backtest_result.html", open_browser=False)
        print("  Chart → backtest_result.html")
    except Exception as e:
        logger.warning(f"Chart generation skipped (known Python 3.7 bug): {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--months", type=int, default=3, help="Months of history to backtest")
    parser.add_argument("--cash",   type=float, default=10000, help="Starting capital")
    args = parser.parse_args()
    run_backtest(args.months, args.cash)
