from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.config import AppConfig, get_nested
from src.database import DEFAULT_DB_PATH
from src.dedupe import dedupe_market_frame
from src.normalization import infer_project_slug
from src.schemas import ComparableListing, PriceSnapshotReference, PropertyInput, ValuationResponse
from src.storage import load_market_frame as storage_load_market_frame
from src.storage import load_price_snapshot_frame as storage_load_price_snapshot_frame
from src.text import text_key


def load_market_frame(db_path: str | Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    return dedupe_market_frame(storage_load_market_frame(db_path))


def load_price_snapshot_frame(db_path: str | Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    return storage_load_price_snapshot_frame(db_path)


def estimate_property(prop: PropertyInput, config: AppConfig, db_path: str | Path = DEFAULT_DB_PATH) -> ValuationResponse:
    frame = load_market_frame(db_path)
    project_slug = infer_project_slug(config, prop.project, default=prop.project)
    project = config.project_by_slug.get(project_slug or "")
    if frame.empty or not project:
        raise ValueError("Chưa có dữ liệu listing/transaction phù hợp. Hãy chạy scripts/crawl.py trước.")

    candidates = _scoped_candidates(frame, project.slug, prop)
    if candidates.empty:
        raise ValueError("Không đủ dữ liệu sau khi lọc nhiễu cho yêu cầu này.")

    candidates = candidates.copy()
    candidates["similarity_score"] = candidates.apply(lambda row: _similarity(row, prop), axis=1)
    candidates = candidates.sort_values(["similarity_score", "observed_at"], ascending=[False, False])

    valuation = config.raw.get("valuation", {})
    limit = int(valuation.get("comparable_limit", 8))
    comps = candidates.head(limit)
    target = _target_series(candidates, prop)
    weights = np.clip(candidates["similarity_score"].to_numpy(dtype=float), 0.05, 1.0)
    q10, q50, q90 = _weighted_quantiles(target.to_numpy(dtype=float), weights, [0.1, 0.5, 0.9])

    if prop.purpose == "sale":
        p10_total, p50_total, p90_total = q10 * prop.area_m2, q50 * prop.area_m2, q90 * prop.area_m2
        p10_ppm, p50_ppm, p90_ppm = q10, q50, q90
    else:
        p10_total, p50_total, p90_total = q10, q50, q90
        p10_ppm = p50_ppm = p90_ppm = None

    sample_size = int(len(candidates))
    confidence = _confidence(sample_size, config)
    snapshot_refs = price_snapshot_references(config, prop.project, prop.purpose, prop.property_type, db_path=db_path)
    top_factors = _top_factors(prop, candidates)
    if snapshot_refs:
        top_factors.append(
            "Có thêm bảng giá tham khảo từ nguồn dự án/đại lý, được tách khỏi mẫu listing để tránh làm lệch comps."
        )
    return ValuationResponse(
        purpose=prop.purpose,
        project=project.name,
        property_type=prop.property_type,
        estimate_basis="listing_comparables_plus_verified_transactions_with_snapshot_reference",
        p10_total_vnd=float(round(p10_total)),
        p50_total_vnd=float(round(p50_total)),
        p90_total_vnd=float(round(p90_total)),
        p10_price_per_m2_vnd=float(round(p10_ppm)) if p10_ppm is not None else None,
        p50_price_per_m2_vnd=float(round(p50_ppm)) if p50_ppm is not None else None,
        p90_price_per_m2_vnd=float(round(p90_ppm)) if p90_ppm is not None else None,
        sample_size=sample_size,
        confidence=confidence,
        data_freshness=_freshness(candidates),
        comparable_listings=[_to_comparable(row) for _, row in comps.iterrows()],
        reference_price_snapshots=snapshot_refs,
        top_factors=top_factors[:6],
        caveat=config.raw.get("market", {}).get(
            "caveat",
            "Ước tính dựa trên giá rao đã lọc nhiễu; chưa phải giá giao dịch chốt tuyệt đối.",
        ),
    )


def market_trends(
    config: AppConfig,
    project: str,
    purpose: str = "sale",
    property_type: str | None = None,
    bedrooms: int | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    frame = load_market_frame(db_path)
    project_slug = infer_project_slug(config, project, default=project)
    project_cfg = config.project_by_slug.get(project_slug or "")
    if frame.empty or not project_cfg:
        raise ValueError("Chưa có dữ liệu để tính trend.")
    df = frame[(frame["project_slug"] == project_cfg.slug) & (frame["purpose"] == purpose)].copy()
    if property_type:
        df = df[df["property_type"] == property_type]
    if bedrooms is not None and "bedrooms" in df:
        df = df[df["bedrooms"] == bedrooms]
    if purpose == "sale":
        df = df[pd.notna(df["price_per_m2_vnd"])]
        metric = "price_per_m2_vnd"
    else:
        df = df[pd.notna(df["rent_monthly_vnd"])]
        metric = "rent_monthly_vnd"
    if df.empty:
        raise ValueError("Không có dữ liệu trend sau filter.")

    df["observed_dt"] = pd.to_datetime(df["observed_at"], errors="coerce", utc=True)
    now = datetime.now(UTC)
    windows = {}

    for label, days in {"1m": 30, "3m": 90, "6m": 180, "12m": 365}.items():
        sub = df[df["observed_dt"] >= now - pd.Timedelta(days=days)]
        windows[label] = {
            "sample_size": int(len(sub)),
            "median": float(round(sub[metric].median())) if len(sub) else None,
            "p10": float(round(sub[metric].quantile(0.1))) if len(sub) else None,
            "p90": float(round(sub[metric].quantile(0.9))) if len(sub) else None,
        }
    return {
        "project": project_cfg.name,
        "property_type": property_type,
        "purpose": purpose,
        "bedrooms": bedrooms,
        "windows": windows,
        "reference_price_snapshots": price_snapshot_references(
            config,
            project_cfg.slug,
            purpose,
            property_type,
            db_path=db_path,
        ),
        "caveat": config.raw.get("market", {}).get("caveat", ""),
    }


def price_snapshot_references(
    config: AppConfig,
    project: str,
    purpose: str = "sale",
    property_type: str | None = None,
    limit: int = 12,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[PriceSnapshotReference]:
    snapshots = load_price_snapshot_frame(db_path)
    project_slug = infer_project_slug(config, project, default=project)
    project_cfg = config.project_by_slug.get(project_slug or "")
    if snapshots.empty or not project_cfg:
        return []
    df = snapshots[(snapshots["project_slug"] == project_cfg.slug) & (snapshots["purpose"] == purpose)].copy()
    if property_type:
        exact = df[df["property_type"] == property_type]
        if not exact.empty:
            df = exact
    if df.empty:
        return []
    df["observed_dt"] = pd.to_datetime(df["observed_at"], errors="coerce", utc=True)
    df = df.sort_values(["observed_dt", "property_type", "subdivision", "label"], ascending=[False, True, True, True])
    return [_to_price_snapshot_reference(row) for _, row in df.head(limit).iterrows()]


def _scoped_candidates(frame: pd.DataFrame, project_slug: str, prop: PropertyInput) -> pd.DataFrame:
    df = frame[(frame["purpose"] == prop.purpose)].copy()
    df = df[df["quality_flags"].apply(lambda flags: not any("outlier" in flag or "missing" in flag for flag in flags))]
    if prop.purpose == "sale":
        df = df[pd.notna(df["price_per_m2_vnd"]) & pd.notna(df["area_m2"])]
    else:
        df = df[pd.notna(df["rent_monthly_vnd"]) & pd.notna(df["area_m2"])]

    same_project = df[df["project_slug"] == project_slug]
    same_type = same_project[same_project["property_type"] == prop.property_type]
    if len(same_type) >= 3:
        return same_type
    if len(same_project) >= 3:
        return same_project
    same_type_all = df[df["property_type"] == prop.property_type]
    return same_type_all if len(same_type_all) >= 3 else df


def _target_series(candidates: pd.DataFrame, prop: PropertyInput) -> pd.Series:
    if prop.purpose == "sale":
        return candidates["price_per_m2_vnd"].astype(float)
    return candidates["rent_monthly_vnd"].astype(float)


def _similarity(row: pd.Series, prop: PropertyInput) -> float:
    score = 1.0
    if pd.notna(row.get("area_m2")):
        score -= min(abs(float(row["area_m2"]) - prop.area_m2) / max(prop.area_m2, 1), 0.6) * 0.45
    if prop.bedrooms is not None and pd.notna(row.get("bedrooms")):
        score -= min(abs(int(row["bedrooms"]) - prop.bedrooms), 3) * 0.08
    if prop.subdivision and row.get("subdivision") and text_key(prop.subdivision) == text_key(row["subdivision"]):
        score += 0.08
    if prop.view and row.get("view") and text_key(prop.view) == text_key(row["view"]):
        score += 0.04
    if prop.furniture and row.get("furniture") and text_key(prop.furniture) == text_key(row["furniture"]):
        score += 0.03
    if int(row.get("is_verified") or 0) == 1:
        score += 0.08
    return float(max(0.05, min(score, 1.2)))


def _weighted_quantiles(values: np.ndarray, weights: np.ndarray, quantiles: list[float]) -> list[float]:
    mask = np.isfinite(values) & np.isfinite(weights)
    values, weights = values[mask], weights[mask]
    if len(values) == 0:
        raise ValueError("Không có giá trị hợp lệ để tính quantile.")
    order = np.argsort(values)
    values, weights = values[order], weights[order]
    cumulative = np.cumsum(weights)
    cumulative /= cumulative[-1]
    return [float(np.interp(q, cumulative, values)) for q in quantiles]


def _confidence(sample_size: int, config: AppConfig) -> str:
    strong = int(get_nested(config, "valuation", "min_strong_sample_size", default=50))
    medium = int(get_nested(config, "valuation", "min_medium_sample_size", default=15))
    if sample_size >= strong:
        return "high"
    if sample_size >= medium:
        return "medium"
    return "low"


def _freshness(df: pd.DataFrame) -> str | None:
    if df.empty or "observed_at" not in df:
        return None
    value = pd.to_datetime(df["observed_at"], errors="coerce", utc=True).max()
    if pd.isna(value):
        return None
    return value.isoformat()


def _to_comparable(row: pd.Series) -> ComparableListing:
    return ComparableListing(
        title=_clean_optional(row.get("title")),
        address=_clean_optional(row.get("address")),
        project=str(row.get("project_name")),
        property_type=str(row.get("property_type")),
        purpose=str(row.get("purpose")),
        price_total_vnd=_float_optional(row.get("price_total_vnd")),
        price_per_m2_vnd=_float_optional(row.get("price_per_m2_vnd")),
        rent_monthly_vnd=_float_optional(row.get("rent_monthly_vnd")),
        area_m2=_float_optional(row.get("area_m2")),
        bedrooms=_int_optional(row.get("bedrooms")),
        subdivision=_clean_optional(row.get("subdivision")),
        view=_clean_optional(row.get("view")),
        furniture=_clean_optional(row.get("furniture")),
        observed_at=_clean_optional(row.get("observed_at")),
        source_url=_clean_optional(row.get("source_url")),
        similarity_score=round(float(row.get("similarity_score", 0)), 3),
    )


def _to_price_snapshot_reference(row: pd.Series) -> PriceSnapshotReference:
    return PriceSnapshotReference(
        source=str(row.get("source")),
        source_url=_clean_optional(row.get("source_url")),
        observed_at=_clean_optional(row.get("observed_at")),
        project=str(row.get("project_name")),
        property_type=str(row.get("property_type")),
        purpose=str(row.get("purpose")),
        label=_clean_optional(row.get("label")),
        subdivision=_clean_optional(row.get("subdivision")),
        area_min_m2=_float_optional(row.get("area_min_m2")),
        area_max_m2=_float_optional(row.get("area_max_m2")),
        price_min_vnd=_float_optional(row.get("price_min_vnd")),
        price_max_vnd=_float_optional(row.get("price_max_vnd")),
        price_per_m2_min_vnd=_float_optional(row.get("price_per_m2_min_vnd")),
        price_per_m2_max_vnd=_float_optional(row.get("price_per_m2_max_vnd")),
        basis=str(row.get("basis")),
    )


def _top_factors(prop: PropertyInput, candidates: pd.DataFrame) -> list[str]:
    factors = []
    median_area = candidates["area_m2"].median()
    if pd.notna(median_area):
        if prop.area_m2 > median_area * 1.15:
            factors.append("Diện tích lớn hơn nhóm so sánh nên tổng giá cao hơn, dù đơn giá/m² có thể mềm hơn.")
        elif prop.area_m2 < median_area * 0.85:
            factors.append("Diện tích nhỏ hơn nhóm so sánh nên đơn giá/m² thường cao hơn.")
    if prop.bedrooms is not None and "bedrooms" in candidates and pd.notna(candidates["bedrooms"].median()):
        median_bedrooms = candidates["bedrooms"].median()
        if prop.bedrooms > median_bedrooms:
            factors.append("Số phòng ngủ cao hơn median nhóm so sánh, phù hợp nhóm gia đình và hỗ trợ thanh khoản.")
        elif prop.bedrooms < median_bedrooms:
            factors.append("Số phòng ngủ thấp hơn median nhóm so sánh, phù hợp căn nhỏ/tài chính thấp hơn.")
    if prop.view:
        factors.append(f"View '{prop.view}' được đưa vào so khớp với các căn tương đồng khi dữ liệu có thông tin view.")
    if prop.furniture:
        factors.append(f"Tình trạng nội thất '{prop.furniture}' ảnh hưởng tới mức chênh so với căn bàn giao trống/cơ bản.")
    if not prop.view and not prop.furniture:
        factors.append("Chưa cung cấp thông tin view và nội thất, kết quả định giá có thể có sai số lớn hơn so với thực tế.")
    factors.append("Nguồn hiện tại là giá rao công khai; khoảng P10-P90 thể hiện độ nhiễu và khả năng thương lượng.")
    return factors[:5]


def _float_optional(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def _int_optional(value: Any) -> int | None:
    number = _float_optional(value)
    return int(number) if number is not None else None


def _clean_optional(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    return text or None
