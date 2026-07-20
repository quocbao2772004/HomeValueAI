from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import load_config  # noqa: E402
from src.crawler import export_listings_csv, export_price_snapshots_csv, export_property_candidates_csv  # noqa: E402
from src.parser import parse_listing_markdown, parse_price_snapshots, parse_property_candidates  # noqa: E402
from src.storage import get_store  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild listing_observation from saved raw_fetch snapshots.")
    parser.add_argument("--config", default="config/projects.yaml")
    parser.add_argument("--db", default="data/market.sqlite")
    args = parser.parse_args()
    cfg = load_config(args.config)

    store = get_store(args.db)
    store.init()
    rows = store.raw_fetch_rows()
    store.delete_parsed_collections()
    total = 0
    snapshot_total = 0
    candidate_total = 0
    for row in rows:
        path = ROOT / str(row["content_path"])
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8")
        meta = {
            "url": row["url"],
            "project_slug": row["project_slug"],
            "purpose": row["purpose"],
            "property_type": row["property_type"],
        }
        records = parse_listing_markdown(
            content,
            cfg,
            meta,
        )
        snapshots = parse_price_snapshots(content, cfg, meta)
        candidates = parse_property_candidates(content, cfg, meta)
        inserted, _ = store.upsert_listings(records)
        snapshot_inserted, _ = store.upsert_price_snapshots(snapshots)
        candidate_inserted, _ = store.upsert_property_candidates(candidates)
        total += inserted
        snapshot_total += snapshot_inserted
        candidate_total += candidate_inserted
    export_listings_csv(args.db)
    export_price_snapshots_csv(args.db)
    export_property_candidates_csv(args.db)
    print(
        {
            "rebuilt_records": total,
            "rebuilt_price_snapshots": snapshot_total,
            "rebuilt_property_candidates": candidate_total,
            "csv": "data/processed/listings.csv",
            "price_snapshots_csv": "data/processed/price_snapshots.csv",
            "property_candidates_csv": "data/processed/property_candidates.csv",
        }
    )


if __name__ == "__main__":
    main()
