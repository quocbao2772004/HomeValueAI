from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import AppConfig, get_nested
from src.database import DEFAULT_DB_PATH
from src.dedupe import enrich_canonical_dedupe
from src.schemas import DataEvaluationResponse
from src.storage import get_store


def evaluate_market_data(
    config: AppConfig,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> DataEvaluationResponse:
    store = get_store(db_path)
    listings = store.collection_frame("listing_observation")
    snapshots = store.collection_frame("price_snapshot")
    candidates = store.collection_frame("property_candidate")
    enriched = enrich_canonical_dedupe(listings)
    deduped = _deduped(enriched)
    expected_sources = _expected_sources(config)
    observed_sources = _observed_sources(listings, snapshots, candidates)
    duplicate_rows = max(len(listings) - len(deduped), 0)
    duplicate_rate = duplicate_rows / len(listings) if len(listings) else 0.0

    return DataEvaluationResponse(
        generated_at=datetime.now(UTC).isoformat(),
        raw_listing_rows=int(len(listings)),
        deduped_listing_rows=int(len(deduped)),
        duplicate_listing_rows=int(duplicate_rows),
        duplicate_rate=round(float(duplicate_rate), 4),
        expected_sources=expected_sources,
        observed_sources=observed_sources,
        missing_sources=sorted(set(expected_sources) - set(observed_sources)),
        source_counts=_source_counts(listings, deduped, snapshots, candidates),
        project_counts=_project_counts(deduped),
        quality_flag_counts=_quality_flag_counts(listings),
        duplicate_groups=_duplicate_groups(enriched),
        valuation_readiness=_valuation_readiness(config, deduped),
        chart={
            "by_project": _chart_by_project(deduped),
            "by_source": _chart_by_source(listings, deduped, snapshots, candidates),
        },
        notes=_notes(listings, deduped, snapshots, candidates, expected_sources, observed_sources, duplicate_rows),
    )


def _deduped(enriched: pd.DataFrame) -> pd.DataFrame:
    if enriched.empty or "is_canonical_listing" not in enriched:
        return enriched.copy()
    return enriched[enriched["is_canonical_listing"]].copy()


def _expected_sources(config: AppConfig) -> list[str]:
    sources: set[str] = set()
    for project in config.projects:
        for page in project.pages:
            sources.add(page.source if page.source != "auto" else "batdongsan")
    for page in config.raw.get("crawl", {}).get("extra_pages", []):
        sources.add(str(page.get("source") or "batdongsan"))
    return sorted(sources)


def _observed_sources(*frames: pd.DataFrame) -> list[str]:
    sources: set[str] = set()
    for frame in frames:
        if frame.empty or "source" not in frame:
            continue
        sources.update(str(source) for source in frame["source"].dropna().unique() if str(source))
    return sorted(sources)


def _source_counts(raw: pd.DataFrame, deduped: pd.DataFrame, snapshots: pd.DataFrame, candidates: pd.DataFrame) -> list[dict[str, Any]]:
    sources = sorted(set(_observed_sources(raw, deduped, snapshots, candidates)))
    rows = []
    for source in sources:
        raw_count = int((raw["source"] == source).sum()) if "source" in raw else 0
        unique_count = int((deduped["source"] == source).sum()) if "source" in deduped else 0
        snapshot_count = int((snapshots["source"] == source).sum()) if "source" in snapshots else 0
        candidate_count = int((candidates["source"] == source).sum()) if "source" in candidates else 0
        rows.append(
            {
                "source": source,
                "raw_rows": raw_count + snapshot_count + candidate_count,
                "listing_rows": raw_count,
                "deduped_rows": unique_count,
                "duplicate_rows": max(raw_count - unique_count, 0),
                "price_snapshot_rows": snapshot_count,
                "candidate_rows": candidate_count,
            }
        )
    return rows


def _project_counts(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    grouped = (
        frame.groupby(["project_name", "purpose", "property_type"], dropna=False)
        .size()
        .reset_index(name="sample_size")
        .sort_values(["sample_size", "project_name"], ascending=[False, True])
    )
    return [
        {
            "project": str(row["project_name"]),
            "purpose": str(row["purpose"]),
            "property_type": str(row["property_type"]),
            "sample_size": int(row["sample_size"]),
        }
        for _, row in grouped.iterrows()
    ]


def _quality_flag_counts(frame: pd.DataFrame) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    if frame.empty or "quality_flags" not in frame:
        return []
    for flags in frame["quality_flags"]:
        for flag in flags if isinstance(flags, list) else []:
            counts[str(flag)] = counts.get(str(flag), 0) + 1
    return [{"flag": flag, "count": count} for flag, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)]


def _duplicate_groups(enriched: pd.DataFrame) -> list[dict[str, Any]]:
    if enriched.empty or "canonical_key" not in enriched:
        return []
    duplicate_frame = enriched[enriched["duplicate_group_size"] > 1].copy()
    if duplicate_frame.empty:
        return []
    groups = []
    for key, group in duplicate_frame.groupby("canonical_key"):
        sources = sorted({str(source) for source in group.get("source", pd.Series(dtype=str)).dropna().unique()})
        groups.append(
            {
                "canonical_key": str(key),
                "rows": int(len(group)),
                "sources": sources,
                "sample_title": _first_text(group, "title"),
                "project": _first_text(group, "project_name"),
                "area_m2": _first_number(group, "area_m2"),
                "price_total_vnd": _first_number(group, "price_total_vnd"),
                "rent_monthly_vnd": _first_number(group, "rent_monthly_vnd"),
            }
        )
    return sorted(groups, key=lambda item: item["rows"], reverse=True)[:10]


def _valuation_readiness(config: AppConfig, frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    medium = int(get_nested(config, "valuation", "min_medium_sample_size", default=15))
    strong = int(get_nested(config, "valuation", "min_strong_sample_size", default=50))
    rows = []
    for item in _project_counts(frame):
        sample_size = item["sample_size"]
        if sample_size >= strong:
            status = "high"
        elif sample_size >= medium:
            status = "medium"
        else:
            status = "low"
        rows.append({**item, "status": status})
    return rows


def _chart_by_project(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    grouped = frame.groupby("project_name", dropna=False).size().reset_index(name="deduped_rows")
    grouped = grouped.sort_values("deduped_rows", ascending=False)
    return [{"label": str(row["project_name"]), "value": int(row["deduped_rows"])} for _, row in grouped.iterrows()]


def _chart_by_source(raw: pd.DataFrame, deduped: pd.DataFrame, snapshots: pd.DataFrame, candidates: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {
            "label": row["source"],
            "raw": row["raw_rows"],
            "deduped": row["deduped_rows"],
        }
        for row in _source_counts(raw, deduped, snapshots, candidates)
    ]


def _notes(
    raw: pd.DataFrame,
    deduped: pd.DataFrame,
    snapshots: pd.DataFrame,
    candidates: pd.DataFrame,
    expected_sources: list[str],
    observed_sources: list[str],
    duplicate_rows: int,
) -> list[str]:
    notes = [
        f"Đã gộp {duplicate_rows} dòng duplicate chéo nguồn trước khi định giá.",
        f"Dữ liệu định giá dùng {len(deduped)} mẫu listing unique; tổng dữ liệu crawl gồm {len(raw)} listings, {len(snapshots)} bảng giá và {len(candidates)} candidates.",
        f"Đã quan sát dữ liệu từ {len(observed_sources)} nguồn: {', '.join(observed_sources) or 'chưa có'}.",
    ]
    missing = sorted(set(expected_sources) - set(observed_sources))
    if missing:
        notes.append(f"Chưa có mẫu listing hợp lệ từ: {', '.join(missing)}.")
    if not raw.empty and "quality_flags" in raw:
        flagged = int(raw["quality_flags"].apply(lambda flags: bool(flags)).sum())
        notes.append(f"{flagged} dòng có quality flag và được lọc/giảm trọng số tùy luồng xử lý.")
    return notes


def _first_text(frame: pd.DataFrame, column: str) -> str | None:
    if column not in frame:
        return None
    values = frame[column].dropna().astype(str)
    values = values[values.str.len() > 0]
    return values.iloc[0] if len(values) else None


def _first_number(frame: pd.DataFrame, column: str) -> float | None:
    if column not in frame:
        return None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    return float(values.iloc[0]) if len(values) else None
