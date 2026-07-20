from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import AppConfig, load_config  # noqa: E402
from src.crawler import crawl_once  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Near-realtime crawl scheduler with per-source intervals.")
    parser.add_argument("--config", default="config/projects.yaml")
    parser.add_argument("--db", default="data/market.sqlite")
    parser.add_argument("--source", default=None, help="Run only one source. Overrides realtime.jobs.")
    parser.add_argument("--interval-minutes", type=float, default=None, help="Interval for --source mode.")
    parser.add_argument("--limit", type=int, default=None, help="Limit pages per run for --source mode.")
    parser.add_argument("--once", action="store_true", help="Run due jobs once and exit.")
    parser.add_argument("--run-for-minutes", type=float, default=None, help="Stop after this many minutes.")
    parser.add_argument("--reuse-cache", action="store_true", help="Use cached raw_fetch instead of fetching fresh pages.")
    parser.add_argument("--poll-seconds", type=float, default=10)
    args = parser.parse_args()

    cfg = _runtime_config(load_config(args.config), reuse_cache=args.reuse_cache)
    jobs = _jobs_from_args_or_config(cfg, args)
    next_run = {job["source"]: datetime.now(timezone.utc) for job in jobs}
    stop_at = datetime.now(timezone.utc) + timedelta(minutes=args.run_for_minutes) if args.run_for_minutes else None

    while True:
        now = datetime.now(timezone.utc)
        ran_any = False
        for job in jobs:
            source = job["source"]
            if now < next_run[source]:
                continue
            ran_any = True
            report = _run_job(cfg, args.db, job)
            print(json.dumps(report, ensure_ascii=False), flush=True)
            next_run[source] = datetime.now(timezone.utc) + timedelta(minutes=float(job["interval_minutes"]))
        if args.once:
            break
        if stop_at and datetime.now(timezone.utc) >= stop_at:
            break
        if not ran_any:
            time.sleep(max(args.poll_seconds, 1))


def _runtime_config(config: AppConfig, reuse_cache: bool) -> AppConfig:
    raw = deepcopy(config.raw)
    raw.setdefault("crawl", {})["reuse_existing_fetch"] = reuse_cache
    return AppConfig(raw=raw, projects=config.projects)


def _jobs_from_args_or_config(config: AppConfig, args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.source:
        return [
            {
                "source": args.source,
                "interval_minutes": args.interval_minutes or 30,
                "limit": args.limit,
            }
        ]
    jobs = config.raw.get("realtime", {}).get("jobs") or []
    if not jobs:
        return [{"source": None, "interval_minutes": args.interval_minutes or 30, "limit": args.limit}]
    normalized = []
    for job in jobs:
        normalized.append(
            {
                "source": job.get("source"),
                "interval_minutes": float(job.get("interval_minutes", args.interval_minutes or 30)),
                "limit": args.limit if args.limit is not None else job.get("limit"),
            }
        )
    return normalized


def _run_job(config: AppConfig, db_path: str, job: dict[str, Any]) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc)
    try:
        report = crawl_once(config, db_path, limit=job.get("limit"), source_filter=job.get("source"))
        status = "ok"
        error = None
    except Exception as exc:  # noqa: BLE001
        report = {}
        status = "error"
        error = f"{type(exc).__name__}: {exc}"
    return {
        "status": status,
        "source": job.get("source"),
        "limit": job.get("limit"),
        "interval_minutes": job.get("interval_minutes"),
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "records_parsed": report.get("records_parsed", 0),
        "price_snapshots_parsed": report.get("price_snapshots_parsed", 0),
        "property_candidates_parsed": report.get("property_candidates_parsed", 0),
        "pages": len(report.get("pages", [])),
        "output_csv": report.get("output_csv"),
        "error": error,
    }


if __name__ == "__main__":
    main()
