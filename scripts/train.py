from __future__ import annotations

import argparse
from pathlib import Path
import sys

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_percentage_error
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.valuation import load_market_frame  # noqa: E402


FEATURES = [
    "project_slug",
    "property_type",
    "area_m2",
    "bedrooms",
    "floor_number",
    "subdivision",
    "view",
    "furniture",
]
CATEGORICAL = ["project_slug", "property_type", "subdivision", "view", "furniture"]
NUMERIC = ["area_m2", "bedrooms", "floor_number"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Train sklearn quantile models from crawled listings.")
    parser.add_argument("--db", default="data/market.sqlite")
    parser.add_argument("--out", default="models/valuation_models.joblib")
    parser.add_argument("--purpose", choices=["sale", "rent"], default="sale")
    args = parser.parse_args()

    frame = load_market_frame(args.db)
    if frame.empty:
        raise SystemExit("No market data. Run scripts/crawl.py first.")
    target_col = "price_per_m2_vnd" if args.purpose == "sale" else "rent_monthly_vnd"
    df = frame[(frame["purpose"] == args.purpose) & pd.notna(frame[target_col]) & pd.notna(frame["area_m2"])].copy()
    df = df[df["quality_flags"].apply(lambda flags: not any("outlier" in flag or "missing" in flag for flag in flags))]
    if len(df) < 30:
        raise SystemExit(f"Need at least 30 clean rows, got {len(df)}.")

    for column in CATEGORICAL:
        df[column] = df[column].fillna("unknown").astype(str)
    for column in NUMERIC:
        median = df[column].median()
        fill_value = 0 if pd.isna(median) else median
        df[column] = df[column].fillna(fill_value)

    x_train, x_test, y_train, y_test = train_test_split(df[FEATURES], df[target_col], test_size=0.2, random_state=42)
    preprocessor = ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
            ("num", "passthrough", NUMERIC),
        ]
    )
    models = {}
    metrics = {}
    for alpha in (0.1, 0.5, 0.9):
        model = Pipeline(
            steps=[
                ("prep", preprocessor),
                (
                    "regressor",
                    GradientBoostingRegressor(loss="quantile", alpha=alpha, random_state=42, n_estimators=180),
                ),
            ]
        )
        model.fit(x_train, y_train)
        pred = model.predict(x_test)
        models[f"q{int(alpha * 100)}"] = model
        metrics[f"q{int(alpha * 100)}_mape"] = float(mean_absolute_percentage_error(y_test, pred))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"purpose": args.purpose, "target": target_col, "features": FEATURES, "models": models, "metrics": metrics}, out_path)
    print({"rows": len(df), "out": str(out_path), "metrics": metrics})


if __name__ == "__main__":
    main()
