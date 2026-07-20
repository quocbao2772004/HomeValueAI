from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from src.config import AppConfig, get_nested
from src.database import DEFAULT_DB_PATH
from src.parser import blocked_content, parse_listing_markdown, parse_price_snapshots, parse_property_candidates
from src.storage import export_collection_csv, get_store

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw_html"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"


@dataclass(frozen=True)
class FetchResult:
    url: str
    final_url: str
    fetcher: str
    status_code: int | None
    content: str
    blocked: bool
    error: str | None = None


def iter_page_targets(config: AppConfig, limit: int | None = None, source_filter: str | None = None) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    expand_seed_pagination = bool(get_nested(config, "crawl", "expand_seed_pagination", default=False))
    max_seed_page = int(get_nested(config, "crawl", "pagination_pages_per_seed", default=1))
    for project in config.projects:
        for page in project.pages:
            target = {
                "project_slug": project.slug,
                "project_name": project.name,
                "purpose": page.purpose,
                "property_type": page.property_type,
                "source": _resolve_source(page.source, page.url),
                "pagination": page.pagination,
                "max_pages": page.max_pages,
                "url": page.url,
            }
            if source_filter and target["source"] != source_filter:
                continue
            targets.append(target)
            if expand_seed_pagination:
                targets.extend(_expand_seed_pages(target, int(target.get("max_pages") or max_seed_page)))
    for page in config.raw.get("crawl", {}).get("extra_pages", []):
        target = {
            "project_slug": page.get("project_slug") or "",
            "project_name": page.get("project_name") or "",
            "purpose": page["purpose"],
            "property_type": page["property_type"],
            "source": _resolve_source(page.get("source", "auto"), page["url"]),
            "pagination": page.get("pagination", "auto"),
            "max_pages": page.get("max_pages"),
            "url": page["url"],
        }
        if source_filter and target["source"] != source_filter:
            continue
        targets.append(target)
        if expand_seed_pagination:
            targets.extend(_expand_seed_pages(target, int(target.get("max_pages") or max_seed_page)))
    return targets[:limit] if limit else targets


def _expand_seed_pages(target: dict[str, Any], max_seed_page: int) -> list[dict[str, Any]]:
    if max_seed_page <= 1 or re.search(r"/p\d+$", target["url"].rstrip("/")):
        return []
    expanded = []
    base_url = target["url"].rstrip("/")
    for page_number in range(2, max_seed_page + 1):
        item = dict(target)
        item["url"] = _page_url(base_url, page_number, target.get("pagination", "auto"))
        expanded.append(item)
    return expanded


def _resolve_source(source: str, url: str) -> str:
    if source and source != "auto":
        return source
    host = urlparse(url).netloc.lower()
    if "onehousing.vn" in host:
        return "onehousing"
    if "vinhomesonline.vn" in host:
        return "vinhomesonline"
    if "vinhomesland.vn" in host:
        return "vinhomesland"
    return "batdongsan"


def _page_url(base_url: str, page_number: int, pagination: str) -> str:
    if pagination == "query_page":
        parsed = urlparse(base_url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query["page"] = str(page_number)
        return urlunparse(parsed._replace(query=urlencode(query)))
    return f"{base_url}/p{page_number}"


def fetch_page(target: dict[str, str], config: AppConfig) -> FetchResult:
    url = target["url"]
    crawl = config.raw.get("crawl", {})
    timeout = crawl.get("request_timeout_seconds", 30)
    headers = {
        "User-Agent": crawl.get("user_agent", "Mozilla/5.0"),
        "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
    }
    errors: list[str] = []
    source = target.get("source") or _resolve_source("auto", url)
    direct_sources = {"onehousing", "vinhomesonline", "vinhomesland"}
    direct_first = source in direct_sources or crawl.get("direct_fetch_first", True)

    if direct_first:
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            content = response.text or ""
            if response.status_code < 400 and not blocked_content(content):
                return FetchResult(
                    url=url,
                    final_url=response.url,
                    fetcher="direct",
                    status_code=response.status_code,
                    content=content,
                    blocked=False,
                )
            errors.append(f"direct:{response.status_code}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"direct:{type(exc).__name__}:{exc}")

    if source != "onehousing" and crawl.get("reader_fallback_enabled", True):
        reader_prefix = crawl.get("reader_prefix", "")
        reader_url = f"{reader_prefix}{url}"
        try:
            response = requests.get(reader_url, headers=headers, timeout=timeout)
            content = response.text or ""
            return FetchResult(
                url=url,
                final_url=response.url,
                fetcher="reader",
                status_code=response.status_code,
                content=content,
                blocked=blocked_content(content),
                error="; ".join(errors) if errors else None,
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"reader:{type(exc).__name__}:{exc}")

    return FetchResult(
        url=url,
        final_url=url,
        fetcher="none",
        status_code=None,
        content="",
        blocked=True,
        error="; ".join(errors) if errors else "no fetcher enabled",
    )


def load_cached_fetch(store, url: str) -> FetchResult | None:
    row = store.latest_raw_fetch(url)
    if not row:
        return None
    path = PROJECT_ROOT / row["content_path"]
    if not path.exists():
        return None
    return FetchResult(
        url=str(row["url"]),
        final_url=str(row["url"]),
        fetcher=f"cached:{row['fetcher']}",
        status_code=row.get("status_code"),
        content=path.read_text(encoding="utf-8"),
        blocked=bool(row.get("blocked")),
        error=row.get("error"),
    )


def crawl_once(
    config: AppConfig,
    db_path: str | Path = DEFAULT_DB_PATH,
    limit: int | None = None,
    source_filter: str | None = None,
) -> dict[str, Any]:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    max_pages = limit or get_nested(config, "crawl", "max_pages_per_run", default=None)
    delay = float(get_nested(config, "crawl", "delay_seconds", default=1.5))
    seed_targets = iter_page_targets(config, source_filter=source_filter)
    targets = list(seed_targets)
    seen_target_urls = {target["url"] for target in targets}
    fetched_at = datetime.now(UTC)
    all_records: list[dict[str, Any]] = []
    all_snapshots: list[dict[str, Any]] = []
    all_candidates: list[dict[str, Any]] = []
    fetch_reports: list[dict[str, Any]] = []

    store = get_store(db_path)
    store.init()
    index = 0
    while index < len(targets) and (max_pages is None or index < int(max_pages)):
        target = targets[index]
        index += 1
        result = None
        if get_nested(config, "crawl", "reuse_existing_fetch", default=True):
            result = load_cached_fetch(store, target["url"])
        result = result or fetch_page(target, config)
        content_hash = hashlib.sha256(result.content.encode("utf-8", errors="ignore")).hexdigest()
        if result.fetcher.startswith("cached:"):
            cached_row = store.latest_raw_fetch(target["url"])
            raw_path = PROJECT_ROOT / cached_row["content_path"]
        else:
            raw_stem = target["project_slug"] or target.get("source") or "source"
            raw_path = RAW_DIR / f"{fetched_at.strftime('%Y%m%dT%H%M%SZ')}_{raw_stem}_{index}.md"
            raw_path.write_text(result.content, encoding="utf-8")

        records = parse_listing_markdown(result.content, config, target, fetched_at)
        snapshots = parse_price_snapshots(result.content, config, target, fetched_at)
        candidates = parse_property_candidates(result.content, config, target, fetched_at)
        inserted, updated = store.upsert_listings(records)
        snapshot_inserted, snapshot_updated = store.upsert_price_snapshots(snapshots)
        candidate_inserted, candidate_updated = store.upsert_property_candidates(candidates)
        all_records.extend(records)
        all_snapshots.extend(snapshots)
        all_candidates.extend(candidates)
        discovered_targets = _discover_pagination_targets(result.content, target, config)
        discovered_targets.extend(_discover_related_filter_targets(result.content, target, config))
        discovered_targets.extend(_discover_source_listing_targets(result.content, target, config))
        for discovered in discovered_targets:
            if discovered["url"] not in seen_target_urls:
                seen_target_urls.add(discovered["url"])
                targets.append(discovered)
        if not result.fetcher.startswith("cached:"):
            store.insert_raw_fetch(
                {
                    "url": result.url,
                    "project_slug": target["project_slug"],
                    "purpose": target["purpose"],
                    "property_type": target["property_type"],
                    "fetcher": result.fetcher,
                    "status_code": result.status_code,
                    "fetched_at": fetched_at.isoformat(),
                    "blocked": 1 if result.blocked else 0,
                    "content_path": str(raw_path.relative_to(PROJECT_ROOT)),
                    "content_hash": content_hash,
                    "error": result.error,
                }
            )
        fetch_reports.append(
            {
                "url": result.url,
                "source": target.get("source"),
                "project_slug": target["project_slug"],
                "purpose": target["purpose"],
                "property_type": target["property_type"],
                "fetcher": result.fetcher,
                "status_code": result.status_code,
                "blocked": result.blocked,
                "parsed_records": len(records),
                "parsed_price_snapshots": len(snapshots),
                "parsed_property_candidates": len(candidates),
                "inserted": inserted,
                "updated": updated,
                "snapshot_inserted": snapshot_inserted,
                "snapshot_updated": snapshot_updated,
                "candidate_inserted": candidate_inserted,
                "candidate_updated": candidate_updated,
                "error": result.error,
            }
        )
        if index < len(targets) and (max_pages is None or index < int(max_pages)):
            time.sleep(delay)

    export_listings_csv(db_path)
    export_price_snapshots_csv(db_path)
    export_property_candidates_csv(db_path)
    return {
        "fetched_at": fetched_at.isoformat(),
        "pages": fetch_reports,
        "records_parsed": len(all_records),
        "price_snapshots_parsed": len(all_snapshots),
        "property_candidates_parsed": len(all_candidates),
        "output_csv": str(PROCESSED_DIR / "listings.csv"),
        "output_price_snapshots_csv": str(PROCESSED_DIR / "price_snapshots.csv"),
        "output_property_candidates_csv": str(PROCESSED_DIR / "property_candidates.csv"),
        "db_path": str(db_path),
        "source_filter": source_filter,
    }


def _discover_pagination_targets(markdown: str, target: dict[str, Any], config: AppConfig) -> list[dict[str, Any]]:
    max_page = int(target.get("max_pages") or get_nested(config, "crawl", "pagination_pages_per_seed", default=1))
    if max_page <= 1:
        return []
    if target.get("pagination") == "query_page":
        return _discover_query_page_targets(markdown, target, max_page)
    base_url = target["url"].rstrip("/")
    parsed_base = urlparse(base_url)
    base_path = parsed_base.path.rstrip("/")
    discovered: list[dict[str, str]] = []
    pattern = re.compile(r"https://batdongsan\.com\.vn[^\s\)\"]+/p(?P<page>\d+)", re.IGNORECASE)
    for match in pattern.finditer(markdown):
        page = int(match.group("page"))
        if page > max_page:
            continue
        candidate = match.group(0).rstrip("/")
        parsed_candidate = urlparse(candidate)
        candidate_prefix = re.sub(r"/p\d+$", "", parsed_candidate.path.rstrip("/"))
        if candidate_prefix != base_path:
            continue
        new_target = dict(target)
        new_target["url"] = candidate
        discovered.append(new_target)
    return discovered


def _discover_query_page_targets(markdown: str, target: dict[str, Any], max_page: int) -> list[dict[str, Any]]:
    parsed_base = urlparse(target["url"])
    base_path = parsed_base.path.rstrip("/")
    discovered: list[dict[str, Any]] = []
    soup = BeautifulSoup(markdown, "html.parser")
    for anchor in soup.find_all("a", href=True):
        candidate = urljoin(target["url"], anchor["href"]).rstrip("/")
        parsed = urlparse(candidate)
        if parsed.netloc != parsed_base.netloc or parsed.path.rstrip("/") != base_path:
            continue
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        page = query.get("page")
        if not page or not page.isdigit() or int(page) > max_page:
            continue
        new_target = dict(target)
        new_target["url"] = candidate
        discovered.append(new_target)
    return discovered


def _discover_related_filter_targets(markdown: str, target: dict[str, Any], config: AppConfig) -> list[dict[str, Any]]:
    if not get_nested(config, "crawl", "discover_related_filters", default=False):
        return []
    limit = int(get_nested(config, "crawl", "related_filter_links_per_page", default=5))
    markers = _project_markers_from_config(config, target["project_slug"])
    if not markers:
        return []
    discovered: list[dict[str, str]] = []
    seen: set[str] = set()
    pattern = re.compile(r"https://batdongsan\.com\.vn/[^\s\)\"]+", re.IGNORECASE)
    for match in pattern.finditer(markdown):
        candidate = match.group(0).rstrip("/")
        parsed = urlparse(candidate)
        path = parsed.path.rstrip("/")
        if "pr" in path or not any(marker in path for marker in markers):
            continue
        if "/p" in path:
            continue
        if not any(fragment in path for fragment in ("/gia-", "/dt-")):
            continue
        if target["purpose"] == "rent" and "cho-thue" not in path:
            continue
        if target["purpose"] == "sale" and "ban-" not in path:
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        new_target = dict(target)
        new_target["url"] = candidate
        discovered.append(new_target)
        if len(discovered) >= limit:
            break
    return discovered


def _discover_source_listing_targets(markdown: str, target: dict[str, Any], config: AppConfig) -> list[dict[str, Any]]:
    if target.get("source") != "vinhomesonline":
        return []
    if not get_nested(config, "crawl", "discover_listing_links", default=True):
        return []
    limit = int(get_nested(config, "crawl", "listing_links_per_page", default=24))
    discovered: list[dict[str, Any]] = []
    seen: set[str] = set()
    soup = BeautifulSoup(markdown, "html.parser")
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if "/tin/" not in href:
            continue
        candidate = urljoin(target["url"], href).rstrip("/")
        if candidate in seen:
            continue
        seen.add(candidate)
        new_target = dict(target)
        new_target["url"] = candidate
        if "-rent-" in candidate:
            new_target["purpose"] = "rent"
        discovered.append(new_target)
        if len(discovered) >= limit:
            break
    return discovered


def _project_markers_from_config(config: AppConfig, project_slug: str) -> list[str]:
    project = config.project_by_slug.get(project_slug)
    if not project:
        return []
    markers: set[str] = set()
    for page in project.pages:
        path = urlparse(page.url).path.strip("/")
        parts = path.split("/")
        if parts:
            markers.add(parts[0])
        for part in parts:
            if "vinhomes-" in part:
                markers.add(part)
    return sorted(markers, key=len, reverse=True)


def export_listings_csv(db_path: str | Path = DEFAULT_DB_PATH) -> Path:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PROCESSED_DIR / "listings.csv"
    return export_collection_csv("listing_observation", out_path, db_path, sort_field="observed_at")


def export_price_snapshots_csv(db_path: str | Path = DEFAULT_DB_PATH) -> Path:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PROCESSED_DIR / "price_snapshots.csv"
    return export_collection_csv("price_snapshot", out_path, db_path, sort_field="observed_at")


def export_property_candidates_csv(db_path: str | Path = DEFAULT_DB_PATH) -> Path:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PROCESSED_DIR / "property_candidates.csv"
    return export_collection_csv("property_candidate", out_path, db_path, sort_field="observed_at")
