from pathlib import Path

from src.config import load_config
from src.database import connect, init_db, upsert_listings
from src.evaluation import evaluate_market_data
from src.valuation import load_market_frame


def test_evaluation_detects_cross_source_duplicates(tmp_path: Path):
    db_path = tmp_path / "market.sqlite"
    now = "2026-06-18T00:00:00+00:00"
    duplicate_a = _listing(
        source="batdongsan",
        source_url="https://example.com/a",
        dedupe_key="batdongsan:a",
        now=now,
    )
    duplicate_b = _listing(
        source="onehousing",
        source_url="https://example.com/b",
        dedupe_key="onehousing:b",
        now=now,
    )
    unique = _listing(
        source="vinhomesonline",
        source_url="https://example.com/c",
        dedupe_key="vinhomesonline:c",
        now=now,
        price_total_vnd=4_750_000_000,
    )

    conn = connect(db_path)
    init_db(conn)
    upsert_listings(conn, [duplicate_a, duplicate_b, unique])
    conn.commit()
    conn.close()

    cfg = load_config("config/projects.yaml")
    evaluation = evaluate_market_data(cfg, db_path)
    frame = load_market_frame(db_path)

    assert evaluation.raw_listing_rows == 3
    assert evaluation.deduped_listing_rows == 2
    assert evaluation.duplicate_listing_rows == 1
    assert evaluation.duplicate_groups[0]["rows"] == 2
    assert len(frame) == 2


def _listing(
    *,
    source: str,
    source_url: str,
    dedupe_key: str,
    now: str,
    price_total_vnd: int = 4_500_000_000,
) -> dict:
    return {
        "source": source,
        "source_url": source_url,
        "external_id": dedupe_key,
        "first_seen_at": now,
        "last_seen_at": now,
        "observed_at": now,
        "title": "Vinhomes Smart City S303 2PN 54m2",
        "address": "S303, Vinhomes Smart City, Tây Mỗ",
        "project_slug": "vinhomes-smart-city",
        "project_name": "Vinhomes Smart City",
        "property_type": "apartment",
        "purpose": "sale",
        "price_total_vnd": price_total_vnd,
        "price_per_m2_vnd": price_total_vnd / 54,
        "rent_monthly_vnd": None,
        "area_m2": 54,
        "bedrooms": 2,
        "bathrooms": 1,
        "floor_number": 12,
        "total_floors": None,
        "subdivision": "Sapphire",
        "tower": "S303",
        "view": "internal",
        "furniture": "full",
        "legal_status": None,
        "is_verified": 0,
        "quality_flags": [],
        "dedupe_key": dedupe_key,
    }
