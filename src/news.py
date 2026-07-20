from __future__ import annotations

import html
import os
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from math import atan2, cos, radians, sin, sqrt
from threading import Lock
from time import monotonic
from typing import Any
from urllib.parse import quote_plus

import requests

from src.amenities import resolve_location_coordinates
from src.config import AppConfig
from src.normalization import infer_project_slug
from src.text import compact_spaces, text_key

NEWS_TIMEOUT_SECONDS = 6
NEWS_USER_AGENT = "HomeValueAI/1.0 (+https://solanai.us)"
NEWS_TOPICS = (
    "quy hoạch",
    "hạ tầng",
    "mở rộng",
    "khởi công",
    "thi công",
    "xây dựng",
    "thông xe",
    "mở mới",
    "vành đai",
    "metro",
    "trường học",
    "bệnh viện",
    "trung tâm thương mại",
)

_NEWS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_NEWS_CACHE_LOCK = Lock()


def project_news(
    config: AppConfig,
    project: str,
    limit: int = 6,
    *,
    location_label: str | None = None,
) -> dict[str, Any]:
    limit = max(1, min(int(limit or 6), 10))
    project_slug = infer_project_slug(config, project, default=project)
    project_cfg = config.project_by_slug.get(project_slug or "")
    project_name = project_cfg.name if project_cfg else compact_spaces(project) or "Vinhomes"
    district = compact_spaces(project_cfg.district_hint if project_cfg else "") if project_cfg else ""
    city = _market_city(config)
    radius_km = _float_env("NEWS_NEARBY_RADIUS_KM", 8.0)
    target_label = _target_location_label(location_label, project_name, district, city)
    queries = _news_queries(project_name, district, city)
    cache_key = _cache_key(project_name, target_label, limit, radius_km, queries)
    cached = _cache_get(cache_key)
    if cached:
        return cached

    error = ""
    try:
        raw_items = _fetch_news_items(queries, limit=max(limit * 2, limit))
        status = "ok" if raw_items else "empty"
    except Exception as exc:  # noqa: BLE001
        raw_items = []
        status = "error"
        error = str(exc)

    geo_limit = max(0, _int_env("NEWS_GEO_MAX_CANDIDATES", 4))
    target_location = resolve_location_coordinates(target_label) if geo_limit else None
    items = _normalize_items(
        raw_items,
        target_location=target_location,
        project_name=project_name,
        district=district,
        city=city,
        radius_km=radius_km,
        geo_limit=geo_limit,
    )
    items = _sort_items(items)[:limit]
    result = {
        "project": project_name,
        "district": district,
        "city": city,
        "query": queries[0] if queries else f'"{project_name}"',
        "queries": queries,
        "search_url": _google_news_search_url(queries[0] if queries else f'"{project_name}"'),
        "status": status,
        "error": error,
        "generated_at": datetime.now(UTC).isoformat(),
        "location_context": {
            "label": target_label,
            "radius_km": radius_km,
            "status": "resolved" if target_location else "unresolved",
            "name": (target_location or {}).get("name"),
            "address": (target_location or {}).get("address"),
            "provider": (target_location or {}).get("provider"),
        },
        "nearby_verified_count": sum(1 for item in items if item.get("proximity_status") == "verified_nearby"),
        "items": items,
        "summary": _news_summary_from_items(items),
    }
    _cache_set(cache_key, result)
    return deepcopy(result)


def clear_news_cache() -> None:
    with _NEWS_CACHE_LOCK:
        _NEWS_CACHE.clear()


def _fetch_news_items(queries: list[str], limit: int) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, min(len(queries), 3))) as executor:
        futures = {executor.submit(_fetch_query_items, query, limit): query for query in queries}
        for future in as_completed(futures):
            query = futures[future]
            try:
                query_items = future.result()
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))
                continue
            for item in query_items:
                url = item.get("url") or ""
                title_key = text_key(item.get("title"))
                dedupe_key = url or title_key
                if not dedupe_key or dedupe_key in seen:
                    continue
                item["query"] = query
                rows.append(item)
                seen.add(dedupe_key)
                if len(rows) >= limit:
                    return rows
    if not rows and errors:
        raise RuntimeError(errors[0])
    return rows


def _fetch_query_items(query: str, limit: int) -> list[dict[str, str]]:
    response = requests.get(
        _google_news_rss_url(query),
        headers={"User-Agent": NEWS_USER_AGENT},
        timeout=_float_env("NEWS_SEARCH_TIMEOUT_SECONDS", NEWS_TIMEOUT_SECONDS),
    )
    response.raise_for_status()
    return _parse_google_news_feed(response.text, limit=limit)


def _normalize_items(
    raw_items: list[dict[str, Any]],
    *,
    target_location: dict[str, Any] | None,
    project_name: str,
    district: str,
    city: str,
    radius_km: float,
    geo_limit: int,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw in raw_items:
        title = compact_spaces(raw.get("title"))
        url = compact_spaces(raw.get("url"))
        source = compact_spaces(raw.get("source")) or "Nguồn tin"
        if not title or not url:
            continue
        status = _event_status(title, raw.get("snippet"))
        aspect = _affected_aspect(title, raw.get("snippet"))
        item = {
            "title": title,
            "snippet": compact_spaces(raw.get("snippet")),
            "source": source,
            "source_name": source,
            "published_at": compact_spaces(raw.get("published_at")),
            "published_text": compact_spaces(raw.get("published_text")),
            "event_date": None,
            "expected_end_date": None,
            "url": url,
            "source_url": url,
            "query": compact_spaces(raw.get("query")),
            "status": status,
            "event_status": status,
            "aspect": aspect,
            "affected_aspect": aspect,
            "direction": _impact_direction(title, aspect, status),
            "impact_direction": _impact_direction(title, aspect, status),
            "horizon": _impact_horizon(status),
            "impact_horizon": _impact_horizon(status),
            "evidence_strength": _evidence_strength(source, status, url),
            "proximity_status": "unverified",
            "proximity_text": "Chưa xác minh khoảng cách với vị trí định giá.",
            "summary": _event_summary(status, aspect),
        }
        if _mentions_area(title, project_name, district):
            item["proximity_status"] = "same_area_unverified"
            item["proximity_text"] = "Cùng khu vực tìm kiếm, chưa xác minh khoảng cách."
        items.append(item)

    if not target_location or geo_limit <= 0 or not items:
        return _with_main_insight_flags(items)

    candidates = list(enumerate(items[:geo_limit]))
    with ThreadPoolExecutor(max_workers=max(1, min(len(candidates), 3))) as executor:
        futures = {
            executor.submit(_resolve_event_location, item, project_name, district, city): index
            for index, item in candidates
        }
        for future in as_completed(futures):
            index = futures[future]
            event_location = future.result()
            if not event_location:
                continue
            distance_m = round(
                _haversine_distance_m(
                    float(target_location["lat"]),
                    float(target_location["lng"]),
                    float(event_location["lat"]),
                    float(event_location["lng"]),
                )
            )
            item = items[index]
            item["matched_location"] = {
                "name": event_location.get("name"),
                "address": event_location.get("address"),
                "provider": event_location.get("provider"),
            }
            item["distance_m"] = distance_m
            item["distance_km"] = round(distance_m / 1000, 2)
            if distance_m <= radius_km * 1000:
                item["proximity_status"] = "verified_nearby"
                item["proximity_text"] = f"Cách vị trí định giá khoảng {_format_km(distance_m / 1000)} km."
            else:
                item["proximity_status"] = "outside_radius"
                item["proximity_text"] = f"Ngoài bán kính {_format_km(radius_km)} km quanh vị trí định giá."
    return _with_main_insight_flags(items)


def _with_main_insight_flags(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for item in items:
        item["main_insight"] = (
            item.get("proximity_status") == "verified_nearby"
            and item.get("evidence_strength") != "low"
            and item.get("event_status") not in {"unknown", "rumored"}
        )
    return items


def _resolve_event_location(
    item: dict[str, Any],
    project_name: str,
    district: str,
    city: str,
) -> dict[str, Any] | None:
    query = _event_location_query(item.get("title"), project_name, district, city)
    if not query:
        return None
    location = resolve_location_coordinates(query)
    if not location:
        return None
    if not _location_matches_title(item.get("title"), location, project_name, district):
        return None
    return location


def _event_location_query(title: object, project_name: str, district: str, city: str) -> str:
    text = compact_spaces(title)
    if not text:
        return ""
    location_bits = ", ".join(part for part in (district, city) if part)
    return ", ".join(part for part in (text, location_bits or project_name) if part)


def _location_matches_title(title: object, location: dict[str, Any], project_name: str, district: str) -> bool:
    title_tokens = _significant_tokens(title)
    place_tokens = _significant_tokens(" ".join([location.get("name") or "", location.get("address") or ""]))
    if not title_tokens or not place_tokens:
        return False
    overlap = title_tokens & place_tokens
    if len(overlap) >= 2:
        return True
    if overlap and any(len(token) >= 5 for token in overlap):
        return True
    area_tokens = _significant_tokens(" ".join([project_name, district]))
    title_area_overlap = title_tokens & area_tokens
    return bool(title_area_overlap and title_area_overlap <= place_tokens and len(title_area_overlap) >= 2)


def _significant_tokens(value: object) -> set[str]:
    key = text_key(value)
    tokens = {token for token in re.split(r"\W+", key) if len(token) >= 3}
    return tokens - {
        "tin",
        "moi",
        "bat",
        "dong",
        "san",
        "gia",
        "ha",
        "noi",
        "vinhomes",
        "du",
        "an",
        "khu",
        "can",
        "ho",
        "chung",
        "cu",
        "chuan",
        "bi",
        "sap",
        "quy",
        "hoach",
        "mo",
        "rong",
        "xay",
        "dung",
        "thi",
        "cong",
        "khoi",
        "cong",
    }


def _sort_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    proximity_rank = {
        "verified_nearby": 0,
        "same_area_unverified": 1,
        "outside_radius": 2,
        "unverified": 3,
    }
    evidence_rank = {"high": 0, "medium": 1, "low": 2}
    status_rank = {
        "completed": 0,
        "under_construction": 1,
        "officially_announced": 2,
        "confirmed": 3,
        "proposed": 4,
        "rumored": 5,
        "unknown": 6,
    }
    return sorted(
        items,
        key=lambda item: (
            proximity_rank.get(str(item.get("proximity_status")), 9),
            evidence_rank.get(str(item.get("evidence_strength")), 9),
            status_rank.get(str(item.get("event_status") or item.get("status")), 9),
            _published_rank(item.get("published_at")),
        ),
        reverse=False,
    )


def _published_rank(value: object) -> float:
    text = compact_spaces(value)
    if not text:
        return 0
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return 0
    return -dt.timestamp()


def _event_status(title: object, snippet: object = "") -> str:
    key = text_key(" ".join([compact_spaces(title), compact_spaces(snippet)]))
    if any(term in key for term in ("khanh thanh", "thong xe", "dua vao hoat dong", "dua vao su dung", "mo cua")):
        return "completed"
    if any(term in key for term in ("khoi cong", "thi cong", "dang xay", "dang trien khai", "xay dung")):
        return "under_construction"
    if any(term in key for term in ("phe duyet", "duoc duyet", "ban hanh", "cong bo", "chinh thuc", "quyet dinh")):
        return "officially_announced"
    if any(term in key for term in ("xac nhan", "da thong qua")):
        return "confirmed"
    if any(term in key for term in ("de xuat", "kien nghi", "nghien cuu", "du kien", "quy hoach du kien")):
        return "proposed"
    if any(term in key for term in ("tin don", "chua xac thuc", "nghe noi")):
        return "rumored"
    return "unknown"


def _affected_aspect(title: object, snippet: object = "") -> str:
    key = text_key(" ".join([compact_spaces(title), compact_spaces(snippet)]))
    if any(term in key for term in ("duong", "vanh dai", "metro", "giao thong", "cau", "tuyen", "nut giao", "xe buyt")):
        return "connectivity"
    if any(term in key for term in ("phap ly", "so hong", "quy hoach", "phe duyet", "dat dai")):
        return "legal"
    if any(term in key for term in ("nguon cung", "mo ban", "ban giao", "du an moi", "can ho moi")):
        return "supply"
    if any(term in key for term in ("truong", "benh vien", "trung tam thuong mai", "tien ich", "cong vien", "ho dieu hoa")):
        return "demand"
    if any(term in key for term in ("van hanh", "phi dich vu", "quan ly", "bao tri")):
        return "operation"
    if any(term in key for term in ("ngap", "o nhiem", "moi truong", "rac thai", "tieng on")):
        return "environment"
    return "other"


def _impact_direction(title: object, aspect: str, status: str) -> str:
    key = text_key(title)
    if any(term in key for term in ("ngap", "o nhiem", "ket xe", "un tac", "tam dung", "cham tien do")):
        return "negative"
    if status in {"proposed", "rumored", "unknown"}:
        return "unclear"
    if status == "under_construction":
        return "mixed"
    if aspect in {"connectivity", "legal", "demand", "operation"}:
        return "positive"
    if aspect == "supply":
        return "mixed"
    return "unclear"


def _impact_horizon(status: str) -> str:
    if status == "completed":
        return "short"
    if status == "under_construction":
        return "short"
    if status in {"officially_announced", "confirmed"}:
        return "medium"
    if status in {"proposed", "rumored"}:
        return "long"
    return "medium"


def _evidence_strength(source: str, status: str, url: str) -> str:
    if not url or status in {"unknown", "rumored"}:
        return "low"
    source_key = text_key(source)
    if any(term in source_key for term in ("chinh phu", "ubnd", "so ", "cong thong tin", "vinhomes", "vingroup")):
        return "high"
    if status in {"completed", "under_construction", "officially_announced", "confirmed"}:
        return "medium"
    return "low"


def _event_summary(status: str, aspect: str) -> str:
    status_label = {
        "completed": "đã hoàn thành",
        "under_construction": "đang thi công/triển khai",
        "officially_announced": "đã được công bố chính thức",
        "confirmed": "đã được xác nhận",
        "proposed": "đang ở mức đề xuất/nghiên cứu",
        "rumored": "chưa xác thực",
        "unknown": "chưa rõ trạng thái",
    }.get(status, "chưa rõ trạng thái")
    aspect_label = {
        "connectivity": "kết nối giao thông",
        "legal": "quy hoạch/pháp lý",
        "supply": "nguồn cung",
        "demand": "nhu cầu và tiện ích",
        "operation": "vận hành",
        "environment": "môi trường sống",
        "other": "bối cảnh khu vực",
    }.get(aspect, "bối cảnh khu vực")
    return f"Sự kiện {status_label}, liên quan đến {aspect_label}."


def _mentions_area(title: object, project_name: str, district: str) -> bool:
    key = text_key(title)
    area_keys = [text_key(project_name), text_key(district)]
    return any(area and area in key for area in area_keys)


def _news_queries(project_name: str, district: str, city: str) -> list[str]:
    topic_group = "(" + " OR ".join(f'"{topic}"' for topic in NEWS_TOPICS) + ")"
    queries = [
        f'"{project_name}" {topic_group}',
    ]
    if district:
        queries.append(f'"{district}" {topic_group} "{city}"')
    else:
        queries.append(f'"{project_name}" "{city}" hạ tầng quy hoạch')
    return queries


def _target_location_label(location_label: str | None, project_name: str, district: str, city: str) -> str:
    parts = [location_label, project_name, district, city]
    cleaned: list[str] = []
    seen: set[str] = set()
    for part in parts:
        text = compact_spaces(part)
        key = text_key(text)
        if text and key not in seen:
            cleaned.append(text)
            seen.add(key)
    return ", ".join(cleaned)


def _market_city(config: AppConfig) -> str:
    market = config.raw.get("market") if isinstance(config.raw, dict) else None
    city = (market or {}).get("city") if isinstance(market, dict) else None
    return compact_spaces(city) or "Hà Nội"


def _google_news_rss_url(query: str) -> str:
    encoded = quote_plus(query)
    return f"https://news.google.com/rss/search?q={encoded}&hl=vi&gl=VN&ceid=VN:vi"


def _google_news_search_url(query: str) -> str:
    encoded = quote_plus(query)
    return f"https://news.google.com/search?q={encoded}&hl=vi&gl=VN&ceid=VN:vi"


def _parse_google_news_feed(xml_text: str, limit: int) -> list[dict[str, str]]:
    root = ET.fromstring(xml_text)
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in root.findall(".//item"):
        title = _clean_feed_text(item.findtext("title"))
        url = compact_spaces(item.findtext("link"))
        if not title or not url or url in seen:
            continue
        source = _clean_feed_text(item.findtext("source")) or _source_from_title(title)
        title = _title_without_source(title, source)
        published_at, published_text = _published_fields(item.findtext("pubDate"))
        rows.append(
            {
                "title": title,
                "snippet": _clean_feed_text(item.findtext("description")),
                "source": source,
                "published_at": published_at,
                "published_text": published_text,
                "url": url,
            }
        )
        seen.add(url)
        if len(rows) >= limit:
            break
    return rows


def _news_summary_from_items(items: list[dict[str, Any]]) -> str:
    verified = [item for item in items if item.get("proximity_status") == "verified_nearby"]
    if verified:
        first = verified[0]
        return f"Tin gần vị trí cần theo dõi: {first.get('title')} ({first.get('source')})."
    if items:
        first = items[0]
        return f"Có tin cùng khu vực cần theo dõi nhưng chưa đủ dữ liệu để xác minh khoảng cách: {first.get('title')}."
    return "Chưa có tin mới đủ rõ để đưa vào nhận định."


def _clean_feed_text(value: object) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return compact_spaces(text)


def _source_from_title(title: str) -> str:
    if " - " in title:
        return title.rsplit(" - ", 1)[-1].strip()
    return "Google News"


def _title_without_source(title: str, source: str) -> str:
    suffix = f" - {source}"
    return title[: -len(suffix)].strip() if source and title.endswith(suffix) else title


def _published_fields(value: object) -> tuple[str, str]:
    text = compact_spaces(value)
    if not text:
        return "", ""
    try:
        dt = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return "", text
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return dt.isoformat(), dt.strftime("%d/%m/%Y")


def _cache_key(project_name: str, target_label: str, limit: int, radius_km: float, queries: list[str]) -> str:
    return "|".join([text_key(project_name), text_key(target_label), str(limit), str(radius_km), *map(text_key, queries)])


def _cache_get(key: str) -> dict[str, Any] | None:
    ttl = max(0, _int_env("NEWS_CACHE_TTL_SECONDS", 1800))
    if ttl <= 0:
        return None
    now = monotonic()
    with _NEWS_CACHE_LOCK:
        row = _NEWS_CACHE.get(key)
        if not row:
            return None
        created, value = row
        if now - created > ttl:
            _NEWS_CACHE.pop(key, None)
            return None
        return deepcopy(value)


def _cache_set(key: str, value: dict[str, Any]) -> None:
    ttl = max(0, _int_env("NEWS_CACHE_TTL_SECONDS", 1800))
    if ttl <= 0:
        return
    with _NEWS_CACHE_LOCK:
        _NEWS_CACHE[key] = (monotonic(), deepcopy(value))


def _haversine_distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius_m = 6_371_000
    phi1 = radians(lat1)
    phi2 = radians(lat2)
    d_phi = radians(lat2 - lat1)
    d_lambda = radians(lng2 - lng1)
    a = sin(d_phi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(d_lambda / 2) ** 2
    return 2 * radius_m * atan2(sqrt(a), sqrt(1 - a))


def _format_km(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default
