from __future__ import annotations

import math
from typing import Any

import pandas as pd

from src.text import text_key

SOURCE_PRIORITY = {
    "verified": 0,
    "verified_transaction": 0,
    "onehousing": 1,
    "vinhomesonline": 2,
    "batdongsan": 3,
    "vinhomesland": 4,
}


def enrich_canonical_dedupe(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()

    df = frame.copy()
    if "basis" not in df:
        df["basis"] = "listing"
    df["canonical_key"] = df.apply(canonical_listing_key, axis=1)
    listing_mask = df["basis"].fillna("listing").astype(str).eq("listing")
    group_sizes = df.loc[listing_mask].groupby("canonical_key")["canonical_key"].transform("size")
    df["duplicate_group_size"] = 1
    df.loc[listing_mask, "duplicate_group_size"] = group_sizes.fillna(1).astype(int)
    source_map = (
        df.loc[listing_mask]
        .groupby("canonical_key")["source"]
        .apply(lambda values: ", ".join(sorted({str(value) for value in values if str(value) and str(value) != "nan"})))
        .to_dict()
    )
    df["duplicate_sources"] = df["canonical_key"].map(source_map).fillna("")
    df["_dedupe_rank"] = df.apply(_dedupe_rank, axis=1)
    df["_observed_dt"] = pd.to_datetime(df.get("observed_at"), errors="coerce", utc=True)
    df = df.sort_values(
        ["canonical_key", "_dedupe_rank", "_observed_dt"],
        ascending=[True, True, False],
        kind="mergesort",
    )
    df["is_canonical_listing"] = True
    df.loc[listing_mask, "is_canonical_listing"] = ~df.loc[listing_mask].duplicated("canonical_key", keep="first")
    return df.drop(columns=["_dedupe_rank", "_observed_dt"])


def dedupe_market_frame(frame: pd.DataFrame) -> pd.DataFrame:
    enriched = enrich_canonical_dedupe(frame)
    if enriched.empty or "is_canonical_listing" not in enriched:
        return enriched
    return enriched[enriched["is_canonical_listing"]].copy()


def canonical_listing_key(row: pd.Series | dict[str, Any]) -> str:
    basis = _clean(row.get("basis", "listing"))
    if basis and basis != "listing":
        return f"{basis}|{_clean(row.get('source'))}|{_clean(row.get('id'))}|{_clean(row.get('dedupe_key'))}"

    project = _clean(row.get("project_slug") or row.get("project_name"))
    purpose = _clean(row.get("purpose"))
    property_type = _clean(row.get("property_type"))
    area = _bucket(row.get("area_m2"), 1)
    bedrooms = _bucket(row.get("bedrooms"), 1)
    price = _price_bucket(row)
    location = _location_fingerprint(row)
    if location == "unknown":
        location = _title_fingerprint(row)
    return "|".join([project, purpose, property_type, area, bedrooms, price, location])


def _dedupe_rank(row: pd.Series) -> tuple[int, int, float]:
    source = _clean(row.get("source"))
    basis = _clean(row.get("basis"))
    priority = SOURCE_PRIORITY.get(basis, SOURCE_PRIORITY.get(source, 50))
    has_source_url = 0 if _clean(row.get("source_url")) else 1
    source_weight = row.get("source_weight")
    try:
        weight_rank = -float(source_weight) if source_weight is not None and not pd.isna(source_weight) else 0.0
    except (TypeError, ValueError):
        weight_rank = 0.0
    return (priority, has_source_url, weight_rank)


def _price_bucket(row: pd.Series | dict[str, Any]) -> str:
    purpose = _clean(row.get("purpose"))
    if purpose == "rent":
        return _bucket(row.get("rent_monthly_vnd"), 1_000_000)
    total = row.get("price_total_vnd")
    if _is_number(total):
        return _bucket(total, 50_000_000)
    return _bucket(row.get("price_per_m2_vnd"), 1_000_000)


def _location_fingerprint(row: pd.Series | dict[str, Any]) -> str:
    parts = [
        row.get("tower"),
        row.get("subdivision"),
        row.get("address"),
    ]
    text = " ".join(_clean(part) for part in parts if _clean(part))
    return text_key(text)[:80] if text else "unknown"


def _title_fingerprint(row: pd.Series | dict[str, Any]) -> str:
    title = text_key(row.get("title") or "")
    tokens = [token for token in title.split() if any(char.isdigit() for char in token)]
    if tokens:
        return " ".join(tokens[:4])[:80]
    return title[:80] if title else "unknown"


def _bucket(value: Any, size: float) -> str:
    if not _is_number(value):
        return "na"
    number = float(value)
    if size <= 1:
        return str(int(round(number)))
    return str(int(round(number / size) * size))


def _is_number(value: Any) -> bool:
    if value is None:
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number)


def _clean(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip().lower()
