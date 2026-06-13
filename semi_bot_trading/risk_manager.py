"""Risk management module for the live trading bot.

Each trade's lot size is calculated dynamically based on:
    lot_size = (balance * risk_pct / 100) / (stop_distance * contract_size)

Daily loss is tracked from closed trade P&L in the DB. When the daily loss
ceiling is hit, the bot halts execution for the rest of the day.

Account profiles
----------------
- personal       : flexible defaults, suitable for personal accounts
- ftmo_challenge : FTMO Challenge rules (5% daily loss, 10% max drawdown)
- the5ers        : The5ers rules (4% daily loss, 8% max drawdown)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from sqlite3 import Connection
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .mt5_client import MT5BrokerClient


@dataclass(frozen=True)
class AccountProfile:
    name: str
    risk_per_trade_pct: float   # % of balance risked per trade
    max_daily_loss_pct: float   # halt when today's loss exceeds this % of balance
    max_total_drawdown_pct: float  # informational; logged but not enforced in this version
    max_trades_per_day: int


PROFILES: dict[str, AccountProfile] = {
    "personal": AccountProfile(
        name="Personal",
        risk_per_trade_pct=1.0,
        max_daily_loss_pct=5.0,
        max_total_drawdown_pct=20.0,
        max_trades_per_day=10,
    ),
    "ftmo_challenge": AccountProfile(
        name="FTMO Challenge",
        risk_per_trade_pct=1.0,
        max_daily_loss_pct=5.0,
        max_total_drawdown_pct=10.0,
        max_trades_per_day=10,
    ),
    "the5ers": AccountProfile(
        name="The5ers",
        risk_per_trade_pct=0.5,
        max_daily_loss_pct=4.0,
        max_total_drawdown_pct=8.0,
        max_trades_per_day=5,
    ),
}

MIN_LOT = 0.01
MAX_LOT = 100.0


@dataclass(frozen=True)
class RiskAssessment:
    allowed: bool
    lot_size: float
    reason: str
    balance: float = 0.0
    risk_amount: float = 0.0
    daily_loss: float = 0.0
    daily_loss_limit: float = 0.0


class RiskManager:
    """Calculates lot size and enforces risk limits before each trade."""

    def __init__(
        self,
        client: "MT5BrokerClient",
        profile: AccountProfile,
        risk_per_trade_pct: float | None = None,
    ) -> None:
        self.client = client
        self.profile = profile
        # Allow env-level override of risk %; otherwise use profile default.
        self._risk_pct = risk_per_trade_pct if risk_per_trade_pct is not None else profile.risk_per_trade_pct

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def assess_trade(
        self,
        conn: Connection,
        symbol: str,
        entry: float | None,
        stop_loss: float | None,
        broker_symbol: str,
    ) -> RiskAssessment:
        """Return a RiskAssessment for the proposed trade.

        If `allowed` is False the bot must not place the order.
        If `allowed` is True the bot should use `lot_size` for the order.
        """
        if entry is None or stop_loss is None:
            return RiskAssessment(allowed=False, lot_size=0.0, reason="entry or stop_loss is None")

        stop_distance = abs(float(entry) - float(stop_loss))
        if stop_distance == 0:
            return RiskAssessment(allowed=False, lot_size=0.0, reason="stop_loss equals entry price")

        # Fetch live account data from MT5
        try:
            account = self.client.get_account_info()
        except Exception as exc:
            return RiskAssessment(allowed=False, lot_size=0.0, reason=f"MT5 account_info failed: {exc}")

        balance = account["balance"]
        if balance <= 0:
            return RiskAssessment(allowed=False, lot_size=0.0, reason=f"Invalid balance: {balance}")

        # Daily loss check
        daily_loss = get_today_realized_loss(conn, symbol)
        daily_loss_limit = balance * self.profile.max_daily_loss_pct / 100.0
        if daily_loss >= daily_loss_limit:
            return RiskAssessment(
                allowed=False,
                lot_size=0.0,
                reason=(
                    f"[{self.profile.name}] Daily loss limit reached: "
                    f"${daily_loss:.2f} >= ${daily_loss_limit:.2f} "
                    f"({self.profile.max_daily_loss_pct}% of ${balance:.2f})"
                ),
                balance=balance,
                daily_loss=daily_loss,
                daily_loss_limit=daily_loss_limit,
            )

        # Risk amount — don't let a single trade exceed the remaining daily budget
        risk_amount = balance * self._risk_pct / 100.0
        remaining_budget = daily_loss_limit - daily_loss
        risk_amount = min(risk_amount, remaining_budget)

        # Lot size calculation
        try:
            contract_size = self.client.get_symbol_contract_size(broker_symbol)
        except Exception:
            contract_size = 100.0  # safe fallback for XAUUSD

        raw_lot = risk_amount / (stop_distance * contract_size)
        lot_size = _clamp_lot(raw_lot)

        return RiskAssessment(
            allowed=True,
            lot_size=lot_size,
            reason=(
                f"[{self.profile.name}] risk={self._risk_pct}% "
                f"balance=${balance:.2f} "
                f"risk_amount=${risk_amount:.2f} "
                f"stop={stop_distance:.5f} "
                f"contract={contract_size} "
                f"lots={lot_size}"
            ),
            balance=balance,
            risk_amount=risk_amount,
            daily_loss=daily_loss,
            daily_loss_limit=daily_loss_limit,
        )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def get_today_realized_loss(conn: Connection, symbol: str) -> float:
    """Return today's total realized loss as a positive number (0 if profitable)."""
    day_prefix = datetime.now(timezone.utc).date().isoformat()
    row = conn.execute(
        """
        SELECT COALESCE(SUM(pnl), 0.0) AS total_pnl
        FROM trade_orders
        WHERE symbol = ?
          AND status = 'closed'
          AND closed_at >= ?
        """,
        (symbol, day_prefix),
    ).fetchone()
    total_pnl = float(row["total_pnl"])
    # Return the magnitude of losses; ignore profits (they don't reduce limits).
    return -total_pnl if total_pnl < 0 else 0.0


def _clamp_lot(raw: float) -> float:
    """Round to 2 decimal places and clamp within broker-safe bounds."""
    rounded = round(raw, 2)
    return max(MIN_LOT, min(MAX_LOT, rounded))


def build_risk_manager(client: "MT5BrokerClient", profile_name: str, risk_per_trade_pct: float | None) -> RiskManager:
    """Construct a RiskManager from env-level config."""
    key = profile_name.lower().strip()
    if key not in PROFILES:
        raise ValueError(
            f"Unknown account profile '{profile_name}'. "
            f"Valid options: {', '.join(PROFILES)}"
        )
    return RiskManager(client, PROFILES[key], risk_per_trade_pct)
