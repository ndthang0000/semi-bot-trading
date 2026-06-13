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


@dataclass(frozen=True)
class MT5OrderRequest:
    broker_symbol: str
    side: str
    volume: float
    stop_loss: float
    take_profit: float
    comment: str
    magic: int


class MT5BrokerClient:
    def __init__(self, credentials: MT5Credentials) -> None:
        try:
            import MetaTrader5 as mt5
        except ImportError as exc:
            raise RuntimeError("MetaTrader5 package is not installed. Run: pip install MetaTrader5") from exc
        self.mt5 = mt5
        self.credentials = credentials

    def connect(self) -> None:
        ok = self.mt5.initialize(
            login=self.credentials.login,
            password=self.credentials.password,
            server=self.credentials.server,
        )
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
        tick = self.mt5.symbol_info_tick(request.broker_symbol)
        if tick is None:
            raise RuntimeError(f"MT5 symbol_info_tick failed: {self.mt5.last_error()}")
        side = request.side.lower()
        if side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        order_type = self.mt5.ORDER_TYPE_BUY if side == "buy" else self.mt5.ORDER_TYPE_SELL
        price = float(tick.ask if side == "buy" else tick.bid)
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

    def positions_count(self, broker_symbol: str) -> int:
        positions = self.mt5.positions_get(symbol=broker_symbol)
        if positions is None:
            return 0
        return len(positions)

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
        filling = getattr(info, "filling_mode", None)
        if filling == self.mt5.ORDER_FILLING_FOK:
            return self.mt5.ORDER_FILLING_FOK
        if filling == self.mt5.ORDER_FILLING_RETURN:
            return self.mt5.ORDER_FILLING_RETURN
        return self.mt5.ORDER_FILLING_IOC
