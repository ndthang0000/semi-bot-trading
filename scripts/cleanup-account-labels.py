from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "var" / "trading.sqlite3"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Relabel legacy live trades as Exness and remove data belonging "
            "to the exact FTMO Demo account label."
        )
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite database path.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes. Without this flag the script only prints a dry-run audit.",
    )
    parser.add_argument("--legacy-label", default="Default")
    parser.add_argument("--exness-label", default="Exness Personal")
    parser.add_argument("--expected-exness-symbol", default="XAUUSDc")
    parser.add_argument("--ftmo-demo-label", default="FTMO Demo")
    parser.add_argument("--ftmo-real-label", default="FTMO 100K 2-Step")
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=None,
        help="Backup directory. Defaults to <database directory>/backups.",
    )
    return parser.parse_args()


def scalar(conn: sqlite3.Connection, sql: str, params: tuple[object, ...] = ()) -> int:
    return int(conn.execute(sql, params).fetchone()[0])


def account_counts(conn: sqlite3.Connection, label: str) -> dict[str, int]:
    return {
        "trade_orders": scalar(
            conn, "SELECT count(*) FROM trade_orders WHERE account_label = ?", (label,)
        ),
        "execution_requests": scalar(
            conn,
            "SELECT count(*) FROM execution_requests WHERE account_label = ?",
            (label,),
        ),
        "account_snapshots": scalar(
            conn,
            "SELECT count(*) FROM account_snapshots WHERE account_label = ?",
            (label,),
        ),
        "spread_snapshots": scalar(
            conn,
            "SELECT count(*) FROM spread_snapshots WHERE account_label = ?",
            (label,),
        ),
    }


def prepare_targets(
    conn: sqlite3.Connection,
    *,
    legacy_label: str,
    expected_exness_symbol: str,
    ftmo_demo_label: str,
) -> None:
    conn.execute("DROP TABLE IF EXISTS temp.legacy_exness_ideas")
    conn.execute("DROP TABLE IF EXISTS temp.ftmo_demo_orders")
    conn.execute("DROP TABLE IF EXISTS temp.ftmo_demo_ideas")

    conn.execute("CREATE TEMP TABLE legacy_exness_ideas(id TEXT PRIMARY KEY)")
    conn.execute(
        """
        INSERT INTO legacy_exness_ideas
        SELECT DISTINCT trade_idea_id
        FROM trade_orders
        WHERE source = 'live' AND account_label = ?
        """,
        (legacy_label,),
    )

    unexpected_symbols = [
        str(row[0])
        for row in conn.execute(
            """
            SELECT DISTINCT e.broker_symbol
            FROM execution_requests e
            JOIN legacy_exness_ideas i ON i.id = e.trade_idea_id
            WHERE e.broker_symbol <> ?
            """,
            (expected_exness_symbol,),
        )
    ]
    missing_requests = scalar(
        conn,
        """
        SELECT count(*)
        FROM legacy_exness_ideas i
        WHERE NOT EXISTS (
            SELECT 1 FROM execution_requests e WHERE e.trade_idea_id = i.id
        )
        """,
    )
    if unexpected_symbols or missing_requests:
        raise RuntimeError(
            "Refusing to relabel ambiguous legacy live trades. "
            f"Unexpected broker symbols={unexpected_symbols}, "
            f"ideas without execution requests={missing_requests}."
        )

    conn.execute("CREATE TEMP TABLE ftmo_demo_orders(id TEXT PRIMARY KEY)")
    conn.execute(
        "INSERT INTO ftmo_demo_orders SELECT id FROM trade_orders WHERE account_label = ?",
        (ftmo_demo_label,),
    )
    conn.execute("CREATE TEMP TABLE ftmo_demo_ideas(id TEXT PRIMARY KEY)")
    conn.execute(
        """
        INSERT OR IGNORE INTO ftmo_demo_ideas
        SELECT DISTINCT trade_idea_id
        FROM trade_orders
        WHERE account_label = ?
        """,
        (ftmo_demo_label,),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO ftmo_demo_ideas
        SELECT DISTINCT trade_idea_id
        FROM execution_requests
        WHERE account_label = ?
        """,
        (ftmo_demo_label,),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO ftmo_demo_ideas
        SELECT id
        FROM trade_ideas
        WHERE json_valid(context_snapshot_json)
          AND json_extract(context_snapshot_json, '$.account_label') = ?
        """,
        (ftmo_demo_label,),
    )


def target_counts(
    conn: sqlite3.Connection,
    *,
    legacy_label: str,
    ftmo_demo_label: str,
) -> dict[str, int]:
    alert_where = """
        dedupe_key LIKE ?
        OR (
            json_valid(message_payload_json)
            AND json_extract(message_payload_json, '$.account') = ?
        )
        OR EXISTS (
            SELECT 1 FROM ftmo_demo_orders o
            WHERE alert_events.entity_ids_json LIKE '%' || o.id || '%'
        )
        OR EXISTS (
            SELECT 1 FROM ftmo_demo_ideas i
            WHERE alert_events.entity_ids_json LIKE '%' || i.id || '%'
        )
    """
    return {
        "legacy_live_orders_to_relabel": scalar(
            conn,
            """
            SELECT count(*) FROM trade_orders
            WHERE source = 'live'
              AND account_label = ?
              AND trade_idea_id IN (SELECT id FROM legacy_exness_ideas)
            """,
            (legacy_label,),
        ),
        "legacy_execution_requests_to_relabel": scalar(
            conn,
            """
            SELECT count(*) FROM execution_requests
            WHERE account_label = ?
              AND trade_idea_id IN (SELECT id FROM legacy_exness_ideas)
            """,
            (legacy_label,),
        ),
        "ftmo_demo_trade_orders_to_delete": scalar(
            conn, "SELECT count(*) FROM ftmo_demo_orders"
        ),
        "ftmo_demo_execution_requests_to_delete": scalar(
            conn,
            "SELECT count(*) FROM execution_requests WHERE account_label = ?",
            (ftmo_demo_label,),
        ),
        "ftmo_demo_trade_ideas_to_delete": scalar(
            conn, "SELECT count(*) FROM ftmo_demo_ideas"
        ),
        "ftmo_demo_alert_events_to_delete": scalar(
            conn,
            f"SELECT count(*) FROM alert_events WHERE {alert_where}",
            (f"%:{ftmo_demo_label}:%", ftmo_demo_label),
        ),
        "ftmo_demo_trade_reviews_to_delete": scalar(
            conn,
            """
            SELECT count(*) FROM trade_reviews
            WHERE trade_order_id IN (SELECT id FROM ftmo_demo_orders)
            """,
        ),
        "ftmo_demo_review_attachments_to_delete": scalar(
            conn,
            """
            SELECT count(*) FROM trade_review_attachments
            WHERE trade_order_id IN (SELECT id FROM ftmo_demo_orders)
            """,
        ),
        "ftmo_demo_trade_fills_to_delete": scalar(
            conn,
            """
            SELECT count(*) FROM trade_fills
            WHERE trade_order_id IN (SELECT id FROM ftmo_demo_orders)
            """,
        ),
        "ftmo_demo_account_snapshots_to_delete": scalar(
            conn,
            "SELECT count(*) FROM account_snapshots WHERE account_label = ?",
            (ftmo_demo_label,),
        ),
        "ftmo_demo_spread_snapshots_to_delete": scalar(
            conn,
            "SELECT count(*) FROM spread_snapshots WHERE account_label = ?",
            (ftmo_demo_label,),
        ),
    }


def create_backup(db_path: Path, backup_dir: Path | None) -> Path:
    destination_dir = backup_dir or db_path.parent / "backups"
    destination_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = destination_dir / f"{db_path.stem}-before-account-cleanup-{timestamp}.sqlite3"
    source = sqlite3.connect(db_path)
    backup = sqlite3.connect(backup_path)
    try:
        source.backup(backup)
    finally:
        backup.close()
        source.close()
    return backup_path


def apply_cleanup(
    conn: sqlite3.Connection,
    *,
    legacy_label: str,
    exness_label: str,
    ftmo_demo_label: str,
) -> dict[str, int]:
    changes: dict[str, int] = {}

    def execute(name: str, sql: str, params: tuple[object, ...] = ()) -> None:
        changes[name] = conn.execute(sql, params).rowcount

    execute(
        "legacy_live_orders_relabelled",
        """
        UPDATE trade_orders
        SET account_label = ?
        WHERE source = 'live'
          AND account_label = ?
          AND trade_idea_id IN (SELECT id FROM legacy_exness_ideas)
        """,
        (exness_label, legacy_label),
    )
    execute(
        "legacy_execution_requests_relabelled",
        """
        UPDATE execution_requests
        SET account_label = ?
        WHERE account_label = ?
          AND trade_idea_id IN (SELECT id FROM legacy_exness_ideas)
        """,
        (exness_label, legacy_label),
    )
    execute(
        "ftmo_demo_alert_events_deleted",
        """
        DELETE FROM alert_events
        WHERE dedupe_key LIKE ?
           OR (
                json_valid(message_payload_json)
                AND json_extract(message_payload_json, '$.account') = ?
           )
           OR EXISTS (
                SELECT 1 FROM ftmo_demo_orders o
                WHERE alert_events.entity_ids_json LIKE '%' || o.id || '%'
           )
           OR EXISTS (
                SELECT 1 FROM ftmo_demo_ideas i
                WHERE alert_events.entity_ids_json LIKE '%' || i.id || '%'
           )
        """,
        (f"%:{ftmo_demo_label}:%", ftmo_demo_label),
    )
    for table in ("trade_review_attachments", "trade_reviews", "trade_fills"):
        execute(
            f"ftmo_demo_{table}_deleted",
            f"DELETE FROM {table} WHERE trade_order_id IN (SELECT id FROM ftmo_demo_orders)",
        )
    execute(
        "ftmo_demo_trade_orders_deleted",
        "DELETE FROM trade_orders WHERE account_label = ?",
        (ftmo_demo_label,),
    )
    execute(
        "ftmo_demo_execution_requests_deleted",
        "DELETE FROM execution_requests WHERE account_label = ?",
        (ftmo_demo_label,),
    )

    referenced_ideas = scalar(
        conn,
        """
        SELECT count(*) FROM ftmo_demo_ideas i
        WHERE EXISTS (SELECT 1 FROM trade_orders o WHERE o.trade_idea_id = i.id)
           OR EXISTS (
                SELECT 1 FROM execution_requests e WHERE e.trade_idea_id = i.id
           )
        """,
    )
    if referenced_ideas:
        raise RuntimeError(
            f"Refusing to delete {referenced_ideas} FTMO Demo ideas still referenced "
            "after account-scoped deletes."
        )
    execute(
        "ftmo_demo_trade_ideas_deleted",
        "DELETE FROM trade_ideas WHERE id IN (SELECT id FROM ftmo_demo_ideas)",
    )
    execute(
        "ftmo_demo_account_snapshots_deleted",
        "DELETE FROM account_snapshots WHERE account_label = ?",
        (ftmo_demo_label,),
    )
    execute(
        "ftmo_demo_spread_snapshots_deleted",
        "DELETE FROM spread_snapshots WHERE account_label = ?",
        (ftmo_demo_label,),
    )
    return changes


def main() -> int:
    args = parse_args()
    db_path = args.db.expanduser().resolve()
    if not db_path.is_file():
        raise SystemExit(f"Database does not exist: {db_path}")
    if len(
        {
            args.legacy_label,
            args.exness_label,
            args.ftmo_demo_label,
            args.ftmo_real_label,
        }
    ) != 4:
        raise SystemExit("All account labels must be distinct.")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    prepare_targets(
        conn,
        legacy_label=args.legacy_label,
        expected_exness_symbol=args.expected_exness_symbol,
        ftmo_demo_label=args.ftmo_demo_label,
    )
    targets = target_counts(
        conn,
        legacy_label=args.legacy_label,
        ftmo_demo_label=args.ftmo_demo_label,
    )
    ftmo_real_before = account_counts(conn, args.ftmo_real_label)
    if not any(ftmo_real_before.values()):
        conn.close()
        raise SystemExit(
            f"FTMO real safety label was not found: {args.ftmo_real_label!r}. "
            "Pass the exact current real account label."
        )

    print(f"Database: {db_path}")
    print("Mode:", "APPLY" if args.apply else "DRY RUN")
    print("Targets:")
    for key, value in targets.items():
        print(f"  {key}: {value}")
    print(f"FTMO real safety snapshot ({args.ftmo_real_label}): {ftmo_real_before}")
    print(
        "Legacy spread snapshots labelled Default are intentionally preserved; "
        "this script only relabels live trade/order records."
    )

    if not args.apply:
        print("No database changes were made. Re-run with --apply after reviewing counts.")
        conn.close()
        return 0

    conn.close()
    backup_path = create_backup(db_path, args.backup_dir)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("BEGIN IMMEDIATE")
        prepare_targets(
            conn,
            legacy_label=args.legacy_label,
            expected_exness_symbol=args.expected_exness_symbol,
            ftmo_demo_label=args.ftmo_demo_label,
        )
        changes = apply_cleanup(
            conn,
            legacy_label=args.legacy_label,
            exness_label=args.exness_label,
            ftmo_demo_label=args.ftmo_demo_label,
        )
        if account_counts(conn, args.ftmo_real_label) != ftmo_real_before:
            raise RuntimeError("FTMO real row counts changed; rolling back.")
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise

    integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
    foreign_key_violations = len(list(conn.execute("PRAGMA foreign_key_check")))
    remaining_demo = sum(account_counts(conn, args.ftmo_demo_label).values())
    remaining_demo_ideas = scalar(
        conn,
        """
        SELECT count(*) FROM trade_ideas
        WHERE id IN (SELECT id FROM ftmo_demo_ideas)
           OR (
                json_valid(context_snapshot_json)
                AND json_extract(context_snapshot_json, '$.account_label') = ?
           )
        """,
        (args.ftmo_demo_label,),
    )
    remaining_demo_alerts = scalar(
        conn,
        """
        SELECT count(*) FROM alert_events
        WHERE dedupe_key LIKE ?
           OR (
                json_valid(message_payload_json)
                AND json_extract(message_payload_json, '$.account') = ?
           )
           OR EXISTS (
                SELECT 1 FROM ftmo_demo_orders o
                WHERE alert_events.entity_ids_json LIKE '%' || o.id || '%'
           )
           OR EXISTS (
                SELECT 1 FROM ftmo_demo_ideas i
                WHERE alert_events.entity_ids_json LIKE '%' || i.id || '%'
           )
        """,
        (f"%:{args.ftmo_demo_label}:%", args.ftmo_demo_label),
    )
    remaining_default_live = scalar(
        conn,
        """
        SELECT count(*) FROM trade_orders
        WHERE source = 'live' AND account_label = ?
        """,
        (args.legacy_label,),
    )
    preserved_default_backtests = scalar(
        conn,
        """
        SELECT count(*) FROM trade_orders
        WHERE source = 'backtest' AND account_label = ?
        """,
        (args.legacy_label,),
    )
    conn.close()

    if (
        integrity != "ok"
        or foreign_key_violations
        or remaining_demo
        or remaining_demo_ideas
        or remaining_demo_alerts
        or remaining_default_live
    ):
        raise RuntimeError(
            "Post-cleanup validation failed: "
            f"integrity={integrity}, foreign_keys={foreign_key_violations}, "
            f"remaining_demo={remaining_demo}, "
            f"remaining_demo_ideas={remaining_demo_ideas}, "
            f"remaining_demo_alerts={remaining_demo_alerts}, "
            f"remaining_default_live={remaining_default_live}. "
            f"Restore from {backup_path}."
        )

    print(f"Backup: {backup_path}")
    print("Applied changes:")
    for key, value in changes.items():
        print(f"  {key}: {value}")
    print(f"FTMO real unchanged: {ftmo_real_before}")
    print(f"Default backtest orders preserved: {preserved_default_backtests}")
    print("Integrity check: ok")
    print("Foreign-key violations: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
