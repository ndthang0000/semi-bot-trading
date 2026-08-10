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
from datetime import datetime, timedelta, timezone
from sqlite3 import Connection
import math
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .mt5_client import MT5BrokerClient


@dataclass(frozen=True)
class AccountProfile:
    name: str
    risk_per_trade_pct: float   # % of balance risked per trade
    max_daily_loss_pct: float   # halt when today's loss exceeds this % of balance
    max_total_drawdown_pct: float  # informational; logged but not enforced in this version
    max_trades_per_day: int
    balance_scale: float = 1.0


PROFILES: dict[str, AccountProfile] = {
    "personal": AccountProfile(
        name="Personal",
        risk_per_trade_pct=2.0,
        max_daily_loss_pct=6.0,
        max_total_drawdown_pct=20.0,
        max_trades_per_day=10,
    ),
    "personal_cent": AccountProfile(
        name="Personal Cent",
        risk_per_trade_pct=2.0,
        max_daily_loss_pct=6.0,
        max_total_drawdown_pct=20.0,
        max_trades_per_day=10,
        balance_scale=0.01,
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
        risk_per_trade_pct=1.0,
        max_daily_loss_pct=4.0,
        max_total_drawdown_pct=8.0,
        max_trades_per_day=5,
    ),
}

MIN_LOT = 0.01
MAX_LOT = 10.0   # hard safety cap — prevents runaway lot sizing from bad contract_size data


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
        balance_scale: float | None = None,
    ) -> None:
        self.client = client
        self.profile = profile
        # Allow env-level override of risk %; otherwise use profile default.
        self._risk_pct = risk_per_trade_pct if risk_per_trade_pct is not None else profile.risk_per_trade_pct
        self._balance_scale = balance_scale if balance_scale is not None else profile.balance_scale

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
        account_label: str = "Default",
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
        risk_balance = balance * self._balance_scale
        if risk_balance <= 0:
            return RiskAssessment(allowed=False, lot_size=0.0, reason=f"Invalid risk-adjusted balance: {risk_balance}")

        # FTMO's daily loss is equity-based and therefore includes floating P/L.
        # snapshot_account refreshes this metric immediately before candidates
        # are evaluated. Fail closed when that safety snapshot is absent/stale.
        if self.profile.name.lower().startswith("ftmo"):
            daily_metric = conn.execute(
                """
                SELECT daily_profit, initial_balance, balance_at_midnight, snapshot_at
                FROM account_daily_metrics
                WHERE account_label = ?
                ORDER BY snapshot_at DESC
                LIMIT 1
                """,
                (account_label,),
            ).fetchone()
            if daily_metric is None:
                return RiskAssessment(
                    allowed=False,
                    lot_size=0.0,
                    reason=f"[{self.profile.name}] blocked: FTMO daily equity metric is unavailable",
                    balance=risk_balance,
                )
            try:
                metric_at = datetime.fromisoformat(str(daily_metric["snapshot_at"]).replace("Z", "+00:00"))
                if metric_at.tzinfo is None:
                    metric_at = metric_at.replace(tzinfo=timezone.utc)
            except ValueError:
                metric_at = datetime.min.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - metric_at.astimezone(timezone.utc) > timedelta(minutes=2):
                return RiskAssessment(
                    allowed=False,
                    lot_size=0.0,
                    reason=f"[{self.profile.name}] blocked: FTMO daily equity metric is stale",
                    balance=risk_balance,
                )
            daily_loss = max(-float(daily_metric["daily_profit"]) * self._balance_scale, 0.0)
            limit_base = float(daily_metric["initial_balance"] or daily_metric["balance_at_midnight"]) * self._balance_scale
            daily_loss_limit = limit_base * self.profile.max_daily_loss_pct / 100.0
        else:
            daily_loss = get_today_realized_loss(conn, symbol, account_label=account_label) * self._balance_scale
            daily_loss_limit = risk_balance * self.profile.max_daily_loss_pct / 100.0
        if daily_loss >= daily_loss_limit:
            return RiskAssessment(
                allowed=False,
                lot_size=0.0,
                reason=(
                    f"[{self.profile.name}] Daily loss limit reached: "
                    f"${daily_loss:.2f} >= ${daily_loss_limit:.2f} "
                    f"({self.profile.max_daily_loss_pct}% of risk balance ${risk_balance:.2f})"
                ),
                balance=risk_balance,
                daily_loss=daily_loss,
                daily_loss_limit=daily_loss_limit,
            )

        # Risk amount — don't let a single trade exceed the remaining daily budget
        risk_amount = risk_balance * self._risk_pct / 100.0
        remaining_budget = daily_loss_limit - daily_loss
        risk_amount = min(risk_amount, remaining_budget)

        # Lot size calculation
        symbol_trade_info: dict[str, Any] = {}
        try:
            if hasattr(self.client, "get_symbol_trade_info"):
                symbol_trade_info = dict(self.client.get_symbol_trade_info(broker_symbol))
                contract_size = float(symbol_trade_info.get("trade_contract_size") or 0.0)
                if contract_size <= 0:
                    raise RuntimeError(f"invalid trade_contract_size={contract_size}")
            else:
                contract_size = self.client.get_symbol_contract_size(broker_symbol)
        except Exception as exc:
            if self.profile.name.lower().startswith("ftmo"):
                return RiskAssessment(
                    allowed=False,
                    lot_size=0.0,
                    reason=f"[{self.profile.name}] blocked: could not read contract_size for {broker_symbol}: {exc}",
                    balance=risk_balance,
                    daily_loss=daily_loss,
                    daily_loss_limit=daily_loss_limit,
                )
            contract_size = 100.0  # safe fallback for XAUUSD

        # Sanity check: contract_size < 10 for a gold symbol almost always means
        # MT5 returned data for a cent-account or exotic symbol. Fall back to 100.
        if contract_size < 10:
            if self.profile.name.lower().startswith("ftmo"):
                return RiskAssessment(
                    allowed=False,
                    lot_size=0.0,
                    reason=f"[{self.profile.name}] blocked: suspicious contract_size={contract_size} for {broker_symbol}",
                    balance=risk_balance,
                    daily_loss=daily_loss,
                    daily_loss_limit=daily_loss_limit,
                )
            contract_size = 100.0

        raw_lot = risk_amount / (stop_distance * contract_size)
        volume_min = float(symbol_trade_info.get("volume_min") or MIN_LOT)
        volume_max = float(symbol_trade_info.get("volume_max") or MAX_LOT)
        volume_step = float(symbol_trade_info.get("volume_step") or 0.01)
        if self.profile.name.lower().startswith("ftmo") and raw_lot < max(MIN_LOT, volume_min):
            return RiskAssessment(
                allowed=False,
                lot_size=0.0,
                reason=(
                    f"[{self.profile.name}] blocked: calculated lot {raw_lot:.4f} is below "
                    f"broker minimum {max(MIN_LOT, volume_min):.4f}; refusing to over-risk"
                ),
                balance=risk_balance,
                risk_amount=risk_amount,
                daily_loss=daily_loss,
                daily_loss_limit=daily_loss_limit,
            )
        lot_size = _clamp_lot(raw_lot, volume_min=volume_min, volume_max=volume_max, volume_step=volume_step)

        clamped_warning = ""
        if raw_lot > MAX_LOT:
            clamped_warning = (
                f" WARNING: raw_lot={raw_lot:.2f} exceeded MAX_LOT={MAX_LOT}, clamped. "
                f"Check contract_size or balance."
            )

        return RiskAssessment(
            allowed=True,
            lot_size=lot_size,
            reason=(
                f"[{self.profile.name}] risk={self._risk_pct}% "
                f"balance_raw=${balance:.2f} "
                f"balance_scale={self._balance_scale:.4f} "
                f"risk_balance=${risk_balance:.2f} "
                f"risk_amount=${risk_amount:.2f} "
                f"stop={stop_distance:.5f} "
                f"contract={contract_size} "
                f"lots={lot_size}"
                f"{clamped_warning}"
            ),
            balance=risk_balance,
            risk_amount=risk_amount,
            daily_loss=daily_loss,
            daily_loss_limit=daily_loss_limit,
        )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def get_today_realized_loss(conn: Connection, symbol: str, *, account_label: str = "Default") -> float:
    """Return today's total realized loss as a positive number (0 if profitable)."""
    day_prefix = datetime.now(timezone.utc).date().isoformat()
    row = conn.execute(
        """
        SELECT COALESCE(SUM(pnl), 0.0) AS total_pnl
        FROM trade_orders
        WHERE symbol = ?
          AND account_label = ?
          AND status = 'closed'
          AND closed_at >= ?
        """,
        (symbol, account_label, day_prefix),
    ).fetchone()
    total_pnl = float(row["total_pnl"])
    # Return the magnitude of losses; ignore profits (they don't reduce limits).
    return -total_pnl if total_pnl < 0 else 0.0


def _clamp_lot(
    raw: float,
    *,
    volume_min: float = MIN_LOT,
    volume_max: float = MAX_LOT,
    volume_step: float = 0.01,
) -> float:
    """Round down to broker volume step and clamp within local and broker caps."""
    min_lot = max(MIN_LOT, float(volume_min or MIN_LOT))
    max_lot = min(MAX_LOT, float(volume_max or MAX_LOT))
    step = float(volume_step or 0.01)
    if step <= 0:
        step = 0.01
    stepped = math.floor(max(raw, 0.0) / step) * step
    decimals = max(0, min(8, len(f"{step:.8f}".rstrip("0").split(".")[-1])))
    rounded = round(stepped, decimals)
    return max(min_lot, min(max_lot, rounded))


def build_risk_manager(
    client: "MT5BrokerClient",
    profile_name: str,
    risk_per_trade_pct: float | None,
    balance_scale: float | None = None,
) -> RiskManager:
    """Construct a RiskManager from env-level config."""
    key = profile_name.lower().strip()
    if key not in PROFILES:
        raise ValueError(
            f"Unknown account profile '{profile_name}'. "
            f"Valid options: {', '.join(PROFILES)}"
        )
    return RiskManager(client, PROFILES[key], risk_per_trade_pct, balance_scale)
