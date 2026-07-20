from src.storage import MongoStore, SQLiteStore, get_store, resolve_backend


def test_storage_auto_falls_back_to_sqlite(monkeypatch, tmp_path):
    monkeypatch.setenv("VALUATION_STORAGE_BACKEND", "auto")
    monkeypatch.delenv("MONGODB_URI", raising=False)

    assert resolve_backend() == "sqlite"
    assert isinstance(get_store(tmp_path / "market.sqlite"), SQLiteStore)


def test_storage_auto_selects_mongo_when_uri_exists(monkeypatch):
    monkeypatch.setenv("VALUATION_STORAGE_BACKEND", "auto")
    monkeypatch.setenv("MONGODB_URI", "mongodb://example.invalid:27017")

    assert resolve_backend() == "mongo"
    store = get_store()
    assert isinstance(store, MongoStore)
    assert store.db_name == "homevalue_market"


def test_sqlite_store_verified_transaction_loads_as_market_frame(monkeypatch, tmp_path):
    monkeypatch.setenv("VALUATION_STORAGE_BACKEND", "sqlite")
    store = get_store(tmp_path / "market.sqlite")
    store.init()

    inserted_id = store.insert_verified_transaction(
        {
            "created_at": "2026-06-17T00:00:00+00:00",
            "project_slug": "vinhomes-smart-city",
            "project_name": "Vinhomes Smart City",
            "property_type": "apartment",
            "purpose": "sale",
            "transaction_price_vnd": 5_500_000_000,
            "rent_monthly_vnd": None,
            "area_m2": 55,
            "bedrooms": 2,
            "subdivision": "Sapphire",
            "transaction_date": "2026-06-16",
            "confidence_score": 0.9,
            "evidence_note": "test import",
            "source": "manual",
        }
    )

    frame = store.load_market_frame()
    assert inserted_id == 1
    assert len(frame) == 1
    assert frame.iloc[0]["basis"] == "verified_transaction"
    assert frame.iloc[0]["is_verified"] == 1
    assert frame.iloc[0]["price_per_m2_vnd"] == 100_000_000
