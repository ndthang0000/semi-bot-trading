from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .candles import Candle
from .timeframes import timeframe_delta


@dataclass(frozen=True)
class MT5Credentials:
    login: int
    password: str
    server: str
    path: str | None = None


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
            open_time = datetime.fromtimestamp(int(item["time"]), tz=UTC)
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
        result = self.mt5.order_send(payload)
        if result is None:
            raise RuntimeError(f"MT5 order_send failed: {self.mt5.last_error()}")
        data = result._asdict()
        retcode = int(data.get("retcode", -1))
        if retcode not in {self.mt5.TRADE_RETCODE_DONE, self.mt5.TRADE_RETCODE_PLACED}:
            raise RuntimeError(f"MT5 limit order rejected retcode={retcode}: {data}")
        return data

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

    def positions_count(self, broker_symbol: str) -> int:
        positions = self.mt5.positions_get(symbol=broker_symbol)
        if positions is None:
            return 0
        return len(positions)

    def cancel_pending_orders(self, broker_symbol: str, *, comment: str = "weekend flatten") -> list[dict[str, Any]]:
        """Cancel all pending orders for a symbol and return MT5 responses."""
        self.ensure_symbol(broker_symbol)
        orders = self.mt5.orders_get(symbol=broker_symbol)
        if not orders:
            return []
        results: list[dict[str, Any]] = []
        for order in orders:
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

    def close_open_positions(self, broker_symbol: str, *, magic: int, comment: str = "weekend flatten") -> list[dict[str, Any]]:
        """Close all open positions for a symbol at market and return MT5 responses."""
        self.ensure_symbol(broker_symbol)
        positions = self.mt5.positions_get(symbol=broker_symbol)
        if not positions:
            return []
        results: list[dict[str, Any]] = []
        filling_mode = self.order_filling_mode(broker_symbol)
        for position in positions:
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
                "magic": magic,
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
        for deal in deals:
            if int(deal.entry) == 1:  # DEAL_ENTRY_OUT
                close_time = datetime.fromtimestamp(int(deal.time), tz=UTC)
                return {
                    "price": float(deal.price),
                    "profit": float(deal.profit),
                    "swap": float(getattr(deal, "swap", 0) or 0),
                    "commission": float(getattr(deal, "commission", 0) or 0),
                    "time_iso": close_time.replace(microsecond=0).isoformat(),
                    "volume": float(deal.volume),
                    "deal_ticket": str(deal.ticket),
                }
        return None

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
