from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


TRUE_VALUES = {"1", "true", "yes", "on", "y"}


@dataclass(frozen=True)
class RuntimeEnv:
    mt5_login: int | None
    mt5_password: str | None
    mt5_server: str | None
    mt5_path: str | None
    mt5_symbol: str
    mt5_magic: int
    telegram_token: str | None
    telegram_chat_id: str | None
    execution_enabled: bool
    live_order_volume: float  # fallback fixed lot; ignored when risk_per_trade_pct is set
    max_open_positions_per_symbol: int
    max_trades_per_day: int
    poll_seconds: float
    poll_at_seconds: tuple[int, ...]
    max_entry_drift_price: float
    max_spread_price: float
    live_sync_candles: bool
    live_run_detectors: bool
    live_evaluate_intrabar: bool
    chart_url_base: str
    # Account identity — human-readable label shown in dashboard; unique per MT5 account
    account_label: str            # e.g. "Exness Personal", "FTMO Challenge #1"
    # Risk management
    account_profile: str          # "personal" | "ftmo_challenge" | "the5ers"
    account_balance_scale: float | None  # e.g. Exness cent USC -> USD risk-equivalent uses 0.01
    risk_per_trade_pct: float | None  # % of balance per trade; None → use profile default
    # Auth
    secret_key: str               # JWT signing key — must be set in .env
    admin_username: str           # login username (default: admin)
    admin_password_hash: str | None  # bcrypt hash — set via: semi-bot hash-password
    # CORS — comma-separated origins allowed to call the API
    allowed_origins: list[str]
    # Environment — "development" | "production"
    environment: str
    # Weekend risk controls
    weekend_flatten_enabled: bool = True
    weekend_flatten_timezone: str = "America/New_York"
    weekend_no_new_trades_time: str = "12:00"
    weekend_flatten_time: str = "15:30"
    partial_take_profit_enabled: bool = True
    partial_take_profit_r: float = 1.25
    partial_take_profit_fraction: float = 0.5
    partial_take_profit_be_buffer: float = 0.0
    # Offset of broker-server wall-clock timestamps from UTC. Some MT5
    # terminals encode deal/candle epochs using server time rather than UTC.
    mt5_server_utc_offset_hours: float = 0.0
    # FTMO daily result resets at Prague midnight (CEST/CET). Set the original
    # account size so daily_profit_pct maps exactly to the FTMO 5% objective.
    account_initial_balance: float | None = None
    daily_reset_timezone: str = "Europe/Prague"
    # FTMO news compliance applies only to funded Standard accounts. Evaluation
    # covers Challenge/Verification; Swing is explicitly exempt from the rule.
    ftmo_phase: str = "evaluation"
    ftmo_account_type: str = "standard"
    ftmo_news_buffer_minutes: int = 5
    ftmo_news_calendar_max_age_hours: int = 36
    ftmo_news_flatten_enabled: bool = True
    manual_trade_guard_seconds: float = 1.0


def load_dotenv(path: Path | str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_runtime_env(dotenv_path: Path | str = ".env") -> RuntimeEnv:
    load_dotenv(dotenv_path)
    return RuntimeEnv(
        mt5_login=env_int("MT5_LOGIN"),
        mt5_password=env_text("MT5_PASSWORD"),
        mt5_server=env_text("MT5_SERVER"),
        mt5_path=env_text("MT5_PATH"),
        mt5_symbol=env_text("MT5_SYMBOL", "XAUUSDm") or "XAUUSDm",
        mt5_magic=env_int("MT5_MAGIC", 260612) or 260612,
        mt5_server_utc_offset_hours=env_float("MT5_SERVER_UTC_OFFSET_HOURS", 0.0) or 0.0,
        telegram_token=env_text("TELEGRAM_TOKEN"),
        telegram_chat_id=env_text("TELEGRAM_CHAT_ID"),
        execution_enabled=env_bool("EXECUTION_ENABLED", False),
        live_order_volume=env_float("LIVE_ORDER_VOLUME", 0.01) or 0.01,
        max_open_positions_per_symbol=env_int("MAX_OPEN_POSITIONS_PER_SYMBOL", 1) or 1,
        max_trades_per_day=env_int("MAX_TRADES_PER_DAY", 10) or 10,
        poll_seconds=env_float("LIVE_POLL_SECONDS", 15.0) or 15.0,
        poll_at_seconds=env_seconds_tuple("LIVE_POLL_AT_SECONDS", (1, 16, 31, 46)),
        max_entry_drift_price=env_float("MAX_ENTRY_DRIFT_PRICE", 2.0) or 0.0,
        max_spread_price=env_float("MAX_SPREAD_PRICE", 2.0) or 0.0,
        live_sync_candles=env_bool("LIVE_SYNC_CANDLES", True),
        live_run_detectors=env_bool("LIVE_RUN_DETECTORS", True),
        live_evaluate_intrabar=env_bool("LIVE_EVALUATE_INTRABAR", False),
        chart_url_base=env_text("CHART_URL_BASE", "http://127.0.0.1:5173") or "http://127.0.0.1:5173",
        account_label=env_text("ACCOUNT_LABEL", "Default") or "Default",
        account_profile=env_text("ACCOUNT_PROFILE", "personal") or "personal",
        account_balance_scale=env_float("ACCOUNT_BALANCE_SCALE"),
        risk_per_trade_pct=env_float("RISK_PER_TRADE_PCT"),
        secret_key=env_text("SECRET_KEY", "") or "",
        admin_username=env_text("ADMIN_USERNAME", "admin") or "admin",
        admin_password_hash=env_text("ADMIN_PASSWORD_HASH"),
        allowed_origins=env_list(
            "ALLOWED_ORIGINS",
            ["http://127.0.0.1:5173", "http://localhost:5173", "http://127.0.0.1:8765", "http://localhost:8765"],
        ),
        environment=env_text("ENVIRONMENT", "development") or "development",
        weekend_flatten_enabled=env_bool("WEEKEND_FLATTEN_ENABLED", True),
        weekend_flatten_timezone=env_text("WEEKEND_FLATTEN_TIMEZONE", "America/New_York") or "America/New_York",
        weekend_no_new_trades_time=env_text("WEEKEND_NO_NEW_TRADES_TIME", "12:00") or "12:00",
        weekend_flatten_time=env_text("WEEKEND_FLATTEN_TIME", "15:30") or "15:30",
        partial_take_profit_enabled=env_bool("PARTIAL_TAKE_PROFIT_ENABLED", True),
        partial_take_profit_r=env_float("PARTIAL_TAKE_PROFIT_R", 1.25) or 1.25,
        partial_take_profit_fraction=env_float("PARTIAL_TAKE_PROFIT_FRACTION", 0.5) or 0.5,
        partial_take_profit_be_buffer=env_float("PARTIAL_TAKE_PROFIT_BE_BUFFER", 0.0) or 0.0,
        account_initial_balance=env_float("ACCOUNT_INITIAL_BALANCE"),
        daily_reset_timezone=env_text("DAILY_RESET_TIMEZONE", "Europe/Prague") or "Europe/Prague",
        ftmo_phase=env_text("FTMO_PHASE", "evaluation") or "evaluation",
        ftmo_account_type=env_text("FTMO_ACCOUNT_TYPE", "standard") or "standard",
        ftmo_news_buffer_minutes=env_int("FTMO_NEWS_BUFFER_MINUTES", 5) or 5,
        ftmo_news_calendar_max_age_hours=env_int("FTMO_NEWS_CALENDAR_MAX_AGE_HOURS", 36) or 36,
        ftmo_news_flatten_enabled=env_bool("FTMO_NEWS_FLATTEN_ENABLED", True),
        manual_trade_guard_seconds=max(env_float("MANUAL_TRADE_GUARD_SECONDS", 1.0) or 1.0, 0.25),
    )


def is_production(env: RuntimeEnv) -> bool:
    return env.environment.lower() == "production"


def env_text(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


def env_int(name: str, default: int | None = None) -> int | None:
    value = env_text(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"{name} must be an integer") from None


def env_float(name: str, default: float | None = None) -> float | None:
    value = env_text(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        raise ValueError(f"{name} must be a number") from None


def env_bool(name: str, default: bool = False) -> bool:
    value = env_text(name)
    if value is None:
        return default
    return value.strip().lower() in TRUE_VALUES


def env_list(name: str, default: list[str]) -> list[str]:
    """Parse a comma-separated env variable into a list of strings."""
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


def env_seconds_tuple(name: str, default: tuple[int, ...]) -> tuple[int, ...]:
    """Parse comma-separated second marks within a minute, e.g. 1,16,45."""
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    seconds: list[int] = []
    for raw in value.split(","):
        item = raw.strip()
        if not item:
            continue
        try:
            second = int(item)
        except ValueError:
            raise ValueError(f"{name} must contain integer seconds") from None
        if second < 0 or second > 59:
            raise ValueError(f"{name} values must be between 0 and 59")
        seconds.append(second)
    return tuple(sorted(set(seconds))) or default
