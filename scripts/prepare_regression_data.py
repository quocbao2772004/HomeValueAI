from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import TransformedTargetRegressor
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.dedupe import canonical_listing_key  # noqa: E402
from src.normalization import (  # noqa: E402
    infer_property_type,
    normalize_furniture,
    normalize_view,
    parse_bedrooms,
    parse_subdivision,
    parse_tower_code,
)
from src.text import text_key  # noqa: E402

COMMON_COLUMNS = [
    "source",
    "source_url",
    "external_id",
    "observed_at",
    "title",
    "address",
    "project_slug",
    "project_name",
    "property_type",
    "purpose",
    "price_total_vnd",
    "price_per_m2_vnd",
    "rent_monthly_vnd",
    "area_m2",
    "bedrooms",
    "bathrooms",
    "floor_number",
    "total_floors",
    "subdivision",
    "tower",
    "view",
    "furniture",
    "legal_status",
    "is_verified",
    "quality_flags_json",
    "dedupe_key",
    "basis",
    "source_file",
]

NUMERIC_COLUMNS = [
    "price_total_vnd",
    "price_per_m2_vnd",
    "rent_monthly_vnd",
    "area_m2",
    "bedrooms",
    "bathrooms",
    "floor_number",
    "total_floors",
    "is_verified",
]

MODEL_FEATURES = [
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
CATEGORICAL_FEATURES = ["project_slug", "property_type", "subdivision", "tower", "view", "furniture"]
NUMERIC_FEATURES = ["area_m2", "bedrooms", "bathrooms", "floor_number", "total_floors"]

SALE_PPM_MIN = 15_000_000
SALE_PPM_MAX = 450_000_000
RENT_MIN = 1_000_000
RENT_MAX = 300_000_000
MODEL_ALLOWED_BASES = {"listing", "market_listing", "hanoi_listing"}

SOURCE_PRIORITY = {
    "onehousing": 1,
    "market_vinhomes": 2,
    "vinhomesonline": 3,
    "homedy": 4,
    "batdongsan": 5,
    "vinhomesland": 6,
    "bdsvinhomes": 7,
    "vinhomesreal": 8,
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Combine, clean, dedupe Vinhomes CSV data, then train a sale price regression model."
    )
    parser.add_argument("--processed-dir", default="data/processed")
    parser.add_argument("--crawl-dir", default="crawl_data")
    parser.add_argument("--out-data", default="data/processed/combined_clean_listings.csv")
    parser.add_argument("--out-references", default="data/processed/combined_clean_references.csv")
    parser.add_argument("--out-predictions", default="data/processed/house_price_predictions.csv")
    parser.add_argument("--out-summary", default="data/processed/house_price_prediction_summary.csv")
    parser.add_argument("--out-report", default="data/processed/combined_clean_report.json")
    parser.add_argument("--out-model", default="models/combined_sale_regression_model.joblib")
    args = parser.parse_args()

    processed_dir = Path(args.processed_dir)
    crawl_dir = Path(args.crawl_dir)

    input_counts: dict[str, int] = {}
    listing_frames = [
        _processed_listings(processed_dir / "listings.csv", input_counts),
        _property_candidates(processed_dir / "property_candidates.csv", input_counts),
        _market_vinhomes(crawl_dir / "market_vinhomes.csv", input_counts),
        _hanoi_source_listings(crawl_dir / "vinhomes_hanoi_sources.csv", input_counts),
    ]
    available_listing_frames = [frame for frame in listing_frames if not frame.empty]
    if available_listing_frames:
        concat_ready = [frame.dropna(axis=1, how="all") for frame in available_listing_frames]
        raw_listings = _align_common(pd.concat(concat_ready, ignore_index=True, sort=False))
    else:
        raw_listings = _empty_common()
    clean_before_dedupe, dropped = _clean_listing_frame(raw_listings)
    clean_listings = _aggregate_duplicate_listings(clean_before_dedupe)

    references = _combined_references(processed_dir, crawl_dir, input_counts)

    model_payload, predictions, summary = _train_and_predict(clean_listings)

    out_data = Path(args.out_data)
    out_references = Path(args.out_references)
    out_predictions = Path(args.out_predictions)
    out_summary = Path(args.out_summary)
    out_report = Path(args.out_report)
    out_model = Path(args.out_model)
    for path in [out_data, out_references, out_predictions, out_summary, out_report, out_model]:
        path.parent.mkdir(parents=True, exist_ok=True)

    clean_listings.to_csv(out_data, index=False, encoding="utf-8-sig")
    references.to_csv(out_references, index=False, encoding="utf-8-sig")
    predictions.to_csv(out_predictions, index=False, encoding="utf-8-sig")
    summary.to_csv(out_summary, index=False, encoding="utf-8-sig")
    joblib.dump(model_payload, out_model)

    duplicate_groups = int((clean_before_dedupe.groupby("canonical_key").size() > 1).sum()) if not clean_before_dedupe.empty else 0
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "input_counts": input_counts,
        "raw_listing_rows": int(len(raw_listings)),
        "dropped_rows": dropped,
        "clean_rows_before_dedupe": int(len(clean_before_dedupe)),
        "duplicate_groups_collapsed": duplicate_groups,
        "clean_rows_after_dedupe": int(len(clean_listings)),
        "reference_rows": int(len(references)),
        "sale_training_rows": int(model_payload["train_rows"]),
        "sale_prediction_rows": int(len(predictions)),
        "model_training_scope": "sale rows with project_slug starting vinhomes- and basis in listing/market_listing/hanoi_listing",
        "model_metrics": model_payload["metrics"],
        "outputs": {
            "clean_listings": str(out_data),
            "clean_references": str(out_references),
            "predictions": str(out_predictions),
            "prediction_summary": str(out_summary),
            "model": str(out_model),
        },
    }
    out_report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


def _read_csv(path: Path, input_counts: dict[str, int]) -> pd.DataFrame:
    if not path.exists():
        input_counts[str(path)] = 0
        return pd.DataFrame()
    df = pd.read_csv(path, encoding="utf-8-sig")
    input_counts[str(path)] = int(len(df))
    return df


def _processed_listings(path: Path, input_counts: dict[str, int]) -> pd.DataFrame:
    df = _read_csv(path, input_counts)
    if df.empty:
        return _empty_common()
    df = df.copy()
    df["basis"] = "listing"
    df["source_file"] = str(path)
    return _align_common(df)


def _property_candidates(path: Path, input_counts: dict[str, int]) -> pd.DataFrame:
    df = _read_csv(path, input_counts)
    if df.empty:
        return _empty_common()
    df = df.rename(columns={"mapped_project_slug": "project_slug", "raw_project_name": "project_name"}).copy()
    df["basis"] = "property_candidate"
    df["source_file"] = str(path)
    return _align_common(df)


def _market_vinhomes(path: Path, input_counts: dict[str, int]) -> pd.DataFrame:
    df = _read_csv(path, input_counts)
    if df.empty:
        return _empty_common()
    df = df.copy()
    df["basis"] = "market_listing"
    df["source_file"] = str(path)
    df["dedupe_key"] = df.apply(lambda row: f"{row.get('source', 'market_vinhomes')}:{row.get('source_url', '')}", axis=1)
    return _align_common(df)


def _hanoi_source_listings(path: Path, input_counts: dict[str, int]) -> pd.DataFrame:
    df = _read_csv(path, input_counts)
    if df.empty:
        return _empty_common()
    df = df[df.get("record_type").fillna("") == "listing"].copy()
    if df.empty:
        return _empty_common()
    df["price_total_vnd"] = _mean_pair(df.get("price_min_vnd"), df.get("price_max_vnd"))
    df["area_m2"] = _mean_pair(df.get("area_min_m2"), df.get("area_max_m2"))
    df["basis"] = "hanoi_listing"
    df["source_file"] = str(path)
    df["dedupe_key"] = df.apply(lambda row: f"{row.get('source', 'hanoi')}:{row.get('source_url', '')}", axis=1)
    return _align_common(df)


def _combined_references(processed_dir: Path, crawl_dir: Path, input_counts: dict[str, int]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []

    snapshots = _read_csv(processed_dir / "price_snapshots.csv", input_counts)
    if not snapshots.empty:
        snapshots = snapshots.copy()
        snapshots["record_type"] = "price_snapshot"
        snapshots["reference_label"] = snapshots.get("label")
        snapshots["mid_area_m2"] = _mean_pair(snapshots.get("area_min_m2"), snapshots.get("area_max_m2"))
        snapshots["mid_price_total_vnd"] = _mean_pair(snapshots.get("price_min_vnd"), snapshots.get("price_max_vnd"))
        snapshots["mid_price_per_m2_vnd"] = _mean_pair(
            snapshots.get("price_per_m2_min_vnd"), snapshots.get("price_per_m2_max_vnd")
        )
        frames.append(snapshots)

    hanoi = _read_csv(crawl_dir / "vinhomes_hanoi_sources.csv", input_counts)
    if not hanoi.empty:
        hanoi = hanoi[hanoi.get("record_type").fillna("") == "project_reference"].copy()
        if not hanoi.empty:
            hanoi["basis"] = "project_reference"
            hanoi["reference_label"] = hanoi.get("title")
            hanoi["mid_area_m2"] = _mean_pair(hanoi.get("area_min_m2"), hanoi.get("area_max_m2"))
            hanoi["mid_price_total_vnd"] = _mean_pair(hanoi.get("price_min_vnd"), hanoi.get("price_max_vnd"))
            hanoi["mid_price_per_m2_vnd"] = pd.to_numeric(hanoi.get("price_per_m2_vnd"), errors="coerce")
            frames.append(hanoi)

    if not frames:
        return pd.DataFrame()
    refs = pd.concat(frames, ignore_index=True, sort=False)
    refs["mid_price_per_m2_vnd"] = refs["mid_price_per_m2_vnd"].where(
        refs["mid_price_per_m2_vnd"].notna(),
        refs["mid_price_total_vnd"] / refs["mid_area_m2"],
    )
    refs = _normalize_strings(refs)
    for column in [
        "price_min_vnd",
        "price_max_vnd",
        "price_per_m2_min_vnd",
        "price_per_m2_max_vnd",
        "area_min_m2",
        "area_max_m2",
        "mid_area_m2",
        "mid_price_total_vnd",
        "mid_price_per_m2_vnd",
    ]:
        if column in refs:
            refs[column] = pd.to_numeric(refs[column], errors="coerce")
    refs["reference_key"] = refs.apply(
        lambda row: "|".join(
            [
                _clean_value(row.get("project_slug")),
                _clean_value(row.get("purpose")),
                _clean_value(row.get("property_type")),
                _clean_value(row.get("source")),
                _clean_value(row.get("source_url")),
                _clean_value(row.get("reference_label")),
                _clean_value(row.get("subdivision")),
                _clean_value(row.get("basis")),
            ]
        ),
        axis=1,
    )
    return _aggregate_duplicate_references(refs)


def _align_common(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for column in COMMON_COLUMNS:
        if column not in df:
            df[column] = pd.NA
    return df[COMMON_COLUMNS].copy()


def _empty_common() -> pd.DataFrame:
    return pd.DataFrame(columns=COMMON_COLUMNS)


def _clean_listing_frame(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    if df.empty:
        return _empty_common(), {"missing_or_invalid": 0, "outlier": 0}

    cleaned = df.copy()
    cleaned = _normalize_strings(cleaned)
    for column in NUMERIC_COLUMNS:
        cleaned[column] = pd.to_numeric(cleaned[column], errors="coerce")

    cleaned["purpose"] = cleaned["purpose"].fillna("sale").replace("", "sale")
    cleaned["property_type"] = cleaned.apply(_clean_property_type, axis=1)
    cleaned["project_name"] = cleaned["project_name"].where(cleaned["project_name"].notna(), cleaned["project_slug"])
    cleaned["project_slug"] = cleaned.apply(_clean_project_slug, axis=1)
    cleaned["bedrooms"] = cleaned["bedrooms"].where(
        cleaned["bedrooms"].notna(), cleaned["title"].apply(lambda value: parse_bedrooms(value))
    )
    cleaned["subdivision"] = cleaned.apply(_clean_subdivision_value, axis=1)
    cleaned["tower"] = cleaned.apply(_clean_tower_value, axis=1)
    cleaned["view"] = cleaned.apply(
        lambda row: row["view"] if _has_value(row.get("view")) else normalize_view(row.get("title"), row.get("address")),
        axis=1,
    )
    cleaned["furniture"] = cleaned.apply(
        lambda row: row["furniture"]
        if _has_value(row.get("furniture"))
        else normalize_furniture(row.get("title"), row.get("address")),
        axis=1,
    )

    cleaned["price_per_m2_vnd"] = cleaned["price_per_m2_vnd"].where(
        cleaned["price_per_m2_vnd"].notna(),
        cleaned["price_total_vnd"] / cleaned["area_m2"],
    )
    cleaned["price_total_vnd"] = cleaned["price_total_vnd"].where(
        cleaned["price_total_vnd"].notna(),
        cleaned["price_per_m2_vnd"] * cleaned["area_m2"],
    )
    cleaned["is_verified"] = cleaned["is_verified"].fillna(0)
    cleaned["dedupe_key"] = cleaned.apply(_ensure_dedupe_key, axis=1)

    cleaned["quality_flags"] = cleaned["quality_flags_json"].apply(_loads_flags)
    cleaned["quality_flags"] = cleaned.apply(_with_computed_flags, axis=1)
    cleaned["quality_flags_json"] = cleaned["quality_flags"].apply(lambda flags: json.dumps(flags, ensure_ascii=False))
    cleaned["canonical_key"] = cleaned.apply(_canonical_key, axis=1)

    bad_mask = cleaned["quality_flags"].apply(_has_blocking_quality_flag)
    missing_or_invalid = cleaned["quality_flags"].apply(
        lambda flags: any(flag.startswith("missing_") or flag.startswith("invalid_") for flag in flags)
    )
    outlier = cleaned["quality_flags"].apply(lambda flags: any("outlier" in flag for flag in flags))
    cleaned = cleaned[~bad_mask].copy()
    cleaned = cleaned[cleaned["canonical_key"].fillna("").astype(str).str.len() > 0].copy()
    cleaned = cleaned.sort_values(["canonical_key", "observed_at"], ascending=[True, False], kind="mergesort")
    dropped = {
        "missing_or_invalid": int(missing_or_invalid.sum()),
        "outlier": int(outlier.sum()),
        "total": int(bad_mask.sum()),
    }
    return cleaned, dropped


def _aggregate_duplicate_listings(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    rows: list[dict[str, Any]] = []
    ordered = df.copy()
    ordered["_source_priority"] = ordered["source"].map(SOURCE_PRIORITY).fillna(99)
    ordered["_observed_dt"] = pd.to_datetime(ordered["observed_at"], errors="coerce", utc=True)
    ordered = ordered.sort_values(["canonical_key", "_source_priority", "_observed_dt"], ascending=[True, True, False])

    for canonical_key, group in ordered.groupby("canonical_key", sort=False):
        group = group.copy()
        representative = group.iloc[0].to_dict()
        output: dict[str, Any] = {
            column: _first_non_empty(group[column]) if column in group else pd.NA
            for column in COMMON_COLUMNS
            if column not in NUMERIC_COLUMNS
        }
        for column in NUMERIC_COLUMNS:
            output[column] = float(group[column].mean(skipna=True)) if column in group and group[column].notna().any() else np.nan

        output["canonical_key"] = canonical_key
        output["duplicate_count"] = int(len(group))
        output["duplicate_sources"] = ", ".join(_unique_clean(group.get("source", pd.Series(dtype=str))))
        output["source"] = ", ".join(_unique_clean(group.get("source", pd.Series(dtype=str)))) or representative.get("source")
        output["basis"] = ", ".join(_unique_clean(group.get("basis", pd.Series(dtype=str)))) or representative.get("basis")
        output["source_file"] = ", ".join(_unique_clean(group.get("source_file", pd.Series(dtype=str))))
        output["observed_at"] = _max_datetime_text(group.get("observed_at", pd.Series(dtype=str)))
        output["quality_flags"] = sorted({flag for flags in group["quality_flags"] for flag in flags})
        output["quality_flags_json"] = json.dumps(output["quality_flags"], ensure_ascii=False)
        rows.append(output)

    result = pd.DataFrame(rows)
    result["price_per_m2_vnd"] = result["price_per_m2_vnd"].where(
        result["price_per_m2_vnd"].notna(),
        result["price_total_vnd"] / result["area_m2"],
    )
    result["price_total_vnd"] = result["price_total_vnd"].where(
        result["price_total_vnd"].notna(),
        result["price_per_m2_vnd"] * result["area_m2"],
    )
    result["model_training_eligible"] = result.apply(_is_model_training_eligible, axis=1)
    result = result.drop(columns=["quality_flags"], errors="ignore")
    stable_columns = [
        *COMMON_COLUMNS,
        "canonical_key",
        "duplicate_count",
        "duplicate_sources",
        "model_training_eligible",
    ]
    return result[[column for column in stable_columns if column in result]].copy()


def _aggregate_duplicate_references(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    rows: list[dict[str, Any]] = []
    numeric = [
        column
        for column in [
            "price_min_vnd",
            "price_max_vnd",
            "price_per_m2_min_vnd",
            "price_per_m2_max_vnd",
            "area_min_m2",
            "area_max_m2",
            "mid_area_m2",
            "mid_price_total_vnd",
            "mid_price_per_m2_vnd",
        ]
        if column in df
    ]
    for reference_key, group in df.groupby("reference_key", sort=False):
        output = {column: _first_non_empty(group[column]) for column in group.columns if column not in numeric}
        for column in numeric:
            output[column] = float(group[column].mean(skipna=True)) if group[column].notna().any() else np.nan
        output["reference_key"] = reference_key
        output["duplicate_count"] = int(len(group))
        rows.append(output)
    return pd.DataFrame(rows)


def _train_and_predict(clean_listings: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    sale = clean_listings[
        clean_listings["model_training_eligible"].astype(bool)
        & (clean_listings["purpose"] == "sale")
        & clean_listings["price_per_m2_vnd"].notna()
        & clean_listings["area_m2"].notna()
        & (clean_listings["area_m2"] > 0)
    ].copy()
    if len(sale) < 30:
        raise SystemExit(f"Need at least 30 clean sale rows to train regression model, got {len(sale)}.")

    for column in CATEGORICAL_FEATURES:
        sale[column] = sale[column].fillna("unknown").replace("", "unknown").astype(str)
    for column in NUMERIC_FEATURES:
        sale[column] = pd.to_numeric(sale[column], errors="coerce")

    x_train, x_test, y_train, y_test = train_test_split(
        sale[MODEL_FEATURES],
        sale["price_per_m2_vnd"].astype(float),
        test_size=0.2,
        random_state=42,
    )
    regressor = Pipeline(
        steps=[
            (
                "prep",
                _column_transformer(),
            ),
            (
                "regressor",
                GradientBoostingRegressor(
                    random_state=42,
                    n_estimators=260,
                    learning_rate=0.045,
                    max_depth=3,
                    min_samples_leaf=5,
                ),
            ),
        ]
    )
    model = TransformedTargetRegressor(regressor=regressor, func=np.log1p, inverse_func=np.expm1)
    model.fit(x_train, y_train)
    test_pred = model.predict(x_test)
    metrics = {
        "target": "price_per_m2_vnd",
        "mae_price_per_m2_vnd": float(mean_absolute_error(y_test, test_pred)),
        "mape": float(mean_absolute_percentage_error(y_test, test_pred)),
        "r2": float(r2_score(y_test, test_pred)),
        "test_rows": int(len(x_test)),
    }

    predictions = sale.copy()
    predictions["predicted_price_per_m2_vnd"] = model.predict(predictions[MODEL_FEATURES])
    predictions["predicted_price_total_vnd"] = predictions["predicted_price_per_m2_vnd"] * predictions["area_m2"]
    predictions["actual_price_total_vnd"] = predictions["price_total_vnd"]
    predictions["prediction_error_pct"] = (
        (predictions["predicted_price_total_vnd"] - predictions["actual_price_total_vnd"])
        / predictions["actual_price_total_vnd"]
    )

    prediction_columns = [
        "project_slug",
        "project_name",
        "property_type",
        "purpose",
        "area_m2",
        "bedrooms",
        "bathrooms",
        "floor_number",
        "subdivision",
        "tower",
        "view",
        "furniture",
        "actual_price_total_vnd",
        "price_per_m2_vnd",
        "predicted_price_total_vnd",
        "predicted_price_per_m2_vnd",
        "prediction_error_pct",
        "duplicate_count",
        "source",
        "basis",
        "title",
        "source_url",
        "canonical_key",
        "model_training_eligible",
    ]
    predictions = predictions[[column for column in prediction_columns if column in predictions]].copy()

    summary = _prediction_summary(predictions)
    payload = {
        "created_at": datetime.now(UTC).isoformat(),
        "purpose": "sale",
        "features": MODEL_FEATURES,
        "categorical_features": CATEGORICAL_FEATURES,
        "numeric_features": NUMERIC_FEATURES,
        "target": "price_per_m2_vnd",
        "train_rows": int(len(sale)),
        "metrics": metrics,
        "model": model,
    }
    return payload, predictions, summary


def _column_transformer():
    from sklearn.compose import ColumnTransformer

    categorical = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="constant", fill_value="unknown")),
            ("onehot", OneHotEncoder(handle_unknown="ignore")),
        ]
    )
    numeric = Pipeline(steps=[("imputer", SimpleImputer(strategy="median"))])
    return ColumnTransformer(
        transformers=[
            ("cat", categorical, CATEGORICAL_FEATURES),
            ("num", numeric, NUMERIC_FEATURES),
        ]
    )


def _prediction_summary(predictions: pd.DataFrame) -> pd.DataFrame:
    if predictions.empty:
        return pd.DataFrame()
    df = predictions.copy()
    df["bedrooms_segment"] = df["bedrooms"].apply(_bedroom_segment)
    grouped = (
        df.groupby(["project_slug", "project_name", "property_type", "bedrooms_segment"], dropna=False)
        .agg(
            rows=("predicted_price_total_vnd", "size"),
            median_area_m2=("area_m2", "median"),
            actual_median_total_vnd=("actual_price_total_vnd", "median"),
            predicted_median_total_vnd=("predicted_price_total_vnd", "median"),
            predicted_median_price_per_m2_vnd=("predicted_price_per_m2_vnd", "median"),
            mean_abs_error_pct=("prediction_error_pct", lambda values: float(np.nanmean(np.abs(values)))),
        )
        .reset_index()
        .sort_values(["rows", "project_slug", "property_type"], ascending=[False, True, True])
    )
    return grouped


def _clean_property_type(row: pd.Series) -> str:
    current = _clean_value(row.get("property_type"))
    inferred = infer_property_type(row.get("title"), row.get("address"), default=current or "other")
    if not current or current == "other":
        return inferred
    return current


def _clean_project_slug(row: pd.Series) -> str:
    value = _clean_value(row.get("project_slug"))
    if value:
        return value
    project_name = _clean_value(row.get("project_name"))
    if project_name:
        return text_key(project_name).replace(" ", "-")
    title = _clean_value(row.get("title"))
    if title:
        return text_key(title)[:80].replace(" ", "-")
    return "unknown"


def _clean_subdivision_value(row: pd.Series) -> str | None:
    current = _clean_value(row.get("subdivision"))
    parsed = parse_subdivision(current, row.get("title"), row.get("address"))
    return parsed or current or None


def _clean_tower_value(row: pd.Series) -> str | None:
    current = parse_tower_code(row.get("tower"))
    parsed = parse_tower_code(row.get("title"), row.get("address"), row.get("source_url"))
    if parsed and (not current or (_tower_specificity(parsed) > _tower_specificity(current))):
        return parsed
    return current or parsed


def _tower_specificity(value: str | None) -> int:
    if not value:
        return 0
    return 2 if "." in value else 1


def _with_computed_flags(row: pd.Series) -> list[str]:
    flags = set(row.get("quality_flags") or [])
    purpose = _clean_value(row.get("purpose"))
    area = _float_or_nan(row.get("area_m2"))
    if not math.isfinite(area) or area <= 0:
        flags.add("missing_area")
    if purpose == "rent":
        rent = _float_or_nan(row.get("rent_monthly_vnd"))
        if not math.isfinite(rent):
            flags.add("missing_rent_price")
        elif rent < RENT_MIN or rent > RENT_MAX:
            flags.add("rent_outlier")
    else:
        ppm = _float_or_nan(row.get("price_per_m2_vnd"))
        if not math.isfinite(ppm):
            flags.add("missing_sale_price")
        elif ppm < SALE_PPM_MIN or ppm > SALE_PPM_MAX:
            flags.add("sale_price_outlier")
    return sorted(str(flag) for flag in flags if _clean_value(flag))


def _is_model_training_eligible(row: pd.Series) -> bool:
    basis_values = {
        value.strip()
        for value in str(row.get("basis") or "").split(",")
        if value.strip()
    }
    project_slug = _clean_value(row.get("project_slug"))
    return bool(basis_values & MODEL_ALLOWED_BASES) and project_slug.startswith("vinhomes-")


def _has_blocking_quality_flag(flags: list[str]) -> bool:
    return any(
        flag.startswith("missing_")
        or flag.startswith("invalid_")
        or "outlier" in flag
        for flag in flags
    )


def _canonical_key(row: pd.Series) -> str:
    payload = row.to_dict()
    payload["basis"] = "listing"
    return canonical_listing_key(payload)


def _ensure_dedupe_key(row: pd.Series) -> str:
    current = _clean_value(row.get("dedupe_key"))
    if current:
        return current
    source = _clean_value(row.get("source")) or "unknown"
    source_url = _clean_value(row.get("source_url"))
    if source_url:
        return f"{source}:{source_url}"
    return f"{source}:{_canonical_key(row)}"


def _normalize_strings(df: pd.DataFrame) -> pd.DataFrame:
    output = df.copy()
    for column in output.columns:
        if pd.api.types.is_object_dtype(output[column]) or pd.api.types.is_string_dtype(output[column]):
            output[column] = output[column].apply(lambda value: pd.NA if not _has_value(value) else str(value).strip())
    return output


def _mean_pair(left: Any, right: Any) -> pd.Series:
    left_series = pd.to_numeric(left, errors="coerce") if left is not None else pd.Series(dtype=float)
    right_series = pd.to_numeric(right, errors="coerce") if right is not None else pd.Series(dtype=float)
    return pd.concat([left_series, right_series], axis=1).mean(axis=1, skipna=True)


def _loads_flags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if not _has_value(value):
        return []
    try:
        data = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [str(item) for item in data]


def _first_non_empty(series: pd.Series) -> Any:
    for value in series:
        if _has_value(value):
            return value
    return pd.NA


def _unique_clean(series: pd.Series) -> list[str]:
    values = {_clean_value(value) for value in series if _has_value(value)}
    return sorted(value for value in values if value)


def _max_datetime_text(series: pd.Series) -> str | None:
    datetimes = pd.to_datetime(series, errors="coerce", utc=True)
    if datetimes.notna().any():
        return datetimes.max().isoformat()
    return _first_non_empty(series)


def _bedroom_segment(value: Any) -> str:
    number = _float_or_nan(value)
    if not math.isfinite(number):
        return "unknown"
    if abs(number - round(number)) < 0.01:
        return str(int(round(number)))
    return f"{number:.1f}"


def _float_or_nan(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return number if math.isfinite(number) else float("nan")


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, float) and math.isnan(value):
        return False
    text = str(value).strip()
    return bool(text) and text.lower() not in {"nan", "none", "<na>"}


def _clean_value(value: Any) -> str:
    return str(value).strip().lower() if _has_value(value) else ""


if __name__ == "__main__":
    main()
