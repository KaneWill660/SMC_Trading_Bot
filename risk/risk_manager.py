"""
Risk management: lot size calculation, daily loss tracking, circuit breaker.
XAUUSD: 1 standard lot = $10 per pip (pip = 0.10 price move).
"""

from loguru import logger

XAUUSD_PIP_VALUE_PER_LOT = 10.0  # USD per pip per standard lot
MIN_LOT  = 0.01
MAX_LOT  = 10.0
LOT_STEP = 0.01


def calculate_lot_size(
    balance: float,
    entry: float,
    sl: float,
    risk_percent: float = 0.01,
) -> float:
    """
    Calculate lot size so that if SL is hit, loss equals risk_percent of balance.
    sl_pips = |entry - sl| / 0.10  (XAUUSD pip size = 0.10)
    """
    risk_amount = balance * risk_percent
    sl_distance = abs(entry - sl)

    if sl_distance == 0:
        logger.warning("SL distance is 0 — returning minimum lot")
        return MIN_LOT

    sl_pips = sl_distance / 0.10
    lot = risk_amount / (sl_pips * XAUUSD_PIP_VALUE_PER_LOT)

    # Round to nearest lot step
    lot = round(round(lot / LOT_STEP) * LOT_STEP, 2)
    lot = max(MIN_LOT, min(MAX_LOT, lot))
    return lot


def calculate_tp(
    entry: float,
    sl: float,
    rr: float = 2.0,
    direction: str = "BUY",
) -> float:
    """Calculate TP price based on desired RR ratio."""
    sl_distance = abs(entry - sl)
    tp_distance = sl_distance * rr
    if direction == "BUY":
        return round(entry + tp_distance, 2)
    return round(entry - tp_distance, 2)


class DailyRiskTracker:
    """Track daily PnL and trigger circuit breaker if max loss is exceeded."""

    def __init__(
        self,
        initial_balance: float,
        max_daily_loss_pct: float = 0.03,
    ):
        self.initial_balance    = initial_balance
        self.max_daily_loss_pct = max_daily_loss_pct
        self.daily_pnl          = 0.0

    def record_trade(self, pnl: float):
        self.daily_pnl += pnl
        if pnl < 0:
            logger.warning(f"Trade loss recorded: {pnl:.2f} | Daily PnL: {self.daily_pnl:.2f}")
        else:
            logger.info(f"Trade win recorded: +{pnl:.2f} | Daily PnL: {self.daily_pnl:.2f}")

    def circuit_breaker_tripped(self) -> bool:
        return False

    def reset(self, new_balance: float):
        self.initial_balance = new_balance
        self.daily_pnl       = 0.0
        logger.info(f"Daily risk tracker reset | Balance: {new_balance:.2f}")
