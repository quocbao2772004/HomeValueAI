from __future__ import annotations

import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from src.config import AppConfig
from src.env import PROJECT_ROOT, resolve_project_path
from src.normalization import infer_project_slug
from src.schemas import ComparableListing, PropertyInput, ValuationResponse
from src.valuation import estimate_property, price_snapshot_references

DEFAULT_MODEL_PATH = PROJECT_ROOT / "models" / "combined_sale_regression_model.joblib"
DEFAULT_CLEAN_DATA_PATH = PROJECT_ROOT / "data" / "processed" / "combined_clean_listings.csv"


class PredictionUnavailableError(RuntimeError):
    """Raised when the regression artifacts are missing or not usable."""


def estimate_property_with_prediction(
    prop: PropertyInput,
    config: AppConfig,
    db_path: str | Path,
) -> ValuationResponse:
    if prop.purpose != "sale":
        return estimate_property(prop, config, db_path)
    try:
        return estimate_sale_property(prop, config, db_path)
    except PredictionUnavailableError:
        return estimate_property(prop, config, db_path)


def estimate_sale_property(
    prop: PropertyInput,
    config: AppConfig,
    db_path: str | Path,
    model_path: str | Path | None = None,
    clean_data_path: str | Path | None = None,
) -> ValuationResponse:
    model_payload = _load_model_payload(str(_artifact_path(model_path, "VALUATION_REGRESSION_MODEL_PATH", DEFAULT_MODEL_PATH)))
    clean_frame = _load_clean_frame(str(_artifact_path(clean_data_path, "VALUATION_CLEAN_LISTINGS_PATH", DEFAULT_CLEAN_DATA_PATH)))

    project_slug = _project_slug(prop.project, config)
    project = config.project_by_slug.get(project_slug or "")
    if not project:
        raise ValueError("Không nhận diện được project trong config.")

    features = _model_features(model_payload)
    input_frame = pd.DataFrame([_feature_row(prop, project.slug, features)])
    model = model_payload.get("model")
    if model is None or not hasattr(model, "predict"):
        raise PredictionUnavailableError("Regression model artifact is invalid.")

    predicted_ppm = float(model.predict(input_frame)[0])
    predicted_total = predicted_ppm * prop.area_m2
    metrics = dict(model_payload.get("metrics") or {})
    interval_ppm = _prediction_interval_ppm(predicted_ppm, metrics)
    p10_ppm, p90_ppm = interval_ppm
    p10_total = p10_ppm * prop.area_m2
    p90_total = p90_ppm * prop.area_m2

    candidates = _prediction_scope(clean_frame, project.slug, prop)
    comparable_listings = _comparable_listings(candidates, prop)
    sample_size = int(len(candidates)) if not candidates.empty else int(model_payload.get("train_rows") or 0)
    confidence = _prediction_confidence(sample_size, metrics)
    freshness = _freshness(clean_frame)
    refs = price_snapshot_references(config, project.slug, prop.purpose, prop.property_type, db_path=db_path)

    return ValuationResponse(
        purpose=prop.purpose,
        project=project.name,
        property_type=prop.property_type,
        estimate_basis="regression_prediction_from_combined_clean_market_data",
        p10_total_vnd=float(round(p10_total)),
        p50_total_vnd=float(round(predicted_total)),
        p90_total_vnd=float(round(p90_total)),
        p10_price_per_m2_vnd=float(round(p10_ppm)),
        p50_price_per_m2_vnd=float(round(predicted_ppm)),
        p90_price_per_m2_vnd=float(round(p90_ppm)),
        sample_size=sample_size,
        confidence=confidence,
        data_freshness=freshness,
        comparable_listings=comparable_listings,
        reference_price_snapshots=refs,
        top_factors=_prediction_top_factors(prop, project.name, metrics, sample_size, bool(refs)),
        caveat=(
            "Ước tính theo mô hình regression từ dữ liệu đã làm sạch; đây là mức tham khảo thị trường, "
            "giá thực tế còn phụ thuộc vào tình trạng căn và quá trình thương lượng."
        ),
        prediction_method="gradient_boosting_regression",
        predicted_price_total_vnd=float(round(predicted_total)),
        predicted_price_per_m2_vnd=float(round(predicted_ppm)),
        model_metrics=_public_metrics(metrics, model_payload),
    )


def _artifact_path(value: str | Path | None, env_name: str, default: Path) -> Path:
    if value:
        return resolve_project_path(str(value))
    env_value = os.getenv(env_name)
    return resolve_project_path(env_value) if env_value else default


@lru_cache(maxsize=4)
def _load_model_payload(path: str) -> dict[str, Any]:
    artifact = Path(path)
    if not artifact.exists():
        raise PredictionUnavailableError(f"Missing regression model artifact: {artifact}")
    payload = joblib.load(artifact)
    if not isinstance(payload, dict):
        raise PredictionUnavailableError("Regression model artifact is not a payload dictionary.")
    return payload


@lru_cache(maxsize=4)
def _load_clean_frame(path: str) -> pd.DataFrame:
    artifact = Path(path)
    if not artifact.exists():
        return pd.DataFrame()
    frame = pd.read_csv(artifact, encoding="utf-8-sig")
    if "model_training_eligible" in frame:
        frame = frame[frame["model_training_eligible"].astype(str).str.lower().isin({"true", "1"})]
    if "purpose" in frame:
        frame = frame[frame["purpose"] == "sale"]
    return frame.copy()


def _model_features(model_payload: dict[str, Any]) -> list[str]:
    features = model_payload.get("features")
    if isinstance(features, list) and features:
        return [str(item) for item in features]
    return [
        "project_slug",
        "property_type",
        "area_m2",
        "bedrooms",
        "bathrooms",
        "floor_number",
        "total_floors",
        "subdivision",
        "tower",
        "view",
        "furniture",
    ]


def _feature_row(prop: PropertyInput, project_slug: str, features: list[str]) -> dict[str, Any]:
    values = {
        "project_slug": project_slug,
        "property_type": prop.property_type or "apartment",
        "area_m2": prop.area_m2,
        "bedrooms": prop.bedrooms,
        "bathrooms": prop.bathrooms,
        "floor_number": prop.floor_number,
        "total_floors": None,
        "subdivision": prop.subdivision or "unknown",
        "tower": prop.tower or "unknown",
        "view": prop.view or "unknown",
        "furniture": prop.furniture or "unknown",
    }
    return {feature: values.get(feature) for feature in features}


def _project_slug(value: str, config: AppConfig) -> str | None:
    return infer_project_slug(config, value, default=value)


def _prediction_interval_ppm(predicted_ppm: float, metrics: dict[str, Any]) -> tuple[float, float]:
    mape = _float_optional(metrics.get("mape"))
    mae = _float_optional(metrics.get("mae_price_per_m2_vnd"))
    relative_margin = predicted_ppm * min(max(mape or 0.12, 0.08), 0.28)
    absolute_margin = (mae or 0) * 1.15
    margin = max(relative_margin, absolute_margin)
    return max(predicted_ppm - margin, predicted_ppm * 0.55), predicted_ppm + margin


def _prediction_scope(frame: pd.DataFrame, project_slug: str, prop: PropertyInput) -> pd.DataFrame:
    if frame.empty:
        return frame
    df = frame[frame["project_slug"] == project_slug].copy()
    if df.empty:
        df = frame.copy()
    exact_type = df[df["property_type"] == prop.property_type]
    if not exact_type.empty:
        df = exact_type
    if prop.bedrooms is not None and "bedrooms" in df:
        exact_bedrooms = df[pd.to_numeric(df["bedrooms"], errors="coerce") == prop.bedrooms]
        if not exact_bedrooms.empty:
            df = exact_bedrooms
    return df


def _comparable_listings(frame: pd.DataFrame, prop: PropertyInput, limit: int = 8) -> list[ComparableListing]:
    if frame.empty:
        return []
    df = frame.copy()
    df["similarity_score"] = df.apply(lambda row: _similarity_score(row, prop), axis=1)
    if "observed_at" in df:
        df["observed_dt"] = pd.to_datetime(df["observed_at"], errors="coerce", utc=True)
        df = df.sort_values(["similarity_score", "observed_dt"], ascending=[False, False])
    else:
        df = df.sort_values("similarity_score", ascending=False)
    return [_to_comparable(row) for _, row in df.head(limit).iterrows()]


def _similarity_score(row: pd.Series, prop: PropertyInput) -> float:
    score = 1.0
    area = _float_optional(row.get("area_m2"))
    if area:
        score -= min(abs(area - prop.area_m2) / max(prop.area_m2, 1), 0.7) * 0.5
    bedrooms = _int_optional(row.get("bedrooms"))
    if prop.bedrooms is not None and bedrooms is not None:
        score -= min(abs(bedrooms - prop.bedrooms), 3) * 0.09
    if _same_text(row.get("subdivision"), prop.subdivision):
        score += 0.07
    if _same_text(row.get("tower"), prop.tower):
        score += 0.08
    if _same_text(row.get("view"), prop.view):
        score += 0.04
    if _same_text(row.get("furniture"), prop.furniture):
        score += 0.04
    return float(max(0.05, min(score, 1.15)))


def _to_comparable(row: pd.Series) -> ComparableListing:
    return ComparableListing(
        title=_clean_optional(row.get("title")),
        address=_clean_optional(row.get("address")),
        project=_clean_optional(row.get("project_name")) or _clean_optional(row.get("project_slug")) or "",
        property_type=_clean_optional(row.get("property_type")) or "",
        purpose=_clean_optional(row.get("purpose")) or "sale",
        price_total_vnd=_float_optional(row.get("price_total_vnd")),
        price_per_m2_vnd=_float_optional(row.get("price_per_m2_vnd")),
        rent_monthly_vnd=_float_optional(row.get("rent_monthly_vnd")),
        area_m2=_float_optional(row.get("area_m2")),
        bedrooms=_int_optional(row.get("bedrooms")),
        subdivision=_clean_optional(row.get("subdivision")),
        tower=_clean_optional(row.get("tower")),
        view=_clean_optional(row.get("view")),
        furniture=_clean_optional(row.get("furniture")),
        observed_at=_clean_optional(row.get("observed_at")),
        source_url=_clean_optional(row.get("source_url")),
        similarity_score=round(float(row.get("similarity_score", 0)), 3),
    )


def _prediction_confidence(sample_size: int, metrics: dict[str, Any]) -> str:
    r2 = _float_optional(metrics.get("r2")) or 0
    mape = _float_optional(metrics.get("mape")) or 1
    if sample_size >= 50 and r2 >= 0.65 and mape <= 0.14:
        return "high"
    if sample_size >= 15 and r2 >= 0.45 and mape <= 0.22:
        return "medium"
    return "low"


def _prediction_top_factors(
    prop: PropertyInput,
    project_name: str,
    metrics: dict[str, Any],
    sample_size: int,
    has_refs: bool,
) -> list[str]:
    factors = [
        f"Dự án {project_name}, loại hình {prop.property_type} và diện tích {prop.area_m2:g}m2 là các biến chính trong dự đoán.",
    ]
    if prop.bedrooms is not None:
        factors.append(f"Số phòng ngủ {prop.bedrooms}PN giúp so với nhóm căn cùng công năng.")
    if prop.subdivision or prop.tower:
        factors.append("Phân khu/tòa được dùng để điều chỉnh so với mặt bằng chung nếu có dữ liệu tương ứng.")
    if prop.view:
        factors.append(f"View {prop.view} có thể ảnh hưởng tới thanh khoản và biên thương lượng.")
    if prop.furniture:
        factors.append(f"Nội thất {prop.furniture} là yếu tố hỗ trợ điều chỉnh giá.")
    mape = _float_optional(metrics.get("mape"))
    if mape:
        factors.append(f"Sai số kiểm định trung bình khoảng {mape * 100:.1f}%, nên khoảng giá đã được mở rộng quanh dự đoán.")
    if sample_size < 15:
        factors.append("Dữ liệu cùng phân khúc còn mỏng, nên nên kiểm tra thêm căn so sánh trước khi chốt giá.")
    if has_refs:
        factors.append("Có thêm bảng giá tham khảo từ nguồn dự án/đại lý để đối chiếu ngoài dự đoán.")
    return factors[:6]


def _public_metrics(metrics: dict[str, Any], model_payload: dict[str, Any]) -> dict[str, Any]:
    keys = ("target", "mae_price_per_m2_vnd", "mape", "r2", "test_rows")
    return {
        "train_rows": int(model_payload.get("train_rows") or 0),
        **{key: metrics[key] for key in keys if key in metrics},
    }


def _freshness(frame: pd.DataFrame) -> str | None:
    if frame.empty or "observed_at" not in frame:
        return None
    values = pd.to_datetime(frame["observed_at"], errors="coerce", utc=True)
    if values.notna().any():
        return values.max().isoformat()
    return None


def _same_text(left: Any, right: Any) -> bool:
    if not left or not right:
        return False
    return str(left).strip().casefold() == str(right).strip().casefold()


def _float_optional(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _int_optional(value: Any) -> int | None:
    number = _float_optional(value)
    return int(round(number)) if number is not None else None


def _clean_optional(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    return text if text and text.lower() not in {"nan", "none", "<na>", "unknown"} else None
