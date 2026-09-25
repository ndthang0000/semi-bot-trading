from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from sqlite3 import Connection

from .zones import CandleSlice, latest_atr


DEFAULT_STOP_ATR = 1.0
MIN_STOP_ATR = 0.618
DEFAULT_RISK_REWARD = 1.5
MIN_RISK_REWARD = 1.0
MAX_RISK_REWARD = 4.0


@dataclass(frozen=True)
class QuickOrderGeometry:
    side: str
    entry: float
    requested_stop: float | None
    stop_loss: float
    take_profit: float
    stop_distance: float
    stop_atr: float
    risk_reward: float
    atr_h1: float
    stop_was_adjusted: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def build_quick_order_geometry(
    *,
    side: str,
    entry: float,
    requested_stop: float | None,
    atr_h1: float,
    risk_reward: float = DEFAULT_RISK_REWARD,
) -> QuickOrderGeometry:
    side = side.lower().strip()
    if side not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    if entry <= 0 or atr_h1 <= 0:
        raise ValueError("entry and H1 ATR must be positive")
    if not MIN_RISK_REWARD <= risk_reward <= MAX_RISK_REWARD:
        raise ValueError(f"risk_reward must be between {MIN_RISK_REWARD:g} and {MAX_RISK_REWARD:g}")

    default_distance = atr_h1 * DEFAULT_STOP_ATR
    minimum_distance = atr_h1 * MIN_STOP_ATR
    requested = float(requested_stop) if requested_stop is not None else None
    if requested is not None and requested <= 0:
        raise ValueError("stop_loss must be positive")

    if side == "buy":
        if requested is not None and requested >= entry:
            raise ValueError("BUY stop loss must be below entry")
        stop_loss = requested if requested is not None else entry - default_distance
        take_profit = entry + (entry - stop_loss) * risk_reward
    else:
        if requested is not None and requested <= entry:
            raise ValueError("SELL stop loss must be above entry")
        stop_loss = requested if requested is not None else entry + default_distance
        take_profit = entry - (stop_loss - entry) * risk_reward

    distance = abs(entry - stop_loss)
    if distance + 1e-9 < minimum_distance:
        raise ValueError(
            f"SL must be at least {MIN_STOP_ATR:g} H1 ATR from entry; "
            f"calculated={distance / atr_h1:.3f} H1 ATR"
        )
    return QuickOrderGeometry(
        side=side,
        entry=round(entry, 5),
        requested_stop=requested,
        stop_loss=round(stop_loss, 5),
        take_profit=round(take_profit, 5),
        stop_distance=round(distance, 5),
        stop_atr=distance / atr_h1,
        risk_reward=risk_reward,
        atr_h1=atr_h1,
        stop_was_adjusted=requested is None,
    )


def latest_closed_h1_atr(conn: Connection, symbol: str, period: int = 14) -> tuple[float, str]:
    now = datetime.now(UTC).isoformat()
    rows = conn.execute(
        """
        SELECT open_time, close_time, open, high, low, close
        FROM candles
        WHERE symbol = ? AND timeframe = 'H1' AND close_time <= ?
        ORDER BY open_time DESC
        LIMIT ?
        """,
        (symbol, now, period + 1),
    ).fetchall()
    if len(rows) < period:
        raise ValueError(f"Need at least {period} closed H1 candles to calculate ATR")
    ordered = list(reversed(rows))
    candles = [
        CandleSlice(
            open_time=str(row["open_time"]),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
        )
        for row in ordered
    ]
    value = latest_atr(candles, period=period)
    if value is None or value <= 0:
        raise ValueError("H1 ATR is unavailable")
    return float(value), str(ordered[-1]["close_time"])
