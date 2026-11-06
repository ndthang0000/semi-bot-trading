from __future__ import annotations

import json
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .chart import CHART_INDICATOR_WARMUP_CANDLES, build_chart_payload, load_chart_indicator_candles
from .config import AppConfig
from .db import connect, init_db


WEB_ROOT = Path(__file__).resolve().parent.parent / "web"


def first_query_value(query: dict[str, list[str]], key: str, default: str | None = None) -> str | None:
    values = query.get(key)
    if not values:
        return default
    return values[0]


def bool_query_value(query: dict[str, list[str]], key: str, default: bool = False) -> bool:
    value = first_query_value(query, key)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def int_query_value(query: dict[str, list[str]], key: str, default: int) -> int:
    value = first_query_value(query, key)
    if value is None:
        return default
    return int(value)


def build_chart_payload_from_query(config: AppConfig, query: dict[str, list[str]]) -> dict:
    symbol = first_query_value(query, "symbol", config.symbol) or config.symbol
    timeframe = first_query_value(query, "timeframe", "M15") or "M15"
    limit = int_query_value(query, "limit", 300)
    start = first_query_value(query, "start")
    end = first_query_value(query, "end")
    active_zones_only = bool_query_value(query, "active_zones_only")

    with connect(config.database) as conn:
        init_db(conn)
        payload = build_chart_payload(
            conn,
            symbol=symbol,
            timeframe=timeframe,
            limit=limit,
            start=start,
            end=end,
            active_zones_only=active_zones_only,
            structure_timeframe=config.bias.timeframe,
        )
        payload["layers"]["indicator_candles"] = load_chart_indicator_candles(
            conn,
            symbol,
            timeframe,
            payload["layers"]["candles"],
            CHART_INDICATOR_WARMUP_CANDLES,
        )
        return payload


class TradingChartRequestHandler(SimpleHTTPRequestHandler):
    config: AppConfig

    def __init__(self, *args, config: AppConfig, **kwargs) -> None:
        self.config = config
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/chart":
            self.handle_chart_api(parsed.query)
            return
        if parsed.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def handle_chart_api(self, raw_query: str) -> None:
        try:
            payload = build_chart_payload_from_query(self.config, parse_qs(raw_query))
            self.send_json(payload)
        except Exception as exc:  # pragma: no cover - exercised through manual local server use
            self.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def run_chart_server(config: AppConfig, host: str, port: int) -> None:
    handler = partial(TradingChartRequestHandler, config=config)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Chart UI: http://{host}:{port}")
    print(f"Database: {config.database}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping chart server...")
    finally:
        server.server_close()
