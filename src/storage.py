from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from src.database import (
    DEFAULT_DB_PATH,
    connect,
    init_db,
)
from src.database import (
    upsert_listings as sqlite_upsert_listings,
)
from src.database import (
    upsert_price_snapshots as sqlite_upsert_price_snapshots,
)
from src.database import (
    upsert_property_candidates as sqlite_upsert_property_candidates,
)
from src.env import load_app_env

MONGO_COLLECTIONS = [
    "raw_fetch",
    "listing_observation",
    "price_snapshot",
    "property_candidate",
    "verified_transaction",
]


@dataclass(frozen=True)
class StorageSettings:
    backend: str
    mongodb_uri: str | None
    mongodb_db: str


def storage_settings() -> StorageSettings:
    load_app_env()
    backend = os.getenv("VALUATION_STORAGE_BACKEND", "auto").strip().lower() or "auto"
    if backend not in {"auto", "mongo", "sqlite"}:
        backend = "auto"
    mongodb_uri = (os.getenv("MONGODB_URI") or "").strip() or None
    mongodb_db = (os.getenv("MONGODB_DB") or "").strip() or "homevalue_market"
    return StorageSettings(
        backend=backend,
        mongodb_uri=mongodb_uri,
        mongodb_db=mongodb_db,
    )


def resolve_backend() -> str:
    settings = storage_settings()
    if settings.backend == "auto":
        return "mongo" if settings.mongodb_uri else "sqlite"
    return settings.backend


def get_store(db_path: str | Path = DEFAULT_DB_PATH):
    settings = storage_settings()
    backend = resolve_backend()
    if backend == "mongo":
        if not settings.mongodb_uri:
            raise ValueError("MONGODB_URI is required when VALUATION_STORAGE_BACKEND=mongo.")
        return MongoStore(settings.mongodb_uri, settings.mongodb_db)
    return SQLiteStore(db_path)


def init_storage(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    store = get_store(db_path)
    store.init()


class SQLiteStore:
    backend = "sqlite"

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)

    def init(self) -> None:
        conn = connect(self.db_path)
        try:
            init_db(conn)
        finally:
            conn.close()

    def latest_raw_fetch(self, url: str) -> dict[str, Any] | None:
        conn = connect(self.db_path)
        init_db(conn)
        try:
            row = conn.execute(
                """
                SELECT url, fetcher, status_code, blocked, content_path, error
                FROM raw_fetch
                WHERE url = ? AND content_path IS NOT NULL
                ORDER BY id DESC
                LIMIT 1
                """,
                (url,),
            ).fetchone()
        finally:
            conn.close()
        return dict(row) if row else None

    def raw_fetch_rows(self) -> list[dict[str, Any]]:
        conn = connect(self.db_path)
        init_db(conn)
        try:
            rows = conn.execute(
                "SELECT url, project_slug, purpose, property_type, fetched_at, content_path FROM raw_fetch ORDER BY id"
            ).fetchall()
        finally:
            conn.close()
        return [dict(row) for row in rows]

    def insert_raw_fetch(self, record: dict[str, Any]) -> None:
        conn = connect(self.db_path)
        init_db(conn)
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO raw_fetch (
                    url, project_slug, purpose, property_type, fetcher, status_code, fetched_at,
                    blocked, content_path, content_hash, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.get("url"),
                    record.get("project_slug"),
                    record.get("purpose"),
                    record.get("property_type"),
                    record.get("fetcher"),
                    record.get("status_code"),
                    record.get("fetched_at"),
                    int(bool(record.get("blocked"))),
                    record.get("content_path"),
                    record.get("content_hash"),
                    record.get("error"),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def upsert_listings(self, records: Iterable[dict[str, Any]]) -> tuple[int, int]:
        conn = connect(self.db_path)
        init_db(conn)
        try:
            result = sqlite_upsert_listings(conn, records)
            conn.commit()
            return result
        finally:
            conn.close()

    def upsert_price_snapshots(self, records: Iterable[dict[str, Any]]) -> tuple[int, int]:
        conn = connect(self.db_path)
        init_db(conn)
        try:
            result = sqlite_upsert_price_snapshots(conn, records)
            conn.commit()
            return result
        finally:
            conn.close()

    def upsert_property_candidates(self, records: Iterable[dict[str, Any]]) -> tuple[int, int]:
        conn = connect(self.db_path)
        init_db(conn)
        try:
            result = sqlite_upsert_property_candidates(conn, records)
            conn.commit()
            return result
        finally:
            conn.close()

    def insert_verified_transaction(self, record: dict[str, Any]) -> int:
        conn = connect(self.db_path)
        init_db(conn)
        try:
            cursor = conn.execute(
                """
                INSERT INTO verified_transaction (
                    created_at, project_slug, project_name, property_type, purpose,
                    transaction_price_vnd, rent_monthly_vnd, area_m2, bedrooms, subdivision,
                    transaction_date, confidence_score, evidence_note, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.get("created_at"),
                    record.get("project_slug"),
                    record.get("project_name"),
                    record.get("property_type"),
                    record.get("purpose"),
                    record.get("transaction_price_vnd"),
                    record.get("rent_monthly_vnd"),
                    record.get("area_m2"),
                    record.get("bedrooms"),
                    record.get("subdivision"),
                    record.get("transaction_date"),
                    record.get("confidence_score"),
                    record.get("evidence_note"),
                    record.get("source"),
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)
        finally:
            conn.close()

    def delete_parsed_collections(self) -> None:
        conn = connect(self.db_path)
        init_db(conn)
        try:
            conn.execute("DELETE FROM listing_observation")
            conn.execute("DELETE FROM price_snapshot")
            conn.execute("DELETE FROM property_candidate")
            conn.commit()
        finally:
            conn.close()

    def load_market_frame(self) -> pd.DataFrame:
        conn = connect(self.db_path)
        init_db(conn)
        try:
            listings = pd.read_sql_query("SELECT * FROM listing_observation", conn)
            verified = pd.read_sql_query("SELECT * FROM verified_transaction", conn)
        finally:
            conn.close()
        return _market_frame_from_tables(listings, verified)

    def load_price_snapshot_frame(self) -> pd.DataFrame:
        return self.collection_frame("price_snapshot", sort_field="observed_at")

    def collection_frame(self, name: str, sort_field: str | None = None) -> pd.DataFrame:
        conn = connect(self.db_path)
        init_db(conn)
        try:
            order = f" ORDER BY {sort_field} DESC" if sort_field else ""
            df = pd.read_sql_query(f"SELECT * FROM {name}{order}", conn)
        finally:
            conn.close()
        if "quality_flags_json" in df:
            df["quality_flags"] = df["quality_flags_json"].apply(_loads_flags)
        return df

    def count(self, name: str) -> int:
        conn = connect(self.db_path)
        init_db(conn)
        try:
            return int(conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
        finally:
            conn.close()


class MongoStore:
    backend = "mongo"

    def __init__(self, uri: str, db_name: str = "homevalue_market"):
        self.uri = uri
        self.db_name = db_name
        self._client = None

    @property
    def client(self):
        if self._client is None:
            try:
                from pymongo import MongoClient
            except ImportError as exc:  # pragma: no cover - depends on environment
                raise RuntimeError("pymongo is required for MongoDB storage. Add pymongo to requirements.") from exc
            timeout_ms = int(os.getenv("MONGODB_TIMEOUT_MS", "5000"))
            self._client = MongoClient(self.uri, serverSelectionTimeoutMS=timeout_ms)
        return self._client

    @property
    def db(self):
        return self.client[self.db_name]

    def init(self) -> None:
        from pymongo import ASCENDING, DESCENDING

        self.client.admin.command("ping")
        self.db.raw_fetch.create_index(
            [("url", ASCENDING), ("content_hash", ASCENDING)],
            unique=True,
            name="uniq_raw_fetch_url_hash",
        )
        self.db.raw_fetch.create_index([("url", ASCENDING), ("fetched_at", DESCENDING)], name="idx_raw_fetch_url_time")
        self.db.listing_observation.create_index("dedupe_key", unique=True, name="uniq_listing_dedupe_key")
        self.db.listing_observation.create_index(
            [("project_slug", ASCENDING), ("property_type", ASCENDING), ("purpose", ASCENDING), ("bedrooms", ASCENDING), ("observed_at", DESCENDING)],
            name="idx_listing_scope",
        )
        self.db.price_snapshot.create_index("dedupe_key", unique=True, name="uniq_price_snapshot_dedupe_key")
        self.db.price_snapshot.create_index(
            [("project_slug", ASCENDING), ("property_type", ASCENDING), ("purpose", ASCENDING), ("observed_at", DESCENDING)],
            name="idx_price_snapshot_scope",
        )
        self.db.property_candidate.create_index("dedupe_key", unique=True, name="uniq_property_candidate_dedupe_key")
        self.db.property_candidate.create_index(
            [("source", ASCENDING), ("mapped_project_slug", ASCENDING), ("observed_at", DESCENDING)],
            name="idx_property_candidate_source",
        )
        self.db.verified_transaction.create_index(
            [("legacy_sqlite_id", ASCENDING)],
            unique=True,
            sparse=True,
            name="uniq_verified_legacy_sqlite_id",
        )

    def latest_raw_fetch(self, url: str) -> dict[str, Any] | None:
        doc = self.db.raw_fetch.find_one(
            {"url": url, "content_path": {"$ne": None}},
            sort=[("fetched_at", -1), ("_id", -1)],
        )
        return _clean_mongo_doc(doc) if doc else None

    def raw_fetch_rows(self) -> list[dict[str, Any]]:
        return [_clean_mongo_doc(doc) for doc in self.db.raw_fetch.find({}, sort=[("fetched_at", 1), ("_id", 1)])]

    def insert_raw_fetch(self, record: dict[str, Any]) -> None:
        from pymongo.errors import DuplicateKeyError

        payload = _mongo_payload(record)
        try:
            self.db.raw_fetch.insert_one(payload)
        except DuplicateKeyError:
            return

    def upsert_listings(self, records: Iterable[dict[str, Any]]) -> tuple[int, int]:
        return self._upsert_by_dedupe_key("listing_observation", records, preserve_first_seen=True)

    def upsert_price_snapshots(self, records: Iterable[dict[str, Any]]) -> tuple[int, int]:
        return self._upsert_by_dedupe_key("price_snapshot", records)

    def upsert_property_candidates(self, records: Iterable[dict[str, Any]]) -> tuple[int, int]:
        return self._upsert_by_dedupe_key("property_candidate", records)

    def _upsert_by_dedupe_key(
        self,
        collection_name: str,
        records: Iterable[dict[str, Any]],
        preserve_first_seen: bool = False,
    ) -> tuple[int, int]:
        inserted = 0
        updated = 0
        collection = self.db[collection_name]
        for record in records:
            payload = _mongo_payload(record)
            dedupe_key = payload["dedupe_key"]
            existing = collection.find_one({"dedupe_key": dedupe_key}, {"first_seen_at": 1})
            if preserve_first_seen and existing and existing.get("first_seen_at"):
                payload["first_seen_at"] = existing["first_seen_at"]
            result = collection.update_one({"dedupe_key": dedupe_key}, {"$set": payload}, upsert=True)
            if result.upserted_id is not None:
                inserted += 1
            elif result.matched_count:
                updated += 1
        return inserted, updated

    def insert_verified_transaction(self, record: dict[str, Any]) -> str:
        payload = _mongo_payload(record)
        result = self.db.verified_transaction.insert_one(payload)
        return str(result.inserted_id)

    def upsert_verified_transactions_by_legacy_id(self, records: Iterable[dict[str, Any]]) -> tuple[int, int]:
        inserted = 0
        updated = 0
        collection = self.db.verified_transaction
        for record in records:
            payload = _mongo_payload(record)
            key = payload.get("legacy_sqlite_id")
            if key is None:
                result = collection.insert_one(payload)
                inserted += int(result.inserted_id is not None)
                continue
            result = collection.update_one({"legacy_sqlite_id": key}, {"$set": payload}, upsert=True)
            if result.upserted_id is not None:
                inserted += 1
            elif result.matched_count:
                updated += 1
        return inserted, updated

    def delete_parsed_collections(self) -> None:
        self.db.listing_observation.delete_many({})
        self.db.price_snapshot.delete_many({})
        self.db.property_candidate.delete_many({})

    def load_market_frame(self) -> pd.DataFrame:
        listings = self.collection_frame("listing_observation")
        verified = self.collection_frame("verified_transaction")
        return _market_frame_from_tables(listings, verified)

    def load_price_snapshot_frame(self) -> pd.DataFrame:
        return self.collection_frame("price_snapshot", sort_field="observed_at")

    def collection_frame(self, name: str, sort_field: str | None = None) -> pd.DataFrame:
        sort = [(sort_field, -1)] if sort_field else None
        cursor = self.db[name].find({}, {"_id": 0}, sort=sort)
        df = pd.DataFrame(list(cursor))
        if "quality_flags" not in df and "quality_flags_json" in df:
            df["quality_flags"] = df["quality_flags_json"].apply(_loads_flags)
        if "quality_flags" in df:
            df["quality_flags"] = df["quality_flags"].apply(_normalize_flags)
        return df

    def count(self, name: str) -> int:
        return int(self.db[name].count_documents({}))


def load_market_frame(db_path: str | Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    return get_store(db_path).load_market_frame()


def load_price_snapshot_frame(db_path: str | Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    return get_store(db_path).load_price_snapshot_frame()


def export_collection_csv(name: str, out_path: str | Path, db_path: str | Path = DEFAULT_DB_PATH, sort_field: str | None = None) -> Path:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df = get_store(db_path).collection_frame(name, sort_field=sort_field)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def _market_frame_from_tables(listings: pd.DataFrame, verified: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    if not listings.empty:
        listings = listings.copy()
        listings["source_weight"] = 1.0
        listings["basis"] = "listing"
        if "quality_flags" not in listings and "quality_flags_json" in listings:
            listings["quality_flags"] = listings["quality_flags_json"].apply(_loads_flags)
        if "quality_flags" in listings:
            listings["quality_flags"] = listings["quality_flags"].apply(_normalize_flags)
        frames.append(listings)
    if not verified.empty:
        verified = verified.copy()
        verified = verified.rename(
            columns={
                "transaction_price_vnd": "price_total_vnd",
                "confidence_score": "source_weight",
            }
        )
        verified["price_per_m2_vnd"] = verified.apply(
            lambda row: row["price_total_vnd"] / row["area_m2"]
            if pd.notna(row.get("price_total_vnd")) and pd.notna(row.get("area_m2")) and row["area_m2"] > 0
            else None,
            axis=1,
        )
        verified["observed_at"] = verified["transaction_date"].fillna(verified["created_at"])
        verified["title"] = verified.get("title", "Verified transaction")
        verified["source_url"] = verified.get("source_url", None)
        verified["is_verified"] = 1
        verified["basis"] = "verified_transaction"
        verified["quality_flags"] = [[] for _ in range(len(verified))]
        frames.append(verified)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False)


def _mongo_payload(record: dict[str, Any]) -> dict[str, Any]:
    payload = dict(record)
    if "quality_flags_json" in payload and "quality_flags" not in payload:
        payload["quality_flags"] = _loads_flags(payload.pop("quality_flags_json"))
    elif "quality_flags" in payload:
        payload["quality_flags"] = _normalize_flags(payload["quality_flags"])
    return payload


def _clean_mongo_doc(doc: dict[str, Any] | None) -> dict[str, Any]:
    if not doc:
        return {}
    payload = dict(doc)
    payload.pop("_id", None)
    if "quality_flags_json" in payload and "quality_flags" not in payload:
        payload["quality_flags"] = _loads_flags(payload.pop("quality_flags_json"))
    if "quality_flags" in payload:
        payload["quality_flags"] = _normalize_flags(payload["quality_flags"])
    return payload


def _loads_flags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if not value:
        return []
    try:
        data = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [str(item) for item in data]


def _normalize_flags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    return _loads_flags(value)
