from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import load_config  # noqa: E402
from src.crawler import crawl_once  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Crawl listing snapshots into the configured storage backend and CSV exports.")
    parser.add_argument("--config", default="config/projects.yaml")
    parser.add_argument("--db", default="data/market.sqlite")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--source", default=None, help="Optional source filter, e.g. onehousing or batdongsan.")
    args = parser.parse_args()

    cfg = load_config(args.config)
    report = crawl_once(cfg, args.db, args.limit, args.source)
    print(report)


if __name__ == "__main__":
    main()
