"""Configurable UTC entry windows; end boundaries are exclusive."""
from datetime import datetime, timedelta, timezone

SESSION_CATALOG = (
    ("asian", "Asian", "00:00", "07:00"),
    ("london", "London", "07:00", "12:00"),
    ("london_ny", "London–NY", "12:00", "17:00"),
    ("new_york", "New York", "17:00", "21:00"),
    ("off_hours", "Off-hours", "21:00", "24:00"),
)
SESSION_NAMES = tuple(item[0] for item in SESSION_CATALOG)
STANDARD_SESSION_WINDOWS = tuple((name, True, start, end) for name, _label, start, end in SESSION_CATALOG)


def session_catalog_api() -> list[dict[str, str]]:
    return [
        {"value": name, "label": label, "start_utc": start, "end_utc": end}
        for name, label, start, end in SESSION_CATALOG
    ]


def session_name(timestamp: str) -> str:
    """Return the fixed UTC session containing a candle open timestamp."""
    moment = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        raise ValueError("Timestamp requires timezone")
    minute = moment.astimezone(timezone.utc).hour * 60 + moment.minute
    for name, _label, start, end in SESSION_CATALOG:
        sh, sm = map(int, start.split(":"))
        eh, em = map(int, end.split(":"))
        begin_minute, finish_minute = sh * 60 + sm, eh * 60 + em
        if begin_minute <= minute < finish_minute:
            return name
    raise ValueError(f"No trading session for timestamp: {timestamp}")


def session_label(name: str) -> str:
    for value, label, _start, _end in SESSION_CATALOG:
        if value == name:
            return label
    return name


def session_end(config, timestamp: str) -> datetime | None:
    return sessions_end(config.zone_reaction_v2_sessions, timestamp)


def selected_session_end(selected: list[str] | tuple[str, ...], timestamp: str) -> datetime | None:
    enabled = set(selected)
    return sessions_end(tuple((name, name in enabled, start, end) for name, _, start, end in STANDARD_SESSION_WINDOWS), timestamp)


def sessions_end(sessions, timestamp: str) -> datetime | None:
    now = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    daily_ranges = []
    for _name, enabled, start, end in sessions:
        if not enabled:
            continue
        sh, sm = map(int, start.split(":"))
        eh, em = map(int, end.split(":"))
        begin_minute, finish_minute = sh * 60 + sm, eh * 60 + em
        if finish_minute <= begin_minute:
            daily_ranges.extend(((begin_minute, 1440), (0, finish_minute)))
        else:
            daily_ranges.append((begin_minute, finish_minute))
    covered_until = 0
    for begin_minute, finish_minute in sorted(daily_ranges):
        if begin_minute > covered_until:
            break
        covered_until = max(covered_until, finish_minute)
    if covered_until >= 1440:
        return datetime.max.replace(tzinfo=timezone.utc)

    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    intervals = []
    for _name, enabled, start, end in sessions:
        if not enabled:
            continue
        sh, sm = map(int, start.split(":"))
        eh, em = map(int, end.split(":"))
        for day_offset in (-1, 0, 1):
            day = midnight + timedelta(days=day_offset)
            begin = day + timedelta(hours=sh, minutes=sm)
            finish = day + timedelta(hours=eh, minutes=em)
            if finish <= begin:
                finish += timedelta(days=1)
            intervals.append((begin, finish))

    merged = []
    for begin, finish in sorted(intervals):
        if merged and begin <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], finish))
        else:
            merged.append((begin, finish))
    for begin, finish in merged:
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
