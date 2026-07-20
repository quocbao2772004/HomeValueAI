from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "market.sqlite"


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS raw_fetch (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  url TEXT NOT NULL,
  project_slug TEXT,
  purpose TEXT,
  property_type TEXT,
  fetcher TEXT NOT NULL,
  status_code INTEGER,
  fetched_at TEXT NOT NULL,
  blocked INTEGER NOT NULL DEFAULT 0,
  content_path TEXT,
  content_hash TEXT NOT NULL,
  error TEXT,
  UNIQUE(url, content_hash)
);

CREATE TABLE IF NOT EXISTS listing_observation (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  source_url TEXT,
  external_id TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  title TEXT,
  address TEXT,
  project_slug TEXT NOT NULL,
  project_name TEXT NOT NULL,
  property_type TEXT NOT NULL,
  purpose TEXT NOT NULL,
  price_total_vnd REAL,
  price_per_m2_vnd REAL,
  rent_monthly_vnd REAL,
  area_m2 REAL,
  bedrooms INTEGER,
  bathrooms INTEGER,
  floor_number INTEGER,
  total_floors INTEGER,
  subdivision TEXT,
  tower TEXT,
  view TEXT,
  furniture TEXT,
  legal_status TEXT,
  is_verified INTEGER NOT NULL DEFAULT 0,
  quality_flags_json TEXT NOT NULL DEFAULT '[]',
  dedupe_key TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_listing_scope
ON listing_observation(project_slug, property_type, purpose, bedrooms, observed_at);

CREATE TABLE IF NOT EXISTS price_snapshot (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  source_url TEXT,
  external_id TEXT,
  observed_at TEXT NOT NULL,
  project_slug TEXT NOT NULL,
  project_name TEXT NOT NULL,
  property_type TEXT NOT NULL,
  purpose TEXT NOT NULL,
  label TEXT,
  subdivision TEXT,
  area_min_m2 REAL,
  area_max_m2 REAL,
  price_min_vnd REAL,
  price_max_vnd REAL,
  price_per_m2_min_vnd REAL,
  price_per_m2_max_vnd REAL,
  basis TEXT NOT NULL,
  quality_flags_json TEXT NOT NULL DEFAULT '[]',
  dedupe_key TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_price_snapshot_scope
ON price_snapshot(project_slug, property_type, purpose, observed_at);

CREATE TABLE IF NOT EXISTS property_candidate (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  source_url TEXT,
  external_id TEXT,
  observed_at TEXT NOT NULL,
  raw_project_name TEXT,
  mapped_project_slug TEXT,
  title TEXT,
  address TEXT,
  property_type TEXT,
  purpose TEXT,
  price_total_vnd REAL,
  price_per_m2_vnd REAL,
  rent_monthly_vnd REAL,
  area_m2 REAL,
  bedrooms INTEGER,
  bathrooms INTEGER,
  quality_flags_json TEXT NOT NULL DEFAULT '[]',
  dedupe_key TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_property_candidate_source
ON property_candidate(source, mapped_project_slug, observed_at);

CREATE TABLE IF NOT EXISTS verified_transaction (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  project_slug TEXT NOT NULL,
  project_name TEXT NOT NULL,
  property_type TEXT NOT NULL,
  purpose TEXT NOT NULL,
  transaction_price_vnd REAL,
  rent_monthly_vnd REAL,
  area_m2 REAL NOT NULL,
  bedrooms INTEGER,
  subdivision TEXT,
  transaction_date TEXT,
  confidence_score REAL NOT NULL,
  evidence_note TEXT,
  source TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_user (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  credit_balance INTEGER NOT NULL DEFAULT 5,
  pro_expires_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_app_user_email
ON app_user(email);

CREATE TABLE IF NOT EXISTS payment_order (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  user_id INTEGER NOT NULL,
  order_code TEXT NOT NULL UNIQUE,
  plan TEXT NOT NULL,
  amount_vnd INTEGER NOT NULL,
  status TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  bank_bin TEXT NOT NULL,
  bank_account_no TEXT NOT NULL,
  bank_account_name TEXT NOT NULL,
  transfer_content TEXT NOT NULL,
  qr_image_url TEXT NOT NULL,
  paid_at TEXT,
  matched_ref_no TEXT,
  matched_amount_vnd INTEGER,
  raw_transaction_json TEXT,
  FOREIGN KEY(user_id) REFERENCES app_user(id)
);

CREATE INDEX IF NOT EXISTS idx_payment_order_user_status
ON payment_order(user_id, status, created_at);

CREATE INDEX IF NOT EXISTS idx_payment_order_ref
ON payment_order(matched_ref_no);

CREATE TABLE IF NOT EXISTS credit_ledger (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  user_id INTEGER NOT NULL,
  action TEXT NOT NULL,
  delta INTEGER NOT NULL,
  balance_after INTEGER NOT NULL,
  idempotency_key TEXT NOT NULL,
  status TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY(user_id) REFERENCES app_user(id),
  UNIQUE(user_id, action, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_credit_ledger_user_created
ON credit_ledger(user_id, created_at);
"""


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    _ensure_column(conn, "app_user", "pro_expires_at", "TEXT")
    _ensure_column(conn, "app_user", "credit_balance", "INTEGER NOT NULL DEFAULT 5")
    conn.commit()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


@contextmanager
def session(db_path: str | Path = DEFAULT_DB_PATH):
    conn = connect(db_path)
    init_db(conn)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert_listings(conn: sqlite3.Connection, records: Iterable[dict[str, Any]]) -> tuple[int, int]:
    inserted = 0
    updated = 0
    for record in records:
        existing = conn.execute(
            "SELECT id, first_seen_at FROM listing_observation WHERE dedupe_key = ?",
            (record["dedupe_key"],),
        ).fetchone()
        payload = _listing_payload(record)
        if existing:
            payload["first_seen_at"] = existing["first_seen_at"]
            conn.execute(
                """
                UPDATE listing_observation
                SET source=:source, source_url=:source_url, external_id=:external_id,
                    first_seen_at=:first_seen_at, last_seen_at=:last_seen_at, observed_at=:observed_at,
                    title=:title, address=:address, project_slug=:project_slug, project_name=:project_name,
                    property_type=:property_type, purpose=:purpose, price_total_vnd=:price_total_vnd,
                    price_per_m2_vnd=:price_per_m2_vnd, rent_monthly_vnd=:rent_monthly_vnd,
                    area_m2=:area_m2, bedrooms=:bedrooms, bathrooms=:bathrooms,
                    floor_number=:floor_number, total_floors=:total_floors, subdivision=:subdivision,
                    tower=:tower, view=:view, furniture=:furniture, legal_status=:legal_status,
                    is_verified=:is_verified, quality_flags_json=:quality_flags_json
                WHERE dedupe_key=:dedupe_key
                """,
                payload,
            )
            updated += 1
        else:
            conn.execute(
                """
                INSERT INTO listing_observation (
                    source, source_url, external_id, first_seen_at, last_seen_at, observed_at,
                    title, address, project_slug, project_name, property_type, purpose,
                    price_total_vnd, price_per_m2_vnd, rent_monthly_vnd, area_m2, bedrooms,
                    bathrooms, floor_number, total_floors, subdivision, tower, view, furniture,
                    legal_status, is_verified, quality_flags_json, dedupe_key
                ) VALUES (
                    :source, :source_url, :external_id, :first_seen_at, :last_seen_at, :observed_at,
                    :title, :address, :project_slug, :project_name, :property_type, :purpose,
                    :price_total_vnd, :price_per_m2_vnd, :rent_monthly_vnd, :area_m2, :bedrooms,
                    :bathrooms, :floor_number, :total_floors, :subdivision, :tower, :view, :furniture,
                    :legal_status, :is_verified, :quality_flags_json, :dedupe_key
                )
                """,
                payload,
            )
            inserted += 1
    return inserted, updated


def upsert_price_snapshots(conn: sqlite3.Connection, records: Iterable[dict[str, Any]]) -> tuple[int, int]:
    inserted = 0
    updated = 0
    for record in records:
        existing = conn.execute(
            "SELECT id FROM price_snapshot WHERE dedupe_key = ?",
            (record["dedupe_key"],),
        ).fetchone()
        payload = _price_snapshot_payload(record)
        if existing:
            conn.execute(
                """
                UPDATE price_snapshot
                SET source=:source, source_url=:source_url, external_id=:external_id,
                    observed_at=:observed_at, project_slug=:project_slug, project_name=:project_name,
                    property_type=:property_type, purpose=:purpose, label=:label, subdivision=:subdivision,
                    area_min_m2=:area_min_m2, area_max_m2=:area_max_m2,
                    price_min_vnd=:price_min_vnd, price_max_vnd=:price_max_vnd,
                    price_per_m2_min_vnd=:price_per_m2_min_vnd,
                    price_per_m2_max_vnd=:price_per_m2_max_vnd,
                    basis=:basis, quality_flags_json=:quality_flags_json
                WHERE dedupe_key=:dedupe_key
                """,
                payload,
            )
            updated += 1
        else:
            conn.execute(
                """
                INSERT INTO price_snapshot (
                    source, source_url, external_id, observed_at, project_slug, project_name,
                    property_type, purpose, label, subdivision, area_min_m2, area_max_m2,
                    price_min_vnd, price_max_vnd, price_per_m2_min_vnd, price_per_m2_max_vnd,
                    basis, quality_flags_json, dedupe_key
                ) VALUES (
                    :source, :source_url, :external_id, :observed_at, :project_slug, :project_name,
                    :property_type, :purpose, :label, :subdivision, :area_min_m2, :area_max_m2,
                    :price_min_vnd, :price_max_vnd, :price_per_m2_min_vnd, :price_per_m2_max_vnd,
                    :basis, :quality_flags_json, :dedupe_key
                )
                """,
                payload,
            )
            inserted += 1
    return inserted, updated


def upsert_property_candidates(conn: sqlite3.Connection, records: Iterable[dict[str, Any]]) -> tuple[int, int]:
    inserted = 0
    updated = 0
    for record in records:
        existing = conn.execute(
            "SELECT id FROM property_candidate WHERE dedupe_key = ?",
            (record["dedupe_key"],),
        ).fetchone()
        payload = _property_candidate_payload(record)
        if existing:
            conn.execute(
                """
                UPDATE property_candidate
                SET source=:source, source_url=:source_url, external_id=:external_id,
                    observed_at=:observed_at, raw_project_name=:raw_project_name,
                    mapped_project_slug=:mapped_project_slug, title=:title, address=:address,
                    property_type=:property_type, purpose=:purpose,
                    price_total_vnd=:price_total_vnd, price_per_m2_vnd=:price_per_m2_vnd,
                    rent_monthly_vnd=:rent_monthly_vnd, area_m2=:area_m2,
                    bedrooms=:bedrooms, bathrooms=:bathrooms,
                    quality_flags_json=:quality_flags_json
                WHERE dedupe_key=:dedupe_key
                """,
                payload,
            )
            updated += 1
        else:
            conn.execute(
                """
                INSERT INTO property_candidate (
                    source, source_url, external_id, observed_at, raw_project_name,
                    mapped_project_slug, title, address, property_type, purpose,
                    price_total_vnd, price_per_m2_vnd, rent_monthly_vnd, area_m2,
                    bedrooms, bathrooms, quality_flags_json, dedupe_key
                ) VALUES (
                    :source, :source_url, :external_id, :observed_at, :raw_project_name,
                    :mapped_project_slug, :title, :address, :property_type, :purpose,
                    :price_total_vnd, :price_per_m2_vnd, :rent_monthly_vnd, :area_m2,
                    :bedrooms, :bathrooms, :quality_flags_json, :dedupe_key
                )
                """,
                payload,
            )
            inserted += 1
    return inserted, updated


def _listing_payload(record: dict[str, Any]) -> dict[str, Any]:
    payload = dict(record)
    payload["quality_flags_json"] = json.dumps(payload.pop("quality_flags", []), ensure_ascii=False)
    return payload


def _price_snapshot_payload(record: dict[str, Any]) -> dict[str, Any]:
    payload = dict(record)
    payload["quality_flags_json"] = json.dumps(payload.pop("quality_flags", []), ensure_ascii=False)
    return payload


def _property_candidate_payload(record: dict[str, Any]) -> dict[str, Any]:
    payload = dict(record)
    payload["quality_flags_json"] = json.dumps(payload.pop("quality_flags", []), ensure_ascii=False)
    return payload
