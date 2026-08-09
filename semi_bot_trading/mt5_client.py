from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .candles import Candle
from .timeframes import timeframe_delta


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MT5Credentials:
    login: int
    password: str
    server: str
    path: str | None = None
    server_utc_offset_hours: float = 0.0


def mt5_server_timestamp_to_utc(timestamp: int | float, server_utc_offset_hours: float = 0.0) -> datetime:
    """Interpret an MT5 epoch containing broker wall time and return real UTC.

    Most terminals return genuine Unix UTC timestamps and should use the
    default zero offset. A broker whose MT5 history is three hours ahead of
    UTC should configure ``server_utc_offset_hours=3``.
    """
    offset = float(server_utc_offset_hours)
    if not -24.0 < offset < 24.0:
        raise ValueError(f"MT5 server UTC offset must be between -24 and 24 hours, got {offset}")
    encoded_wall_time = datetime.fromtimestamp(int(timestamp), tz=UTC)
    return encoded_wall_time - timedelta(hours=offset)


@dataclass(frozen=True)
class MT5OrderRequest:
    broker_symbol: str
    side: str
    volume: float
    stop_loss: float
    take_profit: float
    comment: str
    magic: int
    entry_price: float | None = None
    expires_at: str | None = None


class MT5BrokerClient:
    def __init__(self, credentials: MT5Credentials) -> None:
        try:
            import MetaTrader5 as mt5
        except ImportError as exc:
            raise RuntimeError("MetaTrader5 package is not installed. Run: pip install MetaTrader5") from exc
        self.mt5 = mt5
        self.credentials = credentials

    def connect(self) -> None:
        kwargs: dict[str, Any] = {
            "login": self.credentials.login,
            "password": self.credentials.password,
            "server": self.credentials.server,
        }
        # Windows services often cannot rely on MetaTrader5's terminal auto-discovery.
        # Passing terminal64.exe explicitly avoids "MetaTrader 5 x64 not found" on VPS.
        if self.credentials.path:
            kwargs["path"] = self.credentials.path
        ok = self.mt5.initialize(**kwargs)
        if not ok:
            raise RuntimeError(f"MT5 initialize failed: {self.mt5.last_error()}")

    def shutdown(self) -> None:
        self.mt5.shutdown()

    def ensure_symbol(self, broker_symbol: str) -> None:
        info = self.mt5.symbol_info(broker_symbol)
        if info is None:
            raise RuntimeError(f"MT5 symbol not found: {broker_symbol}")
        if not info.visible and not self.mt5.symbol_select(broker_symbol, True):
            raise RuntimeError(f"MT5 symbol_select failed for {broker_symbol}: {self.mt5.last_error()}")

    def resolve_symbol(self, preferred_symbol: str, local_symbol: str) -> str:
        if self.mt5.symbol_info(preferred_symbol) is not None:
            self.ensure_symbol(preferred_symbol)
            return preferred_symbol
        patterns = [
            f"{local_symbol}*",
            f"*{local_symbol}*",
            f"{preferred_symbol.rstrip('mcu')}*",
        ]
        seen: set[str] = set()
        for pattern in patterns:
            for symbol in self.mt5.symbols_get(pattern) or []:
                name = str(symbol.name)
                if name in seen:
                    continue
                seen.add(name)
                if name.upper().startswith(local_symbol.upper()):
                    self.ensure_symbol(name)
                    return name
        raise RuntimeError(f"MT5 symbol not found: {preferred_symbol}. No match for local symbol {local_symbol}.")

    def copy_rates(self, broker_symbol: str, local_symbol: str, timeframe: str, count: int) -> list[Candle]:
        self.ensure_symbol(broker_symbol)
        mt5_timeframe = self.mt5_timeframe(timeframe)
        rates = self.mt5.copy_rates_from_pos(broker_symbol, mt5_timeframe, 0, count)
        if rates is None:
            raise RuntimeError(f"MT5 copy_rates_from_pos failed: {self.mt5.last_error()}")
        delta = timeframe_delta(timeframe)
        candles: list[Candle] = []
        for item in rates:
            open_time = mt5_server_timestamp_to_utc(
                int(item["time"]),
                self.credentials.server_utc_offset_hours,
            )
            candles.append(
                Candle(
                    symbol=local_symbol,
                    timeframe=timeframe.upper(),
                    open_time=open_time,
                    close_time=open_time + delta,
                    open=float(item["open"]),
                    high=float(item["high"]),
                    low=float(item["low"]),
                    close=float(item["close"]),
                    volume=float(item["tick_volume"]) if "tick_volume" in item.dtype.names else None,
                    source=f"mt5:{broker_symbol}",
                )
            )
        return candles

    def place_market_order(self, request: MT5OrderRequest) -> dict[str, Any]:
        self.ensure_symbol(request.broker_symbol)
        side = request.side.lower()
        if side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        order_type = self.mt5.ORDER_TYPE_BUY if side == "buy" else self.mt5.ORDER_TYPE_SELL
        price = self.current_price_for_side(request.broker_symbol, side)
        payload = {
            "action": self.mt5.TRADE_ACTION_DEAL,
            "symbol": request.broker_symbol,
            "volume": request.volume,
            "type": order_type,
            "price": price,
            "sl": request.stop_loss,
            "tp": request.take_profit,
            "deviation": 30,
            "magic": request.magic,
            "comment": request.comment[:31],
            "type_time": self.mt5.ORDER_TIME_GTC,
            "type_filling": self.order_filling_mode(request.broker_symbol),
        }
        result = self.mt5.order_send(payload)
        if result is None:
            raise RuntimeError(f"MT5 order_send failed: {self.mt5.last_error()}")
        data = result._asdict()
        retcode = int(data.get("retcode", -1))
        if retcode != self.mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"MT5 order rejected retcode={retcode}: {data}")
        return data

    def current_price_for_side(self, broker_symbol: str, side: str) -> float:
        self.ensure_symbol(broker_symbol)
        tick = self.mt5.symbol_info_tick(broker_symbol)
        if tick is None:
            raise RuntimeError(f"MT5 symbol_info_tick failed: {self.mt5.last_error()}")
        side = side.lower()
        if side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        return float(tick.ask if side == "buy" else tick.bid)

    def get_current_spread(self, broker_symbol: str) -> float:
        """Return the current bid/ask spread in price units (e.g. USD for XAUUSD).

        Returns 0.0 if tick data is unavailable rather than raising, so callers
        can treat a missing tick as a zero spread and let other guards handle it.
        """
        self.ensure_symbol(broker_symbol)
        tick = self.mt5.symbol_info_tick(broker_symbol)
        if tick is None:
            return 0.0
        return max(0.0, float(tick.ask) - float(tick.bid))

    def get_current_quote(self, broker_symbol: str) -> dict[str, float]:
        """Return current bid, ask, and spread in price units."""
        self.ensure_symbol(broker_symbol)
        tick = self.mt5.symbol_info_tick(broker_symbol)
        if tick is None:
            raise RuntimeError(f"MT5 symbol_info_tick failed: {self.mt5.last_error()}")
        bid = float(tick.bid)
        ask = float(tick.ask)
        return {"bid": bid, "ask": ask, "spread": max(0.0, ask - bid)}

    def place_limit_order(self, request: MT5OrderRequest) -> dict[str, Any]:
        self.ensure_symbol(request.broker_symbol)
        side = request.side.lower()
        if side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        if request.entry_price is None:
            raise ValueError("entry_price is required for limit orders")
        order_type = self.mt5.ORDER_TYPE_BUY_LIMIT if side == "buy" else self.mt5.ORDER_TYPE_SELL_LIMIT
        payload = {
            "action": self.mt5.TRADE_ACTION_PENDING,
            "symbol": request.broker_symbol,
            "volume": request.volume,
            "type": order_type,
            "price": float(request.entry_price),
            "sl": request.stop_loss,
            "tp": request.take_profit,
            "deviation": 30,
            "magic": request.magic,
            "comment": request.comment[:31],
            "type_time": self.mt5.ORDER_TIME_GTC,
            "type_filling": self.order_filling_mode(request.broker_symbol),
        }
        uses_broker_expiration = False
        parsed_expiry: datetime | None = None
        if request.expires_at:
            expires_at = datetime.fromisoformat(request.expires_at.replace("Z", "+00:00"))
            if expires_at.tzinfo is None:
                raise ValueError("expires_at must include a timezone offset")
            expires_at = expires_at.astimezone(UTC)
            if expires_at <= datetime.now(UTC) + timedelta(seconds=30):
                raise ValueError("expires_at must be at least 30 seconds in the future")
            parsed_expiry = expires_at
            if self._supports_specified_expiration(request.broker_symbol):
                payload["type_time"] = self.mt5.ORDER_TIME_SPECIFIED
                payload["expiration"] = int(expires_at.timestamp())
                uses_broker_expiration = True
        result = self.mt5.order_send(payload)
        if result is None:
            raise RuntimeError(f"MT5 order_send failed: {self.mt5.last_error()}")
        data = result._asdict()
        retcode = int(data.get("retcode", -1))
        invalid_expiration = int(getattr(self.mt5, "TRADE_RETCODE_INVALID_EXPIRATION", 10022))
        fallback_is_safe = (
            parsed_expiry is not None
            and parsed_expiry > datetime.now(UTC) + timedelta(seconds=30)
            and not data.get("order")
            and not data.get("deal")
        )
        if uses_broker_expiration and retcode == invalid_expiration and fallback_is_safe:
            # Some brokers advertise ORDER_TIME_SPECIFIED for a symbol but still
            # reject short/intraday expirations. The live worker retains the
            # absolute expires_at and cancels the known pending ticket itself,
            # so retrying the rejected request once as GTC preserves the plan
            # timeout without risking a duplicate broker order.
            fallback_payload = dict(payload)
            fallback_payload["type_time"] = self.mt5.ORDER_TIME_GTC
            fallback_payload.pop("expiration", None)
            logger.warning(
                "MT5 rejected specified expiration for %s; retrying pending order as GTC",
                request.broker_symbol,
            )
            result = self.mt5.order_send(fallback_payload)
            if result is None:
                raise RuntimeError(f"MT5 order_send GTC fallback failed: {self.mt5.last_error()}")
            data = result._asdict()
            data["expiration_fallback"] = "gtc"
            retcode = int(data.get("retcode", -1))
        if retcode not in {self.mt5.TRADE_RETCODE_DONE, self.mt5.TRADE_RETCODE_PLACED}:
            raise RuntimeError(f"MT5 limit order rejected retcode={retcode}: {data}")
        return data

    def _supports_specified_expiration(self, broker_symbol: str) -> bool:
        """Return whether the broker symbol allows an exact pending-order expiry.

        MT5 exposes expiration modes as a bitmask. If the terminal cannot expose
        that property, optimistically try the specified mode; the order-send
        fallback above still handles a broker-side 10022 rejection safely.
        """
        info = self.mt5.symbol_info(broker_symbol)
        raw_mode = getattr(info, "expiration_mode", None) if info is not None else None
        if not isinstance(raw_mode, (int, float)):
            return True
        specified_flag = int(getattr(self.mt5, "SYMBOL_EXPIRATION_SPECIFIED", 4))
        return bool(int(raw_mode) & specified_flag)

    def get_account_info(self) -> dict[str, Any]:
        """Return key account metrics: balance, equity, margin, free_margin, profit."""
        info = self.mt5.account_info()
        if info is None:
            raise RuntimeError(f"MT5 account_info failed: {self.mt5.last_error()}")
        d = info._asdict()
        return {
            "balance": float(d.get("balance", 0)),
            "equity": float(d.get("equity", 0)),
            "margin": float(d.get("margin", 0)),
            "free_margin": float(d.get("margin_free", 0)),
            "profit": float(d.get("profit", 0)),
            "currency": str(d.get("currency", "USD")),
        }

    def get_symbol_contract_size(self, broker_symbol: str) -> float:
        """Return the contract size for a symbol (e.g. 100 for XAUUSD, 100000 for EURUSD)."""
        info = self.mt5.symbol_info(broker_symbol)
        if info is None:
            return 100000.0  # safe default (standard forex lot)
        return float(info.trade_contract_size)

    def get_symbol_trade_info(self, broker_symbol: str) -> dict[str, float | str | bool]:
        """Return broker trading metadata used for risk and startup validation."""
        info = self.mt5.symbol_info(broker_symbol)
        if info is None:
            raise RuntimeError(f"MT5 symbol not found: {broker_symbol}")
        data = info._asdict()
        return {
            "name": str(data.get("name") or broker_symbol),
            "visible": bool(data.get("visible")),
            "trade_contract_size": float(data.get("trade_contract_size") or 0.0),
            "volume_min": float(data.get("volume_min") or 0.01),
            "volume_max": float(data.get("volume_max") or 100.0),
            "volume_step": float(data.get("volume_step") or 0.01),
            "digits": float(data.get("digits") or 0),
            "point": float(data.get("point") or 0.0),
            "trade_tick_size": float(data.get("trade_tick_size") or 0.0),
            "trade_tick_value": float(data.get("trade_tick_value") or 0.0),
        }

    def positions_count(self, broker_symbol: str) -> int:
        positions = self.mt5.positions_get(symbol=broker_symbol)
        if positions is None:
            return 0
        return len(positions)

    def bot_order_counts(self, broker_symbol: str, *, magic: int) -> tuple[int, int]:
        """Return (open positions, pending orders) owned by this bot."""
        positions = self.mt5.positions_get(symbol=broker_symbol) or []
        orders = self.mt5.orders_get(symbol=broker_symbol) or []
        return (
            sum(1 for position in positions if int(getattr(position, "magic", 0) or 0) == magic),
            sum(1 for order in orders if int(getattr(order, "magic", 0) or 0) == magic),
        )

    def balance_change_since(self, start_utc: datetime) -> float:
        """Return all balance-changing deal components since an aware UTC time."""
        deals = self.mt5.history_deals_get(start_utc, datetime.now(UTC))
        if deals is None:
            raise RuntimeError(f"MT5 history_deals_get failed: {self.mt5.last_error()}")
        return sum(
            float(getattr(deal, "profit", 0.0) or 0.0)
            + float(getattr(deal, "commission", 0.0) or 0.0)
            + float(getattr(deal, "swap", 0.0) or 0.0)
            + float(getattr(deal, "fee", 0.0) or 0.0)
            for deal in deals
        )

    def cancel_pending_orders(self, broker_symbol: str, *, magic: int, comment: str = "weekend flatten") -> list[dict[str, Any]]:
        """Cancel pending bot orders only; manual orders are never touched."""
        self.ensure_symbol(broker_symbol)
        orders = self.mt5.orders_get(symbol=broker_symbol)
        if not orders:
            return []
        results: list[dict[str, Any]] = []
        for order in orders:
            if int(getattr(order, "magic", 0) or 0) != magic:
                continue
            payload = {
                "action": self.mt5.TRADE_ACTION_REMOVE,
                "order": int(order.ticket),
                "symbol": broker_symbol,
                "comment": comment[:31],
            }
            result = self.mt5.order_send(payload)
            if result is None:
                raise RuntimeError(f"MT5 cancel order failed: {self.mt5.last_error()}")
            data = result._asdict()
            retcode = int(data.get("retcode", -1))
            if retcode != self.mt5.TRADE_RETCODE_DONE:
                raise RuntimeError(f"MT5 cancel order rejected retcode={retcode}: {data}")
            results.append(data)
        return results

    def cancel_pending_order(self, broker_symbol: str, *, order_ticket: str, comment: str = "cancel plan") -> dict[str, Any]:
        """Cancel one known pending order without touching other bot/manual orders."""
        self.ensure_symbol(broker_symbol)
        try:
            ticket = int(order_ticket)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid pending-order ticket: {order_ticket}") from exc
        payload = {
            "action": self.mt5.TRADE_ACTION_REMOVE,
            "order": ticket,
            "symbol": broker_symbol,
            "comment": comment[:31],
        }
        result = self.mt5.order_send(payload)
        if result is None:
            raise RuntimeError(f"MT5 cancel order failed: {self.mt5.last_error()}")
        data = result._asdict()
        retcode = int(data.get("retcode", -1))
        if retcode != self.mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"MT5 cancel order rejected retcode={retcode}: {data}")
        return data

    def get_pending_order_state(self, broker_symbol: str, *, order_ticket: str) -> str | None:
        """Return the broker lifecycle state for one known pending-order ticket.

        ``pending`` means the order still exists in the active order book.
        Terminal history is consulted only after the order disappears so a fill
        is never mistaken for a cancellation. ``None`` deliberately means that
        MT5 has not exposed enough information yet; callers must retry instead
        of guessing a terminal state.
        """
        self.ensure_symbol(broker_symbol)
        try:
            ticket = int(order_ticket)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid pending-order ticket: {order_ticket}") from exc

        active_orders = self.mt5.orders_get(ticket=ticket)
        if active_orders is None:
            return None
        if any(int(getattr(order, "ticket", 0) or 0) == ticket for order in active_orders):
            return "pending"

        historical_orders = self.mt5.history_orders_get(ticket=ticket)
        if historical_orders is None:
            return None
        matching = [order for order in historical_orders if int(getattr(order, "ticket", 0) or 0) == ticket]
        if not matching:
            return None
        order = max(matching, key=lambda item: int(getattr(item, "time_done_msc", 0) or getattr(item, "time_done", 0) or 0))
        state = int(getattr(order, "state", -1))
        if state == int(self.mt5.ORDER_STATE_FILLED):
            return "filled"
        terminal_states = {
            int(self.mt5.ORDER_STATE_CANCELED),
            int(self.mt5.ORDER_STATE_EXPIRED),
            int(self.mt5.ORDER_STATE_REJECTED),
        }
        if state in terminal_states:
            return "cancelled"
        return None

    def close_open_positions(self, broker_symbol: str, *, magic: int | None, comment: str = "weekend flatten") -> list[dict[str, Any]]:
        """Close positions at market; magic=None explicitly includes manual positions."""
        self.ensure_symbol(broker_symbol)
        positions = self.mt5.positions_get(symbol=broker_symbol)
        if not positions:
            return []
        results: list[dict[str, Any]] = []
        filling_mode = self.order_filling_mode(broker_symbol)
        for position in positions:
            if magic is not None and int(getattr(position, "magic", 0) or 0) != magic:
                continue
            side = "sell" if int(position.type) == self.mt5.POSITION_TYPE_BUY else "buy"
            order_type = self.mt5.ORDER_TYPE_SELL if side == "sell" else self.mt5.ORDER_TYPE_BUY
            price = self.current_price_for_side(broker_symbol, side)
            payload = {
                "action": self.mt5.TRADE_ACTION_DEAL,
                "symbol": broker_symbol,
                "volume": float(position.volume),
                "type": order_type,
                "position": int(position.ticket),
                "price": price,
                "deviation": 30,
                "magic": magic or 0,
                "comment": comment[:31],
                "type_time": self.mt5.ORDER_TIME_GTC,
                "type_filling": filling_mode,
            }
            result = self.mt5.order_send(payload)
            if result is None:
                raise RuntimeError(f"MT5 close position failed: {self.mt5.last_error()}")
            data = result._asdict()
            retcode = int(data.get("retcode", -1))
            if retcode != self.mt5.TRADE_RETCODE_DONE:
                raise RuntimeError(f"MT5 close position rejected retcode={retcode}: {data}")
            results.append(data)
        return results

    def get_open_positions(self, broker_symbol: str) -> list[dict[str, Any]]:
        """Return open positions for a symbol with the fields needed by the risk manager."""
        positions = self.mt5.positions_get(symbol=broker_symbol)
        if not positions:
            return []
        result: list[dict[str, Any]] = []
        for position in positions:
            side = "buy" if int(position.type) == self.mt5.POSITION_TYPE_BUY else "sell"
            result.append(
                {
                    "ticket": str(position.ticket),
                    "side": side,
                    "volume": float(position.volume),
                    "price_open": float(position.price_open),
                    "sl": float(getattr(position, "sl", 0.0) or 0.0),
                    "tp": float(getattr(position, "tp", 0.0) or 0.0),
                }
            )
        return result

    def close_partial_position(
        self,
        broker_symbol: str,
        *,
        position_ticket: str,
        side: str,
        volume: float,
        magic: int,
        comment: str = "partial tp",
    ) -> dict[str, Any]:
        """Close part of an open position at market and return the MT5 response."""
        self.ensure_symbol(broker_symbol)
        close_side = "sell" if side.lower() == "buy" else "buy"
        order_type = self.mt5.ORDER_TYPE_SELL if close_side == "sell" else self.mt5.ORDER_TYPE_BUY
        price = self.current_price_for_side(broker_symbol, close_side)
        payload = {
            "action": self.mt5.TRADE_ACTION_DEAL,
            "symbol": broker_symbol,
            "volume": float(volume),
            "type": order_type,
            "position": int(position_ticket),
            "price": price,
            "deviation": 30,
            "magic": magic,
            "comment": comment[:31],
            "type_time": self.mt5.ORDER_TIME_GTC,
            "type_filling": self.order_filling_mode(broker_symbol),
        }
        result = self.mt5.order_send(payload)
        if result is None:
            raise RuntimeError(f"MT5 partial close failed: {self.mt5.last_error()}")
        data = result._asdict()
        retcode = int(data.get("retcode", -1))
        if retcode != self.mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"MT5 partial close rejected retcode={retcode}: {data}")
        return data

    def modify_position_sltp(
        self,
        broker_symbol: str,
        *,
        position_ticket: str,
        stop_loss: float,
        take_profit: float,
        magic: int,
        comment: str = "move sl be",
    ) -> dict[str, Any]:
        """Modify SL/TP on an open position."""
        self.ensure_symbol(broker_symbol)
        payload = {
            "action": self.mt5.TRADE_ACTION_SLTP,
            "symbol": broker_symbol,
            "position": int(position_ticket),
            "sl": float(stop_loss),
            "tp": float(take_profit),
            "magic": magic,
            "comment": comment[:31],
        }
        result = self.mt5.order_send(payload)
        if result is None:
            raise RuntimeError(f"MT5 modify SL/TP failed: {self.mt5.last_error()}")
        data = result._asdict()
        retcode = int(data.get("retcode", -1))
        if retcode != self.mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"MT5 modify SL/TP rejected retcode={retcode}: {data}")
        return data

    def get_open_position_tickets(self, broker_symbol: str) -> set[str]:
        """Return ticket IDs of all currently open positions for the symbol."""
        positions = self.mt5.positions_get(symbol=broker_symbol)
        if not positions:
            return set()
        return {str(p.ticket) for p in positions}

    def get_closed_deal_for_position(self, position_ticket: str) -> dict[str, Any] | None:
        """Find the closing deal for a position identified by its opening ticket.

        MT5 links all deals to a position via position_id. The closing deal
        has entry == DEAL_ENTRY_OUT (1). Returns None if not yet closed or
        history is unavailable.
        """
        try:
            ticket = int(position_ticket)
        except (TypeError, ValueError):
            return None
        deals = self.mt5.history_deals_get(position=ticket)
        if not deals:
            return None
        close_deals: list[Any] = []
        for deal in deals:
            if int(deal.entry) == 1:  # DEAL_ENTRY_OUT
                close_deals.append(deal)
        if not close_deals:
            return None
        total_volume = sum(float(deal.volume) for deal in close_deals)
        weighted_price = (
            sum(float(deal.price) * float(deal.volume) for deal in close_deals) / total_volume
            if total_volume > 0
            else float(close_deals[-1].price)
        )
        latest_deal = max(close_deals, key=lambda item: int(item.time))
        close_time = mt5_server_timestamp_to_utc(
            int(latest_deal.time),
            self.credentials.server_utc_offset_hours,
        )
        # MT5 can charge commission on both DEAL_ENTRY_IN and DEAL_ENTRY_OUT.
        # Profit/close price belong to exit deals, but position-level costs must
        # include every deal or the stored net P&L misses the opening charge.
        return {
            "price": weighted_price,
            "profit": sum(float(deal.profit) for deal in close_deals),
            "swap": sum(float(getattr(deal, "swap", 0) or 0) for deal in deals),
            "commission": sum(float(getattr(deal, "commission", 0) or 0) for deal in deals),
            "fee": sum(float(getattr(deal, "fee", 0) or 0) for deal in deals),
            "time_iso": close_time.replace(microsecond=0).isoformat(),
            "volume": total_volume,
            "deal_ticket": ",".join(str(deal.ticket) for deal in close_deals),
        }

    def mt5_timeframe(self, timeframe: str) -> int:
        key = timeframe.upper()
        mapping = {
            "M1": self.mt5.TIMEFRAME_M1,
            "M5": self.mt5.TIMEFRAME_M5,
            "M15": self.mt5.TIMEFRAME_M15,
            "M30": self.mt5.TIMEFRAME_M30,
            "H1": self.mt5.TIMEFRAME_H1,
            "H4": self.mt5.TIMEFRAME_H4,
            "D1": self.mt5.TIMEFRAME_D1,
        }
        if key not in mapping:
            raise ValueError(f"Unsupported MT5 timeframe: {timeframe}")
        return mapping[key]

    def order_filling_mode(self, broker_symbol: str) -> int:
        info = self.mt5.symbol_info(broker_symbol)
        # filling_mode is a bitmask from symbol_info:
        #   bit 0 (value 1) = SYMBOL_FILLING_FOK supported → use ORDER_FILLING_FOK
        #   bit 1 (value 2) = SYMBOL_FILLING_IOC supported → use ORDER_FILLING_IOC
        # These are *different* constant families from ORDER_FILLING_* so equality
        # comparisons with ORDER_FILLING_FOK / ORDER_FILLING_RETURN were incorrect.
        filling = getattr(info, "filling_mode", None) if info is not None else None
        if filling is None:
            return self.mt5.ORDER_FILLING_IOC  # safe default
        if filling & 1:  # SYMBOL_FILLING_FOK supported
            return self.mt5.ORDER_FILLING_FOK
        if filling & 2:  # SYMBOL_FILLING_IOC supported
            return self.mt5.ORDER_FILLING_IOC
        return self.mt5.ORDER_FILLING_RETURN
