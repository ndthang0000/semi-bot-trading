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
    live_evaluate_intrabar: bool
    chart_url_base: str
    # Account identity — human-readable label shown in dashboard; unique per MT5 account
    account_label: str            # e.g. "Exness Personal", "FTMO Challenge #1"
    # Risk management
    account_profile: str          # "personal" | "ftmo_challenge" | "the5ers"
    risk_per_trade_pct: float | None  # % of balance per trade; None → use profile default
    # Auth
    secret_key: str               # JWT signing key — must be set in .env
    admin_username: str           # login username (default: admin)
    admin_password_hash: str | None  # bcrypt hash — set via: semi-bot hash-password
    # CORS — comma-separated origins allowed to call the API
    allowed_origins: list[str]
    # Environment — "development" | "production"
    environment: str


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
        telegram_token=env_text("TELEGRAM_TOKEN"),
        telegram_chat_id=env_text("TELEGRAM_CHAT_ID"),
        execution_enabled=env_bool("EXECUTION_ENABLED", False),
        live_order_volume=env_float("LIVE_ORDER_VOLUME", 0.01) or 0.01,
        max_open_positions_per_symbol=env_int("MAX_OPEN_POSITIONS_PER_SYMBOL", 1) or 1,
        max_trades_per_day=env_int("MAX_TRADES_PER_DAY", 10) or 10,
        poll_seconds=env_float("LIVE_POLL_SECONDS", 15.0) or 15.0,
        live_evaluate_intrabar=env_bool("LIVE_EVALUATE_INTRABAR", False),
        chart_url_base=env_text("CHART_URL_BASE", "http://127.0.0.1:5173") or "http://127.0.0.1:5173",
        account_label=env_text("ACCOUNT_LABEL", "Default") or "Default",
        account_profile=env_text("ACCOUNT_PROFILE", "personal") or "personal",
        risk_per_trade_pct=env_float("RISK_PER_TRADE_PCT"),
        secret_key=env_text("SECRET_KEY", "") or "",
        admin_username=env_text("ADMIN_USERNAME", "admin") or "admin",
        admin_password_hash=env_text("ADMIN_PASSWORD_HASH"),
        allowed_origins=env_list(
            "ALLOWED_ORIGINS",
            ["http://127.0.0.1:5173", "http://localhost:5173", "http://127.0.0.1:8765", "http://localhost:8765"],
        ),
        environment=env_text("ENVIRONMENT", "development") or "development",
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
