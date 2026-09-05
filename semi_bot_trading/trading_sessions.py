"""Configurable UTC entry windows; end boundaries are exclusive."""
from datetime import datetime, timedelta, timezone


def session_end(config, timestamp: str) -> datetime | None:
    now = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    for _name, enabled, start, end in config.zone_reaction_v2_sessions:
        if not enabled:
            continue
        sh, sm = map(int, start.split(":"))
        eh, em = map(int, end.split(":"))
        begin = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
        finish = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(hours=eh, minutes=em)
        if finish <= begin:
            finish += timedelta(days=1)
        if now < begin:
            begin -= timedelta(days=1)
            finish -= timedelta(days=1)
        if begin <= now < finish:
            return finish
    return None


def parse_sessions(raw):
    result = []
    for name, item in raw.items():
        start, end = str(item["start_utc"]), str(item["end_utc"])
        for value, is_end in ((start, False), (end, True)):
            parts = value.split(":")
            if len(parts) != 2:
                raise ValueError(f"Invalid session time: {value}")
            h, m = map(int, parts)
            if not (0 <= h < 24 and 0 <= m < 60) and not (is_end and h == 24 and m == 0):
                raise ValueError(f"Invalid session time: {value}")
        if start == end:
            raise ValueError(f"Session {name} must have distinct start/end")
        result.append((name, bool(item.get("enabled", False)), start, end))
    return tuple(result)
