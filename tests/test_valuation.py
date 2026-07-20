from pathlib import Path

from src.config import load_config
from src.database import connect, init_db, upsert_listings, upsert_price_snapshots
from src.schemas import PropertyInput
from src.valuation import estimate_property


def test_estimate_property_from_comparables(tmp_path: Path):
    db_path = tmp_path / "market.sqlite"
    cfg = load_config("config/projects.yaml")
    now = "2026-06-13T10:00:00+00:00"
    records = []
    for idx, price in enumerate([4.0, 4.3, 4.6, 4.9, 5.2], start=1):
        records.append(
            {
                "source": "test",
                "source_url": f"https://example.com/{idx}",
                "external_id": str(idx),
                "first_seen_at": now,
                "last_seen_at": now,
                "observed_at": now,
                "title": f"Vinhomes Smart City 2PN {idx}",
                "address": "P. Tây Mỗ",
                "project_slug": "vinhomes-smart-city",
                "project_name": "Vinhomes Smart City",
                "property_type": "apartment",
                "purpose": "sale",
                "price_total_vnd": price * 1_000_000_000,
                "price_per_m2_vnd": price * 1_000_000_000 / 55,
                "rent_monthly_vnd": None,
                "area_m2": 55,
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
                "dedupe_key": f"test:{idx}",
            }
        )
    conn = connect(db_path)
    init_db(conn)
    upsert_listings(conn, records)
    upsert_price_snapshots(
        conn,
        [
            {
                "source": "vinhomesland",
                "source_url": "https://vinhomesland.vn/vinhomes-smart-city/",
                "external_id": "snapshot-1",
                "observed_at": now,
                "project_slug": "vinhomes-smart-city",
                "project_name": "Vinhomes Smart City",
                "property_type": "apartment",
                "purpose": "sale",
                "label": "Căn hộ 2PN",
                "subdivision": None,
                "area_min_m2": 53,
                "area_max_m2": 71,
                "price_min_vnd": 3_100_000_000,
                "price_max_vnd": 7_100_000_000,
                "price_per_m2_min_vnd": 43_661_971,
                "price_per_m2_max_vnd": 133_962_264,
                "basis": "published_price_range",
                "quality_flags": ["aggregate_price_snapshot"],
                "dedupe_key": "price_snapshot:test:1",
            }
        ],
    )
    conn.commit()
    conn.close()

    result = estimate_property(
        PropertyInput(
            project="vinhomes-smart-city",
            purpose="sale",
            property_type="apartment",
            area_m2=55,
            bedrooms=2,
            subdivision="Sapphire",
        ),
        cfg,
        db_path,
    )
    assert result.sample_size == 5
    assert result.p50_total_vnd > 4_000_000_000
    assert len(result.comparable_listings) > 0
    assert len(result.reference_price_snapshots) == 1
    assert result.reference_price_snapshots[0].basis == "published_price_range"
