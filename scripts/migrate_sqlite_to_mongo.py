from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.database import init_db  # noqa: E402
from src.env import load_app_env  # noqa: E402
from src.storage import MongoStore  # noqa: E402


def main() -> None:
    load_app_env()
    parser = argparse.ArgumentParser(description="Migrate the local SQLite market database into MongoDB.")
    parser.add_argument("--sqlite", default="data/market.sqlite", help="Path to the SQLite market database.")
    parser.add_argument("--mongo-uri", default=None, help="MongoDB connection string. Defaults to MONGODB_URI.")
    parser.add_argument("--mongo-db", default=None, help="MongoDB database name. Defaults to MONGODB_DB/homevalue_market.")
    args = parser.parse_args()

    import os

    mongo_uri = args.mongo_uri or os.getenv("MONGODB_URI")
    mongo_db = args.mongo_db or os.getenv("MONGODB_DB", "homevalue_market")
    if not mongo_uri:
        raise SystemExit("Missing MongoDB URI. Set MONGODB_URI in .env or pass --mongo-uri.")

    sqlite_path = Path(args.sqlite)
    if not sqlite_path.exists():
        raise SystemExit(f"SQLite database not found: {sqlite_path}")

    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    try:
        store = MongoStore(mongo_uri, mongo_db)
        store.init()
        report = {}
        report["raw_fetch"] = _migrate_raw_fetch(conn, store)
        report["listing_observation"] = _migrate_by_store_method(conn, store, "listing_observation", store.upsert_listings)
        report["price_snapshot"] = _migrate_by_store_method(conn, store, "price_snapshot", store.upsert_price_snapshots)
        report["property_candidate"] = _migrate_by_store_method(
            conn,
            store,
            "property_candidate",
            store.upsert_property_candidates,
        )
        report["verified_transaction"] = _migrate_verified_transactions(conn, store)
        print(json.dumps({"mongo_db": mongo_db, "collections": report}, ensure_ascii=False, indent=2))
    finally:
        conn.close()


def _sqlite_rows(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    rows = conn.execute(f"SELECT * FROM {table}").fetchall()
    return [dict(row) for row in rows]


def _migrate_raw_fetch(conn: sqlite3.Connection, store: MongoStore) -> dict[str, Any]:
    rows = [_prepare_row(row) for row in _sqlite_rows(conn, "raw_fetch")]
    before = store.count("raw_fetch")
    for row in rows:
        store.insert_raw_fetch(row)
    return _report(conn, store, "raw_fetch", before)


def _migrate_by_store_method(conn: sqlite3.Connection, store: MongoStore, table: str, method) -> dict[str, Any]:
    rows = [_prepare_row(row) for row in _sqlite_rows(conn, table)]
    before = store.count(table)
    inserted, updated = method(rows)
    data = _report(conn, store, table, before)
    data.update({"inserted": inserted, "updated": updated})
    return data


def _migrate_verified_transactions(conn: sqlite3.Connection, store: MongoStore) -> dict[str, Any]:
    rows = [_prepare_row(row) for row in _sqlite_rows(conn, "verified_transaction")]
    before = store.count("verified_transaction")
    inserted, updated = store.upsert_verified_transactions_by_legacy_id(rows)
    data = _report(conn, store, "verified_transaction", before)
    data.update({"inserted": inserted, "updated": updated})
    return data


def _prepare_row(row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    if "id" in payload:
        payload["legacy_sqlite_id"] = payload.pop("id")
    if "quality_flags_json" in payload:
        payload["quality_flags"] = _loads_flags(payload.pop("quality_flags_json"))
    return payload


def _loads_flags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _report(conn: sqlite3.Connection, store: MongoStore, table: str, before: int) -> dict[str, Any]:
    sqlite_count = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    mongo_count = store.count(table)
    return {
        "sqlite_count": sqlite_count,
        "mongo_count_before": before,
        "mongo_count_after": mongo_count,
    }


if __name__ == "__main__":
    main()
