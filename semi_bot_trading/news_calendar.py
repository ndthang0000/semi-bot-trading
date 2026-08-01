"""Economic calendar — ForexFactory feed parser and news blackout logic.

Only USD High-impact events that materially affect XAUUSD are stored.

Tiers
-----
Tier 1 — Tin Đỏ Tối Cao  : blackout ±30 min  (NFP, FOMC rate, CPI, GDP)
Tier 2 — Tin Đỏ Thường   : blackout ±15 min  (PCE, PPI, Retail Sales, ISM, …)
Tier 3 / None             : ignored (spread guard handles these)

The Fair Economy XML timestamps are UTC.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as _tz
UTC = _tz.utc
from sqlite3 import Connection
from typing import Any
from urllib.request import Request, urlopen
from xml.etree import ElementTree

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Currencies that move XAUUSD
# ---------------------------------------------------------------------------

AFFECTED_CURRENCIES: set[str] = {"USD"}

# ---------------------------------------------------------------------------
# Tier keyword lists  (matched case-insensitively against event title)
# ---------------------------------------------------------------------------

# Tier 1 — ±30 min blackout
_TIER1_PATTERNS: list[re.Pattern[str]] = [re.compile(p, re.IGNORECASE) for p in [
    r"(?<!adp\s)non.?farm\s+(payroll|employment\s+change)",
    r"\bnfp\b",
    r"fomc statement",
    r"federal funds rate",
    r"fed funds rate",
    r"\bcpi\s+(m/m|y/y)\b",
    r"\bcore cpi\s+m/m\b",
    r"\b(flash|advance|prelim(?:inary)?|final)\s+gdp\s+q/q\b",
    r"fomc\s+rate\s+decision",
    r"interest rate\s+decision",
]]

# Tier 2 — ±15 min blackout
_TIER2_PATTERNS: list[re.Pattern[str]] = [re.compile(p, re.IGNORECASE) for p in [
    r"\bcore pce\b",
    r"\bpce price index\b",
    r"\bppi\s+m/m\b",
    r"\bcore ppi\b",
    r"\bretail sales\b",
    r"\bism\s+(manufacturing|services|non.manufacturing)\b",
    r"\badp non.?farm\b",
    r"\bjolts\b",
    r"\bunemployment rate\b",
    r"\baverage hourly earnings\b",
]]

_BLACKOUT_MINUTES: dict[int, tuple[int, int]] = {
    1: (30, 30),
    2: (15, 15),
}

# ---------------------------------------------------------------------------
# ForexFactory feed URLs
# ---------------------------------------------------------------------------

_FF_URLS = [
    "https://nfs.faireconomy.media/ff_calendar_thisweek.xml",
    "https://nfs.faireconomy.media/ff_calendar_nextweek.xml",
]

_FF_CALENDAR_URL = "https://www.forexfactory.com/calendar"

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class NewsEvent:
    id: str
    title: str
    country: str
    impact: str
    tier: int | None
    scheduled_at: datetime
    blackout_before_min: int
    blackout_after_min: int
    forecast: str | None
    previous: str | None
    url: str | None
    fetched_at: datetime

    @property
    def blackout_start(self) -> datetime:
        return self.scheduled_at - timedelta(minutes=self.blackout_before_min)

    @property
    def blackout_end(self) -> datetime:
        return self.scheduled_at + timedelta(minutes=self.blackout_after_min)


# ---------------------------------------------------------------------------
# Tier classification
# ---------------------------------------------------------------------------


def classify_tier(title: str, country: str, impact: str) -> int | None:
    """Return 1, 2, or None.

    Only High-impact USD events are eligible. Medium/Low → None regardless of title.
    """
    if country not in AFFECTED_CURRENCIES:
        return None
    if impact.lower() != "high":
        return None
    for pattern in _TIER1_PATTERNS:
        if pattern.search(title):
            return 1
    for pattern in _TIER2_PATTERNS:
        if pattern.search(title):
            return 2
    return None


# ---------------------------------------------------------------------------
# XML fetch and parse
# ---------------------------------------------------------------------------


def _fetch_xml(url: str, timeout: float = 15.0) -> str:
    req = Request(url, headers={"User-Agent": "semi-bot-trading/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return raw.decode("windows-1252", errors="replace")


def _parse_ff_datetime(date_str: str, time_str: str) -> datetime | None:
    """Parse ForexFactory date (06-25-2026) and time (12:30pm) to UTC datetime.

    The nfs.faireconomy.media XML feed publishes UTC clock values. For example,
    a BEA 08:30 EDT release is represented as 12:30pm in the feed. Treating the
    value as Eastern would shift summer releases four hours late.
    """
    date_str = date_str.strip()
    time_str = time_str.strip().lower()
    if not time_str or time_str in {"all day", "tentative", ""}:
        return None
    try:
        dt_naive = datetime.strptime(f"{date_str} {time_str}", "%m-%d-%Y %I:%M%p")
    except ValueError:
        return None
    return dt_naive.replace(tzinfo=UTC)


def _event_id(title: str, country: str, scheduled_at: datetime) -> str:
    raw = f"{title}|{country}|{scheduled_at.isoformat()}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _parse_ff_xml(xml_text: str, fetched_at: datetime) -> list[NewsEvent]:
    events: list[NewsEvent] = []
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        logger.warning("FF XML parse error: %s", exc)
        return events

    for elem in root.findall("event"):
        title = (elem.findtext("title") or "").strip()
        country = (elem.findtext("country") or "").strip()
        impact = (elem.findtext("impact") or "").strip()
        date_str = (elem.findtext("date") or "").strip()
        time_str = (elem.findtext("time") or "").strip()
        forecast = (elem.findtext("forecast") or "").strip() or None
        previous = (elem.findtext("previous") or "").strip() or None
        url = (elem.findtext("url") or "").strip() or _FF_CALENDAR_URL

        tier = classify_tier(title, country, impact)
        if tier is None:
            continue  # not relevant for XAUUSD

        scheduled_at = _parse_ff_datetime(date_str, time_str)
        if scheduled_at is None:
            continue

        before_min, after_min = _BLACKOUT_MINUTES.get(tier, (0, 0))
        event_id = _event_id(title, country, scheduled_at)

        events.append(NewsEvent(
            id=event_id,
            title=title,
            country=country,
            impact=impact,
            tier=tier,
            scheduled_at=scheduled_at,
            blackout_before_min=before_min,
            blackout_after_min=after_min,
            forecast=forecast,
            previous=previous,
            url=url,
            fetched_at=fetched_at,
        ))
    return events


# ---------------------------------------------------------------------------
# DB persistence
# ---------------------------------------------------------------------------


def _upsert_events(conn: Connection, events: list[NewsEvent]) -> int:
    fetched_iso = datetime.now(UTC).replace(microsecond=0).isoformat()
    count = 0
    for ev in events:
        # Parser/timezone fixes must correct the existing event instead of
        # leaving a stale same-day duplicate under the old time-derived ID.
        existing = conn.execute(
            """
            SELECT id
            FROM news_events
            WHERE title = ? AND country = ? AND substr(scheduled_at, 1, 10) = ?
            ORDER BY fetched_at DESC
            LIMIT 1
            """,
            (ev.title, ev.country, ev.scheduled_at.date().isoformat()),
        ).fetchone()
        event_id = str(existing["id"]) if existing is not None else ev.id
        conn.execute(
            """
            INSERT INTO news_events
                (id, title, country, impact, tier, scheduled_at,
                 blackout_before_min, blackout_after_min,
                 forecast, previous, url, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                impact     = excluded.impact,
                tier       = excluded.tier,
                scheduled_at = excluded.scheduled_at,
                blackout_before_min = excluded.blackout_before_min,
                blackout_after_min = excluded.blackout_after_min,
                forecast   = excluded.forecast,
                previous   = excluded.previous,
                url        = excluded.url,
                fetched_at = excluded.fetched_at
            """,
            (
                event_id, ev.title, ev.country, ev.impact, ev.tier,
                ev.scheduled_at.replace(microsecond=0).isoformat(),
                ev.blackout_before_min, ev.blackout_after_min,
                ev.forecast, ev.previous, ev.url, fetched_iso,
            ),
        )
        count += 1
    conn.commit()
    return count


def fetch_and_store_news(conn: Connection) -> int:
    """Fetch this-week + next-week FF calendars and upsert tier-1/2 USD events.

    Returns the number of relevant events upserted. Never raises — errors are
    logged and 0 is returned so the live worker keeps running.
    """
    fetched_at = datetime.now(UTC)
    all_events: list[NewsEvent] = []
    for url in _FF_URLS:
        try:
            xml_text = _fetch_xml(url)
            events = _parse_ff_xml(xml_text, fetched_at)
            all_events.extend(events)
            logger.info("news_calendar: fetched %d relevant events from %s", len(events), url)
        except Exception as exc:
            logger.warning("news_calendar: failed to fetch %s — %s", url, exc)
    if not all_events:
        return 0
    return _upsert_events(conn, all_events)


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def active_news_blackout(conn: Connection, now: datetime | None = None) -> dict[str, Any] | None:
    """Return the active blackout event dict, or None if trading is clear.

    An event is 'active' when now falls inside [scheduled_at - before, scheduled_at + after].
    If multiple events overlap, the highest-tier (lowest tier number) wins.
    """
    if now is None:
        now = datetime.now(UTC)
    now_iso = now.replace(microsecond=0).isoformat()

    # Find events whose blackout window contains now.
    # We query a broad window first, then filter precisely in Python.
    lookahead = (now + timedelta(minutes=60)).isoformat()
    lookbehind = (now - timedelta(minutes=60)).isoformat()
    rows = conn.execute(
        """
        SELECT id, title, country, impact, tier, scheduled_at,
               blackout_before_min, blackout_after_min,
               forecast, previous, url
        FROM news_events
        WHERE scheduled_at BETWEEN ? AND ?
          AND tier IS NOT NULL
        ORDER BY tier ASC, scheduled_at ASC
        """,
        (lookbehind, lookahead),
    ).fetchall()

    for row in rows:
        try:
            sched = datetime.fromisoformat(str(row["scheduled_at"])).replace(tzinfo=UTC)
        except ValueError:
            continue
        window_start = sched - timedelta(minutes=int(row["blackout_before_min"]))
        window_end = sched + timedelta(minutes=int(row["blackout_after_min"]))
        if window_start <= now <= window_end:
            return {
                "id": row["id"],
                "title": row["title"],
                "country": row["country"],
                "tier": row["tier"],
                "scheduled_at": str(row["scheduled_at"]),
                "blackout_from": window_start.isoformat(),
                "blackout_until": window_end.isoformat(),
                "blackout_before_min": row["blackout_before_min"],
                "blackout_after_min": row["blackout_after_min"],
                "forecast": row["forecast"],
                "previous": row["previous"],
                "url": row["url"],
            }
    return None


def upcoming_news_events(
    conn: Connection,
    now: datetime | None = None,
    hours_ahead: int = 48,
) -> list[dict[str, Any]]:
    """Return tier-1/2 events scheduled in the next `hours_ahead` hours, enriched with UI fields."""
    if now is None:
        now = datetime.now(UTC)
    until = now + timedelta(hours=hours_ahead)
    earliest = now - timedelta(minutes=max(after for _before, after in _BLACKOUT_MINUTES.values()))
    rows = conn.execute(
        """
        SELECT id, title, country, impact, tier, scheduled_at,
               blackout_before_min, blackout_after_min,
               forecast, previous, url
        FROM news_events
        WHERE scheduled_at BETWEEN ? AND ?
          AND tier IS NOT NULL
        ORDER BY scheduled_at ASC
        """,
        (earliest.isoformat(), until.isoformat()),
    ).fetchall()

    result: list[dict[str, Any]] = []
    for row in rows:
        try:
            sched = datetime.fromisoformat(str(row["scheduled_at"])).replace(tzinfo=UTC)
        except ValueError:
            continue
        before = int(row["blackout_before_min"])
        after = int(row["blackout_after_min"])
        window_start = sched - timedelta(minutes=before)
        window_end = sched + timedelta(minutes=after)
        minutes_until = int((sched - now).total_seconds() / 60)
        is_active = window_start <= now <= window_end
        if sched < now and not is_active:
            continue

        result.append({
            "id": row["id"],
            "title": row["title"],
            "country": row["country"],
            "impact": row["impact"],
            "tier": row["tier"],
            "scheduled_at": sched.isoformat(),
            "blackout_from": window_start.isoformat(),
            "blackout_until": window_end.isoformat(),
            "blackout_before_min": before,
            "blackout_after_min": after,
            "minutes_until": minutes_until,
            "is_active_blackout": is_active,
            "forecast": row["forecast"],
            "previous": row["previous"],
            "url": row["url"],
        })
    return result


def should_notify_news(
    conn: Connection,
    now: datetime | None = None,
    notify_minutes_before: int = 10,
) -> list[dict[str, Any]]:
    """Return events whose notification window just opened (dedupe via alert_events table).

    We look for events in the band [now + notify_minutes_before - 1, now + notify_minutes_before + 1].
    The 2-minute band covers one poll cycle safely.
    """
    if now is None:
        now = datetime.now(UTC)
    lo = now + timedelta(minutes=notify_minutes_before - 1)
    hi = now + timedelta(minutes=notify_minutes_before + 1)
    rows = conn.execute(
        """
        SELECT id, title, country, tier, scheduled_at,
               blackout_before_min, blackout_after_min,
               forecast, previous
        FROM news_events
        WHERE scheduled_at BETWEEN ? AND ?
          AND tier IS NOT NULL
        ORDER BY tier ASC, scheduled_at ASC
        """,
        (lo.isoformat(), hi.isoformat()),
    ).fetchall()

    result: list[dict[str, Any]] = []
    for row in rows:
        result.append({
            "id": row["id"],
            "title": row["title"],
            "country": row["country"],
            "tier": row["tier"],
            "scheduled_at": str(row["scheduled_at"]),
            "blackout_before_min": row["blackout_before_min"],
            "blackout_after_min": row["blackout_after_min"],
            "forecast": row["forecast"],
            "previous": row["previous"],
        })
    return result
