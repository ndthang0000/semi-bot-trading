from __future__ import annotations

import unittest
from pathlib import Path
from tests.helpers import TemporaryDirectory

from semi_bot_trading.db import connect, init_db
from semi_bot_trading.importer import import_csv_file
from semi_bot_trading.replay import replay_candles


class ImporterTest(unittest.TestCase):
    def test_import_csv_file_idempotent(self) -> None:
        with TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            csv_path = tmp_path / "XAUUSD_M15.csv"
            csv_path.write_text(
                "\n".join(
                    [
                        "time,open,high,low,close,volume",
                        "2026-01-01T00:00:00+00:00,2000,2002,1999,2001,10",
                        "2026-01-01T00:15:00+00:00,2001,2003,2000,2002,11",
                    ]
                )
            )
            db_path = tmp_path / "test.sqlite3"

            with connect(db_path) as conn:
                init_db(conn)
                first = import_csv_file(conn, csv_path)
                second = import_csv_file(conn, csv_path)
                rows = replay_candles(conn, "XAUUSD", "M15", limit=10)

            self.assertEqual(first.rows_seen, 2)
            self.assertEqual(second.rows_seen, 2)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["close"], 2001)


if __name__ == "__main__":
    unittest.main()
