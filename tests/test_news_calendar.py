from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tests.helpers import TemporaryDirectory

from semi_bot_trading.chart import load_chart_contexts
from semi_bot_trading.config import load_config
from semi_bot_trading.db import connect, init_db
from semi_bot_trading.live_worker import _expire_news_regimes, _upsert_news_regime
from semi_bot_trading.news_calendar import (
    _parse_ff_datetime,
    _parse_ff_xml,
    _upsert_events,
    active_ftmo_news_window,
    active_news_blackout,
    classify_tier,
    is_ftmo_restricted_event,
    news_calendar_is_fresh,
    upcoming_news_events,
)


class NewsCalendarTest(unittest.TestCase):
    def test_ftmo_restricted_event_classification_is_separate_from_market_tier(self) -> None:
        self.assertEqual(1, classify_tier("FOMC Meeting Minutes", "USD", "High"))
        self.assertEqual(1, classify_tier("FOMC Meeting Minutes", "USD", "Medium"))
        self.assertIsNone(classify_tier("JOLTS Job Openings", "USD", "Medium"))
        self.assertTrue(is_ftmo_restricted_event("FOMC Meeting Minutes", "USD"))
        self.assertTrue(is_ftmo_restricted_event("CPI y/y", "USD"))
        self.assertFalse(is_ftmo_restricted_event("JOLTS Job Openings", "USD"))
        self.assertFalse(is_ftmo_restricted_event("CPI y/y", "EUR"))

    def test_ftmo_news_window_has_prepare_restricted_and_cooldown_phases(self) -> None:
        scheduled_at = datetime(2026, 8, 7, 12, 30, tzinfo=UTC)
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with connect(db_path) as conn:
                init_db(conn)
                conn.execute(
                    """
                    INSERT INTO news_events (
                        id, title, country, impact, tier, scheduled_at,
                        blackout_before_min, blackout_after_min, forecast, previous, url, fetched_at
                    ) VALUES (?, ?, 'USD', 'High', 1, ?, 30, 30, NULL, NULL, NULL, ?)
                    """,
                    ("nfp", "Non-Farm Employment Change", scheduled_at.isoformat(), scheduled_at.isoformat()),
                )
                conn.commit()

                prepare = active_ftmo_news_window(conn, scheduled_at - timedelta(minutes=4), buffer_minutes=5)
                safety_freeze = active_ftmo_news_window(conn, scheduled_at - timedelta(minutes=2, seconds=30), buffer_minutes=5)
                restricted = active_ftmo_news_window(conn, scheduled_at, buffer_minutes=5)
                cooldown = active_ftmo_news_window(conn, scheduled_at + timedelta(minutes=3), buffer_minutes=5)
                outside = active_ftmo_news_window(conn, scheduled_at + timedelta(minutes=6), buffer_minutes=5)

                self.assertEqual("prepare", prepare["phase"])
                self.assertEqual("restricted", safety_freeze["phase"])
                self.assertEqual("restricted", restricted["phase"])
                self.assertEqual("cooldown", cooldown["phase"])
                self.assertIsNone(outside)
                self.assertTrue(news_calendar_is_fresh(conn, scheduled_at, max_age_hours=36))

    def test_fair_economy_xml_clock_is_already_utc(self) -> None:
        parsed = _parse_ff_datetime("07-30-2026", "12:30pm")

        self.assertEqual(datetime(2026, 7, 30, 12, 30, tzinfo=UTC), parsed)

    def test_fetch_reconciles_stale_same_day_timezone_row(self) -> None:
        xml = """
        <weeklyevents>
          <event>
            <title>Advance GDP q/q</title><country>USD</country><date>07-30-2026</date>
            <time>12:30pm</time><impact>High</impact><forecast>2.1%</forecast>
            <previous>2.0%</previous><url>https://example.test/gdp</url>
          </event>
        </weeklyevents>
        """
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with connect(db_path) as conn:
                init_db(conn)
                conn.execute(
                    """
                    INSERT INTO news_events (
                        id, title, country, impact, tier, scheduled_at,
                        blackout_before_min, blackout_after_min, forecast, previous, url, fetched_at
                    ) VALUES ('stale-id', 'Advance GDP q/q', 'USD', 'High', 1,
                              '2026-07-30T16:30:00+00:00', 30, 30, NULL, NULL,
                              'https://example.test/gdp', '2026-07-29T00:00:00+00:00')
                    """
                )
                events = _parse_ff_xml(xml, datetime(2026, 7, 29, tzinfo=UTC))
                _upsert_events(conn, events)
                rows = conn.execute("SELECT id, scheduled_at FROM news_events").fetchall()

        self.assertEqual([("stale-id", "2026-07-30T12:30:00+00:00")], [(row["id"], row["scheduled_at"]) for row in rows])

    def test_upcoming_news_keeps_active_blackout_after_release_time(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            now = datetime(2026, 6, 24, 13, 10, tzinfo=UTC)
            scheduled_at = now - timedelta(minutes=10)
            with connect(db_path) as conn:
                init_db(conn)
                insert_news_event(conn, scheduled_at=scheduled_at, before=30, after=30)

                events = upcoming_news_events(conn, now=now, hours_ahead=48)
                blackout = active_news_blackout(conn, now=now)

        self.assertEqual(1, len(events))
        self.assertTrue(events[0]["is_active_blackout"])
        self.assertEqual(-10, events[0]["minutes_until"])
        self.assertIsNotNone(blackout)

    def test_news_regime_overlay_expires_without_replacing_bot_regime(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            config = replace(load_config(), database=db_path)
            now = datetime(2099, 6, 24, 13, 0, tzinfo=UTC)
            blackout = {
                "id": "news-1",
                "title": "Core CPI m/m",
                "country": "USD",
                "tier": 1,
                "scheduled_at": now.isoformat(),
                "blackout_from": (now - timedelta(minutes=30)).isoformat(),
                "blackout_until": (now + timedelta(minutes=30)).isoformat(),
                "blackout_before_min": 30,
                "blackout_after_min": 30,
                "forecast": None,
                "previous": None,
                "url": None,
            }
            with connect(db_path) as conn:
                init_db(conn)
                insert_bot_regime(conn, symbol=config.symbol, timeframe=config.regime.timeframe)
                _upsert_news_regime(conn, config, blackout)

                active = load_chart_contexts(conn, config.symbol)
                self.assertEqual("news", active[config.regime.timeframe]["regime"]["effective_value"])

                _expire_news_regimes(conn, config, now + timedelta(minutes=31))
                active = load_chart_contexts(conn, config.symbol)
                rows = conn.execute("SELECT source, status FROM market_contexts ORDER BY source").fetchall()

        self.assertEqual("trending", active[config.regime.timeframe]["regime"]["effective_value"])
        self.assertEqual([("bot", "active"), ("news_calendar", "expired")], [(r["source"], r["status"]) for r in rows])


def insert_news_event(conn, *, scheduled_at: datetime, before: int, after: int) -> None:
    conn.execute(
        """
        INSERT INTO news_events (
            id, title, country, impact, tier, scheduled_at,
            blackout_before_min, blackout_after_min, forecast, previous, url, fetched_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "event-1",
            "Core CPI m/m",
            "USD",
            "High",
            1,
            scheduled_at.replace(microsecond=0).isoformat(),
            before,
            after,
            None,
            None,
            None,
            scheduled_at.replace(microsecond=0).isoformat(),
        ),
    )
    conn.commit()


def insert_bot_regime(conn, *, symbol: str, timeframe: str) -> None:
    conn.execute(
        """
        INSERT INTO market_contexts (
            id, symbol, timeframe, context_type, bot_value, primary_value, secondary_value,
            bot_confidence, effective_value, effective_confidence, source,
            valid_from, valid_until, status, metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "bot-regime",
            symbol,
            timeframe,
            "regime",
            "trending",
            "trending",
            None,
            0.8,
            "trending",
            0.8,
            "bot",
            "2099-06-24T12:00:00+00:00",
            None,
            "active",
            "{}",
        ),
    )
    conn.commit()


if __name__ == "__main__":
    unittest.main()
