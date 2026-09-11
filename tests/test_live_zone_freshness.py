import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from semi_bot_trading.db import connect, init_db
from semi_bot_trading.config import load_config
from semi_bot_trading.live_worker import expire_live_bot_sr_zones, queue_zone_alerts
from tests.test_live_worker import _make_env


class TestLiveZoneFreshness(unittest.TestCase):
    def test_historical_sr_expires_before_alert_and_human_zone_is_preserved(self):
        conn = connect(':memory:')
        self.addCleanup(conn.close)
        init_db(conn)
        now = datetime.now(timezone.utc)
        for identifier, age, source in [('old', 600, 'bot'), ('fresh', 0, 'bot'), ('human', 600, 'human')]:
            detected = (now - timedelta(days=age, minutes=5)).isoformat()
            conn.execute('''INSERT INTO price_zones
                (id,symbol,timeframe,detector,zone_type,direction,price_low,price_high,
                start_time,valid_from,detected_at,status,source)
                VALUES (?,'XAUUSD','H1','sr_v2','support','bullish',2653.6675,2658.5425,
                ?,?,?,'active',?)''', (identifier,detected,detected,detected,source))
        conn.commit()
        # Even before lifecycle fixes the row, historical IDs must not alert.
        rows = conn.execute('SELECT * FROM price_zones WHERE source=\'bot\'').fetchall()
        with patch('semi_bot_trading.live_worker.queue_alert') as alert:
            queue_zone_alerts(conn, load_config(), _make_env(), rows)
            self.assertEqual(1, alert.call_count)
            self.assertEqual(['fresh'], alert.call_args.kwargs['entity_ids'])
        expire_live_bot_sr_zones(conn, 'XAUUSD', now)
        old = conn.execute("SELECT * FROM price_zones WHERE id='old'").fetchone()
        self.assertEqual('expired', old['status'])
        self.assertEqual(old['valid_until'], old['end_time'])
        self.assertEqual('draft', conn.execute("SELECT status FROM price_zones WHERE id='fresh'").fetchone()[0])
        self.assertIsNone(conn.execute("SELECT valid_until FROM price_zones WHERE id='human'").fetchone()[0])
        expire_live_bot_sr_zones(conn, 'XAUUSD', now)
        self.assertEqual('expired', conn.execute("SELECT status FROM price_zones WHERE id='old'").fetchone()[0])

    def seed_review_zone(self, conn):
        now = datetime.now(timezone.utc)
        old = (now - timedelta(days=600)).isoformat()
        conn.execute('''INSERT INTO price_zones
            (id,symbol,timeframe,detector,zone_type,direction,price_low,price_high,
             start_time,valid_from,detected_at,status,source)
            VALUES ('review','XAUUSD','H1','sr_v2','support','bullish',100,105,
             ?,?,?,'draft','bot')''', (old, old, old))
        conn.commit()
        return now

    def test_stale_worker_update_cannot_overwrite_confirmation(self):
        conn = connect(':memory:')
        self.addCleanup(conn.close)
        init_db(conn)
        now = self.seed_review_zone(conn)
        expiry = (now + timedelta(days=3)).isoformat()
        metadata = json.dumps({'activation_review': {'confirmed_by': 'human'}})
        class ConfirmBeforeUpdate:
            def execute(self, sql, parameters=()):
                if sql.lstrip().startswith('UPDATE price_zones SET valid_until'):
                    # Same timestamp: metadata/status checks must still protect review.
                    conn.execute("UPDATE price_zones SET status='active',valid_until=?,end_time=?,metadata_json=? WHERE id='review'",
                                 (expiry, expiry, metadata))
                    conn.commit()
                return conn.execute(sql, parameters)
            def commit(self):
                conn.commit()
        expire_live_bot_sr_zones(ConfirmBeforeUpdate(), 'XAUUSD', now)
        row = conn.execute("SELECT * FROM price_zones WHERE id='review'").fetchone()
        self.assertEqual('active', row['status'])
        self.assertEqual(expiry, row['valid_until'])
        self.assertEqual(metadata, row['metadata_json'])

    def test_init_db_preserves_reviewed_bot_expiry_and_metadata(self):
        for marker in ({'human_adjusted': True}, {'activation_review': {'confirmed_by': 'human'}}):
            for has_expiry in (True, False):
                with self.subTest(marker=marker, has_expiry=has_expiry):
                    conn = connect(':memory:')
                    try:
                        init_db(conn)
                        now = self.seed_review_zone(conn)
                        expiry = (now + timedelta(days=3)).isoformat() if has_expiry else None
                        metadata = json.dumps({'expired_rule': 'default_expiry_backfill', **marker})
                        conn.execute("UPDATE price_zones SET status='active',valid_until=?,end_time=?,metadata_json=? WHERE id='review'",
                                     (expiry, expiry, metadata))
                        conn.commit()
                        for _ in range(2):
                            init_db(conn)
                        row = conn.execute("SELECT * FROM price_zones WHERE id='review'").fetchone()
                        self.assertEqual('active', row['status'])
                        self.assertEqual(expiry, row['valid_until'])
                        self.assertEqual(metadata, row['metadata_json'])
                    finally:
                        conn.close()
