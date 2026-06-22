from __future__ import annotations

import json
import unittest
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from semi_bot_trading.db import connect, init_db


class DbMigrationTest(unittest.TestCase):
    def test_bot_sr_default_expiry_uses_detected_at_not_updated_at(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with closing(connect(db_path)) as conn:
                init_db(conn)
                detected_at = (datetime.now(UTC) - timedelta(days=10)).replace(microsecond=0).isoformat()
                updated_at = (datetime.now(UTC) - timedelta(minutes=5)).replace(microsecond=0).isoformat()
                conn.execute(
                    """
                    INSERT INTO price_zones (
                        id, symbol, timeframe, detector, zone_type, direction,
                        price_low, price_high, start_time, end_time, valid_from, valid_until,
                        invalidated_at, invalidated_by_structure_point_id, detected_at,
                        bot_confidence, bot_weight, effective_confidence, effective_weight,
                        status, source, metadata_json, created_at, updated_at
                    )
                    VALUES ('bot-sr', 'XAUUSD', 'H1', 'sr_v2', 'support', 'bullish',
                            4010, 4030, ?, NULL, ?, NULL,
                            NULL, NULL, ?,
                            0.8, 0.8, 0.8, 0.8,
                            'active', 'bot', ?, ?, ?)
                    """,
                    (detected_at, detected_at, detected_at, json.dumps({}), detected_at, updated_at),
                )
                init_db(conn)
                row = conn.execute(
                    """
                    SELECT status, end_time, valid_until, metadata_json
                    FROM price_zones
                    WHERE id = 'bot-sr'
                    """
                ).fetchone()

        self.assertEqual(row["status"], "expired")
        self.assertEqual(row["valid_until"], (datetime.fromisoformat(detected_at) + timedelta(hours=24)).isoformat())
        self.assertEqual(row["end_time"], row["valid_until"])
        metadata = json.loads(row["metadata_json"])
        self.assertEqual(metadata["default_expiry_backfill"]["base_time"], detected_at)


if __name__ == "__main__":
    unittest.main()
