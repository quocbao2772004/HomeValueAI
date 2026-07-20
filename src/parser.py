from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from src.config import AppConfig
from src.normalization import (
    infer_project_slug,
    infer_property_type,
    normalize_furniture,
    normalize_view,
    parse_area,
    parse_bedrooms,
    parse_price,
    quality_flags,
)
from src.text import compact_spaces, text_key

LISTING_URL_RE = re.compile(r"https://batdongsan\.com\.vn/[^\s\)\"]+pr(?P<id>\d+)", re.IGNORECASE)
PRICE_AREA_RE = re.compile(
    r"(?P<price>(?:\d+(?:[,.]\d+)?\s*(?:tỷ|ty|triệu|tr)(?:\s*/?\s*(?:tháng|th|1 tháng))?|Thỏa thuận))\s*·\s*"
    r"(?P<area>\d+(?:[,.]\d+)?\s*m[²2])"
    r"(?:\s*·\s*(?P<ppm>\d+(?:[,.]\d+)?\s*tr/m[²2]))?",
    re.IGNORECASE,
)
TITLE_RE = re.compile(r"\s+\"(?P<title>[^\"]+)\"\)")


def blocked_content(text: str) -> bool:
    lowered = text.lower()
    short_blocked = len(text) < 1500 and ("just a moment" in lowered or "security verification" in lowered)
    return short_blocked or "target url returned error 403" in lowered


def _title_from_url(url: str) -> str:
    slug = urlparse(url).path.rsplit("/", 1)[-1]
    slug = re.sub(r"-pr\d+$", "", slug)
    return compact_spaces(slug.replace("-", " "))


def parse_listing_markdown(
    markdown: str,
    config: AppConfig,
    page_meta: dict[str, str],
    observed_at: datetime | None = None,
) -> list[dict[str, Any]]:
    source = _source_from_meta(page_meta)
    if source == "onehousing":
        return parse_onehousing_html(markdown, config, page_meta, observed_at)
    if source == "vinhomesonline":
        return parse_vinhomesonline_html(markdown, config, page_meta, observed_at)
    if source == "vinhomesland":
        return []
    return _parse_batdongsan_markdown(markdown, config, page_meta, observed_at)


def parse_price_snapshots(
    html: str,
    config: AppConfig,
    page_meta: dict[str, str],
    observed_at: datetime | None = None,
) -> list[dict[str, Any]]:
    source = _source_from_meta(page_meta)
    if source == "vinhomesland":
        return parse_vinhomesland_snapshots(html, config, page_meta, observed_at)
    return []


def parse_property_candidates(
    html: str,
    config: AppConfig,
    page_meta: dict[str, str],
    observed_at: datetime | None = None,
) -> list[dict[str, Any]]:
    source = _source_from_meta(page_meta)
    if source == "vinhomesonline":
        return parse_vinhomesonline_candidates(html, config, page_meta, observed_at)
    return []


def _source_from_meta(page_meta: dict[str, str]) -> str:
    source = page_meta.get("source")
    if source and source != "auto":
        return source
    host = urlparse(page_meta.get("url", "")).netloc.lower()
    if "onehousing.vn" in host:
        return "onehousing"
    if "vinhomesonline.vn" in host:
        return "vinhomesonline"
    if "vinhomesland.vn" in host:
        return "vinhomesland"
    return "batdongsan"


def _parse_batdongsan_markdown(
    markdown: str,
    config: AppConfig,
    page_meta: dict[str, str],
    observed_at: datetime | None = None,
) -> list[dict[str, Any]]:
    observed_at = observed_at or datetime.now(UTC)
    records: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    default_project_slug = None
    if config.raw.get("crawl", {}).get("allow_project_from_confirmed_page", False):
        default_project_slug = _confirmed_page_project_slug(markdown, config, page_meta.get("project_slug"))

    for match in LISTING_URL_RE.finditer(markdown):
        url = match.group(0)
        if url in seen_urls:
            continue
        seen_urls.add(url)

        window_start = max(0, match.start() - 1400)
        window_end = min(len(markdown), match.end() + 250)
        context = markdown[window_start:window_end]
        price_area_matches = list(PRICE_AREA_RE.finditer(context))
        if not price_area_matches:
            continue
        price_area = price_area_matches[-1]
        price = parse_price(price_area.group("price"), page_meta.get("purpose"))
        ppm = parse_price(price_area.group("ppm") or "", page_meta.get("purpose"))
        area_m2 = parse_area(price_area.group("area"))

        title_match = TITLE_RE.search(markdown[match.end() : match.end() + 280])
        title = compact_spaces(title_match.group("title")) if title_match else _title_from_url(url)
        local_context = compact_spaces(context)
        explicit_project_slug = infer_project_slug(config, title, url, default=None)
        project_slug = explicit_project_slug or default_project_slug
        project = config.project_by_slug.get(project_slug or "")
        if not project:
            continue

        price_total_vnd = price.price_total_vnd
        price_per_m2_vnd = ppm.price_per_m2_vnd or price.price_per_m2_vnd
        rent_monthly_vnd = price.rent_monthly_vnd
        if page_meta.get("purpose") == "rent" and price.price_total_vnd and price.price_total_vnd < 500_000_000:
            rent_monthly_vnd = price.price_total_vnd
            price_total_vnd = None
        if price_total_vnd and area_m2 and not price_per_m2_vnd:
            price_per_m2_vnd = price_total_vnd / area_m2
        if price_per_m2_vnd and area_m2 and not price_total_vnd and page_meta.get("purpose") == "sale":
            price_total_vnd = price_per_m2_vnd * area_m2

        record = {
            "source": "batdongsan",
            "source_url": url,
            "external_id": match.group("id"),
            "observed_at": observed_at.isoformat(),
            "first_seen_at": observed_at.isoformat(),
            "last_seen_at": observed_at.isoformat(),
            "title": title,
            "address": _extract_address(local_context),
            "project_slug": project.slug,
            "project_name": project.name,
            "property_type": infer_property_type(title, default=page_meta.get("property_type")),
            "purpose": page_meta.get("purpose", "sale"),
            "price_total_vnd": price_total_vnd,
            "price_per_m2_vnd": price_per_m2_vnd,
            "rent_monthly_vnd": rent_monthly_vnd,
            "area_m2": area_m2,
            "bedrooms": parse_bedrooms(title, local_context),
            "bathrooms": _extract_bathrooms(local_context),
            "floor_number": _extract_floor(title, local_context),
            "total_floors": None,
            "subdivision": _extract_subdivision(title, local_context),
            "tower": _extract_tower(title, local_context),
            "view": normalize_view(title, local_context),
            "furniture": normalize_furniture(title, local_context),
            "legal_status": "sổ đỏ/sổ hồng" if "sổ" in local_context.lower() else None,
            "is_verified": 1 if "tin xác thực" in local_context.lower() else 0,
        }
        record["quality_flags"] = quality_flags(record, config)
        if not explicit_project_slug and default_project_slug:
            record["quality_flags"].append("project_inferred_from_page")
        record["dedupe_key"] = f"{record['source']}:{record['external_id'] or record['source_url']}"
        records.append(record)

    return records


def parse_vinhomesonline_html(
    html: str,
    config: AppConfig,
    page_meta: dict[str, str],
    observed_at: datetime | None = None,
) -> list[dict[str, Any]]:
    observed_at = observed_at or datetime.now(UTC)
    soup = BeautifulSoup(html, "html.parser")
    records: list[dict[str, Any]] = []
    detail = _vinhomesonline_detail_to_record(soup, config, page_meta, observed_at)
    if detail:
        records.append(detail)
    records.extend(_vinhomesonline_cards_to_records(soup, config, page_meta, observed_at))
    return records


def parse_vinhomesonline_candidates(
    html: str,
    config: AppConfig,
    page_meta: dict[str, str],
    observed_at: datetime | None = None,
) -> list[dict[str, Any]]:
    observed_at = observed_at or datetime.now(UTC)
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[dict[str, Any]] = []
    detail = _vinhomesonline_detail_to_candidate(soup, config, page_meta, observed_at)
    if detail:
        candidates.append(detail)
    candidates.extend(_vinhomesonline_cards_to_candidates(soup, config, page_meta, observed_at))
    return candidates


def _vinhomesonline_detail_to_record(
    soup: BeautifulSoup,
    config: AppConfig,
    page_meta: dict[str, str],
    observed_at: datetime,
) -> dict[str, Any] | None:
    product = _jsonld_product(soup)
    if not product:
        return None
    title = compact_spaces(product.get("name"))
    description = compact_spaces(product.get("description"))
    offer = product.get("offers") if isinstance(product.get("offers"), dict) else {}
    source_url = compact_spaces(offer.get("url")) or page_meta.get("url")
    if source_url and source_url.startswith("http://"):
        source_url = "https://" + source_url.removeprefix("http://")
    labels = _html_label_values(soup)
    project_name = labels.get("Dự án") or _vinhomesonline_breadcrumb_project(soup) or _project_from_title(title)
    project_slug = infer_project_slug(config, project_name, title, description, default=None)
    project = config.project_by_slug.get(project_slug or "")
    if not project:
        return None

    purpose = _vinhomesonline_purpose(title, source_url, page_meta.get("purpose"))
    offer_price = _numeric(offer.get("price"))
    area_m2 = parse_area(labels.get("Diện tích thông thủy") or labels.get("Diện tích") or _regex_first(description, r"diện tích\s*([\d.,]+\s*m[²2])"))
    price_total_vnd = offer_price if purpose == "sale" else None
    rent_monthly_vnd = offer_price if purpose == "rent" else None
    price_per_m2_vnd = price_total_vnd / area_m2 if price_total_vnd and area_m2 else None
    prop_type = infer_property_type(labels.get("Loại hình"), title, description, default=page_meta.get("property_type"))
    status = compact_spaces(labels.get("Tình trạng"))

    record = {
        "source": "vinhomesonline",
        "source_url": source_url,
        "external_id": urlparse(source_url or page_meta.get("url", "")).path.rsplit("/", 1)[-1],
        "observed_at": observed_at.isoformat(),
        "first_seen_at": observed_at.isoformat(),
        "last_seen_at": observed_at.isoformat(),
        "title": title or _title_from_url(source_url or page_meta.get("url", "")),
        "address": _extract_vinhomesonline_address(soup),
        "project_slug": project.slug,
        "project_name": project.name,
        "property_type": prop_type,
        "purpose": purpose,
        "price_total_vnd": price_total_vnd,
        "price_per_m2_vnd": price_per_m2_vnd,
        "rent_monthly_vnd": rent_monthly_vnd,
        "area_m2": area_m2,
        "bedrooms": parse_bedrooms(labels.get("Phòng ngủ"), description, title),
        "bathrooms": _extract_bathrooms(labels.get("Phòng vệ sinh") or description),
        "floor_number": _extract_floor(title, description),
        "total_floors": None,
        "subdivision": _vinhomesonline_subdivision(description),
        "tower": _extract_tower(title, description),
        "view": normalize_view(labels.get("Hướng cửa"), description, title),
        "furniture": normalize_furniture(labels.get("Hoàn thiện"), description),
        "legal_status": "sổ hồng" if "sổ hồng" in description.lower() else None,
        "is_verified": 0,
    }
    record["quality_flags"] = quality_flags(record, config)
    record["quality_flags"].append("structured_vinhomesonline")
    if text_key(status) == "da ban":
        record["quality_flags"].append("status_sold")
    record["dedupe_key"] = f"{record['source']}:{record['external_id'] or record['source_url']}"
    return record


def _vinhomesonline_cards_to_records(
    soup: BeautifulSoup,
    config: AppConfig,
    page_meta: dict[str, str],
    observed_at: datetime,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    base_url = page_meta.get("url", "https://vinhomesonline.vn/")
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "")
        if "/tin/" not in href:
            continue
        source_url = urljoin(base_url, href)
        if source_url in seen:
            continue
        seen.add(source_url)
        context = compact_spaces(anchor.get_text(" ", strip=True))
        if not context:
            continue
        project_slug = infer_project_slug(config, context, default=None)
        project = config.project_by_slug.get(project_slug or "")
        if not project:
            continue
        purpose = _vinhomesonline_purpose(context, source_url, page_meta.get("purpose"))
        price_total_vnd = None
        rent_monthly_vnd = None
        price_per_m2_vnd = None
        if purpose == "rent":
            rent_monthly_vnd = parse_price(_regex_first(context, r"(\d+(?:[,.]\d+)?\s*triệu\s*/\s*tháng)"), "rent").rent_monthly_vnd
        else:
            price_total_vnd = parse_price(_regex_first(context, r"(\d+(?:[,.]\d+)?\s*tỷ)"), "sale").price_total_vnd
            price_per_m2_vnd = parse_price(_regex_first(context, r"(\d+(?:[,.]\d+)?\s*triệu\s*/\s*m[²2])"), "sale").price_per_m2_vnd
        area_m2 = parse_area(_regex_first(context, r"(\d+(?:[,.]\d+)?)\s*m[²2]"))
        if price_total_vnd and area_m2 and not price_per_m2_vnd:
            price_per_m2_vnd = price_total_vnd / area_m2
        external_id = urlparse(source_url).path.rsplit("/", 1)[-1]
        record = {
            "source": "vinhomesonline",
            "source_url": source_url,
            "external_id": external_id,
            "observed_at": observed_at.isoformat(),
            "first_seen_at": observed_at.isoformat(),
            "last_seen_at": observed_at.isoformat(),
            "title": _vinhomesonline_card_title(context),
            "address": _extract_address(context),
            "project_slug": project.slug,
            "project_name": project.name,
            "property_type": infer_property_type(context, default=page_meta.get("property_type")),
            "purpose": purpose,
            "price_total_vnd": price_total_vnd,
            "price_per_m2_vnd": price_per_m2_vnd,
            "rent_monthly_vnd": rent_monthly_vnd,
            "area_m2": area_m2,
            "bedrooms": parse_bedrooms(context),
            "bathrooms": _extract_bathrooms(context),
            "floor_number": _extract_floor(context),
            "total_floors": None,
            "subdivision": _extract_subdivision(context),
            "tower": _extract_tower(context),
            "view": normalize_view(context),
            "furniture": normalize_furniture(context),
            "legal_status": None,
            "is_verified": 0,
        }
        record["quality_flags"] = quality_flags(record, config)
        record["quality_flags"].append("card_vinhomesonline")
        if "đã bán" in context.lower():
            record["quality_flags"].append("status_sold")
        record["dedupe_key"] = f"{record['source']}:{record['external_id']}"
        records.append(record)
    return records


def _vinhomesonline_detail_to_candidate(
    soup: BeautifulSoup,
    config: AppConfig,
    page_meta: dict[str, str],
    observed_at: datetime,
) -> dict[str, Any] | None:
    product = _jsonld_product(soup)
    if not product:
        return None
    title = compact_spaces(product.get("name"))
    description = compact_spaces(product.get("description"))
    offer = product.get("offers") if isinstance(product.get("offers"), dict) else {}
    source_url = compact_spaces(offer.get("url")) or page_meta.get("url")
    if source_url and source_url.startswith("http://"):
        source_url = "https://" + source_url.removeprefix("http://")
    labels = _html_label_values(soup)
    raw_project = labels.get("Dự án") or _vinhomesonline_breadcrumb_project(soup) or _project_from_title(title)
    purpose = _vinhomesonline_purpose(title, source_url, page_meta.get("purpose"))
    offer_price = _numeric(offer.get("price"))
    area_m2 = parse_area(labels.get("Diện tích thông thủy") or labels.get("Diện tích") or _regex_first(description, r"diện tích\s*([\d.,]+\s*m[²2])"))
    price_total_vnd = offer_price if purpose == "sale" else None
    rent_monthly_vnd = offer_price if purpose == "rent" else None
    price_per_m2_vnd = price_total_vnd / area_m2 if price_total_vnd and area_m2 else None
    mapped_slug = infer_project_slug(config, raw_project, title, description, default=None)
    status = compact_spaces(labels.get("Tình trạng"))
    external_id = urlparse(source_url or page_meta.get("url", "")).path.rsplit("/", 1)[-1]
    flags = ["candidate_vinhomesonline", "structured_candidate"]
    if not mapped_slug:
        flags.append("unmapped_project")
    if text_key(status) == "da ban":
        flags.append("status_sold")
    return {
        "source": "vinhomesonline",
        "source_url": source_url,
        "external_id": external_id,
        "observed_at": observed_at.isoformat(),
        "raw_project_name": raw_project,
        "mapped_project_slug": mapped_slug,
        "title": title or _title_from_url(source_url or page_meta.get("url", "")),
        "address": _extract_vinhomesonline_address(soup),
        "property_type": infer_property_type(labels.get("Loại hình"), title, description, default=page_meta.get("property_type")),
        "purpose": purpose,
        "price_total_vnd": price_total_vnd,
        "price_per_m2_vnd": price_per_m2_vnd,
        "rent_monthly_vnd": rent_monthly_vnd,
        "area_m2": area_m2,
        "bedrooms": parse_bedrooms(labels.get("Phòng ngủ"), description, title),
        "bathrooms": _extract_bathrooms(labels.get("Phòng vệ sinh") or description),
        "quality_flags": flags,
        "dedupe_key": f"property_candidate:vinhomesonline:{external_id}",
    }


def _vinhomesonline_cards_to_candidates(
    soup: BeautifulSoup,
    config: AppConfig,
    page_meta: dict[str, str],
    observed_at: datetime,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    base_url = page_meta.get("url", "https://vinhomesonline.vn/")
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "")
        if "/tin/" not in href:
            continue
        source_url = urljoin(base_url, href)
        if source_url in seen:
            continue
        seen.add(source_url)
        context = compact_spaces(anchor.get_text(" ", strip=True))
        if not context:
            continue
        purpose = _vinhomesonline_purpose(context, source_url, page_meta.get("purpose"))
        price_total_vnd = None
        rent_monthly_vnd = None
        price_per_m2_vnd = None
        if purpose == "rent":
            rent_monthly_vnd = parse_price(_regex_first(context, r"(\d+(?:[,.]\d+)?\s*triệu\s*/\s*tháng)"), "rent").rent_monthly_vnd
        else:
            price_total_vnd = parse_price(_regex_first(context, r"(\d+(?:[,.]\d+)?\s*tỷ)"), "sale").price_total_vnd
            price_per_m2_vnd = parse_price(_regex_first(context, r"(\d+(?:[,.]\d+)?\s*triệu\s*/\s*m[²2])"), "sale").price_per_m2_vnd
        area_m2 = parse_area(_regex_first(context, r"(\d+(?:[,.]\d+)?)\s*m[²2]"))
        if price_total_vnd and area_m2 and not price_per_m2_vnd:
            price_per_m2_vnd = price_total_vnd / area_m2
        raw_project = _vinhomesonline_project_from_card(context)
        mapped_slug = infer_project_slug(config, raw_project, context, default=None)
        external_id = urlparse(source_url).path.rsplit("/", 1)[-1]
        flags = ["candidate_vinhomesonline", "card_candidate"]
        if not mapped_slug:
            flags.append("unmapped_project")
        if "đã bán" in context.lower():
            flags.append("status_sold")
        candidates.append(
            {
                "source": "vinhomesonline",
                "source_url": source_url,
                "external_id": external_id,
                "observed_at": observed_at.isoformat(),
                "raw_project_name": raw_project,
                "mapped_project_slug": mapped_slug,
                "title": _vinhomesonline_card_title(context),
                "address": _extract_address(context),
                "property_type": infer_property_type(context, default=page_meta.get("property_type")),
                "purpose": purpose,
                "price_total_vnd": price_total_vnd,
                "price_per_m2_vnd": price_per_m2_vnd,
                "rent_monthly_vnd": rent_monthly_vnd,
                "area_m2": area_m2,
                "bedrooms": parse_bedrooms(context),
                "bathrooms": _extract_bathrooms(context),
                "quality_flags": flags,
                "dedupe_key": f"property_candidate:vinhomesonline:{external_id}",
            }
        )
    return candidates


def _table_rows(table: Any) -> list[list[str]]:
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = [compact_spaces(cell.get_text(" ", strip=True)) for cell in tr.find_all(["th", "td"])]
        if any(cells):
            rows.append(cells)
    return rows


def _is_type_area_price_table(header: list[str]) -> bool:
    key = text_key(" ".join(header))
    return "loai hinh" in key and "dien tich" in key and "gia ban" in key


def _vinhomesland_snapshot_record(
    project: Any,
    page_meta: dict[str, str],
    observed_at: datetime,
    label: str,
    area_text: str | None,
    price_text: str | None,
    subdivision: str | None,
    table_index: int,
    row_index: int,
    col_index: int | None = None,
) -> dict[str, Any] | None:
    label = compact_spaces(label)
    price_text = compact_spaces(price_text)
    if not label or not price_text or "chưa bán" in price_text.lower():
        return None
    prop_type = infer_property_type(label, default="other")
    if prop_type == "other":
        return None
    price_min, price_max, ppm_min, ppm_max = _price_range_values(price_text)
    if price_min is None and ppm_min is None:
        return None
    area_min, area_max = _area_range_values(area_text)
    if price_min and price_max and area_min and area_max and ppm_min is None:
        ppm_min = price_min / area_max
        ppm_max = price_max / area_min
    key_parts = [
        page_meta.get("url", ""),
        project.slug,
        label,
        subdivision or "",
        area_text or "",
        price_text,
        str(table_index),
        str(row_index),
        str(col_index or ""),
    ]
    digest = hashlib.sha1("|".join(key_parts).encode("utf-8")).hexdigest()[:16]
    flags = ["aggregate_price_snapshot", "source_vinhomesland"]
    if area_min is None:
        flags.append("missing_area_range")
    if price_min != price_max or ppm_min != ppm_max:
        flags.append("range_price")
    return {
        "source": "vinhomesland",
        "source_url": page_meta.get("url"),
        "external_id": digest,
        "observed_at": observed_at.isoformat(),
        "project_slug": project.slug,
        "project_name": project.name,
        "property_type": prop_type,
        "purpose": "sale",
        "label": label,
        "subdivision": compact_spaces(subdivision) or None,
        "area_min_m2": area_min,
        "area_max_m2": area_max,
        "price_min_vnd": price_min,
        "price_max_vnd": price_max,
        "price_per_m2_min_vnd": ppm_min,
        "price_per_m2_max_vnd": ppm_max,
        "basis": "published_price_range",
        "quality_flags": flags,
        "dedupe_key": f"price_snapshot:vinhomesland:{digest}",
    }


def _price_range_values(value: object) -> tuple[float | None, float | None, float | None, float | None]:
    text = compact_spaces(value)
    key = text_key(text)
    numbers = _range_numbers(text)
    if not numbers:
        return None, None, None, None
    low, high = numbers[0], numbers[-1]
    if "trieu" in key and ("m2" in key or "m²" in text.lower()):
        return None, None, low * 1_000_000, high * 1_000_000
    if "ty" in key or "ti" in key:
        return low * 1_000_000_000, high * 1_000_000_000, None, None
    if "trieu" in key:
        return low * 1_000_000, high * 1_000_000, None, None
    return None, None, None, None


def _area_range_values(value: object) -> tuple[float | None, float | None]:
    numbers = _range_numbers(value)
    if not numbers:
        return None, None
    return numbers[0], numbers[-1]


def _range_numbers(value: object) -> list[float]:
    text = re.sub(r"(?i)m\s*2\b", "m", compact_spaces(value))
    numbers: list[float] = []
    for token in re.findall(r"\d+(?:[,.]\d+)?", text):
        try:
            numbers.append(float(token.replace(",", ".")))
        except ValueError:
            continue
    return numbers


def _regex_first(text: str, pattern: str) -> str:
    match = re.search(pattern, text, re.IGNORECASE)
    return compact_spaces(match.group(1)) if match else ""


def _jsonld_product(soup: BeautifulSoup) -> dict[str, Any] | None:
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict) and item.get("@type") == "Product":
                return item
    return None


def _html_label_values(soup: BeautifulSoup) -> dict[str, str]:
    labels = {
        "Mã căn",
        "Loại hình",
        "Phòng ngủ",
        "Phòng vệ sinh",
        "Diện tích thông thủy",
        "Diện tích tim tường",
        "Diện tích",
        "Hướng cửa",
        "Hoàn thiện",
        "Tình trạng",
        "Dự án",
    }
    lines = [compact_spaces(line) for line in soup.get_text("\n", strip=True).splitlines()]
    lines = [line for line in lines if line]
    result: dict[str, str] = {}
    ignored_values = {"Tin tức", "Liên hệ", "Bán sơ cấp", "Bán thứ cấp", "Cho thuê", "Pháp lý"}
    for index, line in enumerate(lines[:-1]):
        value = lines[index + 1]
        if line in labels and value not in ignored_values:
            result[line] = value
    return result


def _vinhomesonline_breadcrumb_project(soup: BeautifulSoup) -> str | None:
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict) or data.get("@type") != "BreadcrumbList":
            continue
        items = data.get("itemListElement") or []
        if len(items) >= 2 and isinstance(items[1], dict):
            return compact_spaces(items[1].get("name"))
    return None


def _vinhomesonline_purpose(*values: Any) -> str:
    text = text_key(" ".join(compact_spaces(value) for value in values))
    if "cho thue" in text or "rent" in text:
        return "rent"
    return "sale"


def _vinhomesonline_subdivision(description: str) -> str | None:
    match = re.search(r"phân khu\s+([^.,]+)", description, re.IGNORECASE)
    return compact_spaces(match.group(1)) if match else None


def _extract_vinhomesonline_address(soup: BeautifulSoup) -> str | None:
    text = soup.get_text(" ", strip=True)
    match = re.search(r"(?:Gia Lâm|Nam Từ Liêm|Hà Nội|Hưng Yên)[^·]{0,80}", text, re.IGNORECASE)
    return compact_spaces(match.group(0)) if match else None


def _project_from_title(title: str) -> str | None:
    if "—" not in title:
        return None
    return compact_spaces(title.split("—")[-1])


def _vinhomesonline_project_from_card(context: str) -> str | None:
    match = re.search(
        r"—\s*(.+?)(?:\s+(?:Studio|Căn hộ|Shophouse|Biệt thự|Nhà phố|Penthouse|Văn phòng|Mặt bằng|Shop|Liền kề)\b|$)",
        context,
        re.IGNORECASE,
    )
    return compact_spaces(match.group(1)) if match else None


def _vinhomesonline_card_title(context: str) -> str:
    match = re.search(r"((?:Bán|Cho thuê)\s+.+?)(?:\s+\d+\s*PN|\s+Studio\s+\d|\s+Căn hộ\s+\d|$)", context, re.IGNORECASE)
    return compact_spaces(match.group(1)) if match else context[:180]


def parse_vinhomesland_snapshots(
    html: str,
    config: AppConfig,
    page_meta: dict[str, str],
    observed_at: datetime | None = None,
) -> list[dict[str, Any]]:
    observed_at = observed_at or datetime.now(UTC)
    soup = BeautifulSoup(html, "html.parser")
    project_slug = page_meta.get("project_slug") or infer_project_slug(config, soup.get_text(" ", strip=True), page_meta.get("url"), default=None)
    project = config.project_by_slug.get(project_slug or "")
    if not project:
        return []
    records: list[dict[str, Any]] = []
    for table_index, table in enumerate(soup.find_all("table")):
        rows = _table_rows(table)
        if len(rows) < 2:
            continue
        if _is_type_area_price_table(rows[0]):
            for row_index, row in enumerate(rows[1:], start=1):
                if len(row) < 3:
                    continue
                record = _vinhomesland_snapshot_record(
                    project,
                    page_meta,
                    observed_at,
                    label=row[0],
                    area_text=row[1],
                    price_text=row[2],
                    subdivision=None,
                    table_index=table_index,
                    row_index=row_index,
                )
                if record:
                    records.append(record)
            continue
        headers = rows[0]
        for row_index, row in enumerate(rows[1:], start=1):
            if len(row) < 2:
                continue
            label = row[0]
            for col_index, price_text in enumerate(row[1:], start=1):
                subdivision = headers[col_index] if col_index < len(headers) else None
                record = _vinhomesland_snapshot_record(
                    project,
                    page_meta,
                    observed_at,
                    label=label,
                    area_text=None,
                    price_text=price_text,
                    subdivision=subdivision,
                    table_index=table_index,
                    row_index=row_index,
                    col_index=col_index,
                )
                if record:
                    records.append(record)
    return records


def parse_onehousing_html(
    html: str,
    config: AppConfig,
    page_meta: dict[str, str],
    observed_at: datetime | None = None,
) -> list[dict[str, Any]]:
    observed_at = observed_at or datetime.now(UTC)
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        return []
    try:
        data = json.loads(script.string)
    except json.JSONDecodeError:
        return []
    inventory = data.get("props", {}).get("pageProps", {}).get("inventory", {})
    items = inventory.get("data") or []
    records: list[dict[str, Any]] = []
    for item in items:
        record = _onehousing_item_to_record(item, config, page_meta, observed_at)
        if record:
            records.append(record)
    return records


def _onehousing_item_to_record(
    item: dict[str, Any],
    config: AppConfig,
    page_meta: dict[str, str],
    observed_at: datetime,
) -> dict[str, Any] | None:
    project_name = compact_spaces(item.get("project_name"))
    sector_name = compact_spaces(item.get("sector_name"))
    block_name = compact_spaces(item.get("block_name"))
    property_code = compact_spaces(item.get("property_code"))
    inventory_code = compact_spaces(item.get("inventory_code"))
    property_type_label = _first_text(item.get("property_type"))
    title = _onehousing_title(item, property_type_label, block_name, sector_name, project_name)
    project_slug = infer_project_slug(config, project_name, sector_name, title, default=None)
    project = config.project_by_slug.get(project_slug or "")
    if not project:
        return None

    price_total_vnd = _numeric(item.get("min_selling_price") or item.get("max_selling_price"))
    price_per_m2_vnd = _numeric(item.get("min_unit_price") or item.get("max_unit_price"))
    area_m2 = _numeric(item.get("min_area") or item.get("max_area"))
    if price_total_vnd and area_m2 and not price_per_m2_vnd:
        price_per_m2_vnd = price_total_vnd / area_m2
    if price_per_m2_vnd and area_m2 and not price_total_vnd:
        price_total_vnd = price_per_m2_vnd * area_m2

    prop_type = _onehousing_property_type(item, page_meta.get("property_type"))
    last_modified = _onehousing_datetime(item.get("last_modified_date")) or observed_at.isoformat()
    bathrooms = item.get("number_of_bathrooms")
    record = {
        "source": "onehousing",
        "source_url": _onehousing_source_url(page_meta.get("url"), title, inventory_code),
        "external_id": compact_spaces(item.get("id")) or inventory_code or property_code,
        "observed_at": observed_at.isoformat(),
        "first_seen_at": observed_at.isoformat(),
        "last_seen_at": last_modified,
        "title": title,
        "address": _join_nonempty(item.get("ward"), item.get("district"), item.get("province")),
        "project_slug": project.slug,
        "project_name": project.name,
        "property_type": prop_type,
        "purpose": page_meta.get("purpose", "sale"),
        "price_total_vnd": price_total_vnd,
        "price_per_m2_vnd": price_per_m2_vnd,
        "rent_monthly_vnd": None,
        "area_m2": area_m2,
        "bedrooms": _int_or_none(item.get("number_of_bedrooms")),
        "bathrooms": _int_or_none(_first_value(bathrooms)),
        "floor_number": _int_or_none(item.get("floor_number")),
        "total_floors": None,
        "subdivision": sector_name or None,
        "tower": block_name or None,
        "view": normalize_view(" ".join(item.get("views") or [])),
        "furniture": normalize_furniture(item.get("furniture_status"), item.get("property_furnitures")),
        "legal_status": "available" if item.get("available_for_sale_status") == "AVAILABLE" else None,
        "is_verified": 1 if _has_tag(item, "TCA_DOCQUYEN") else 0,
    }
    record["quality_flags"] = quality_flags(record, config)
    record["quality_flags"].append("structured_onehousing")
    if item.get("classify"):
        record["quality_flags"].append(f"classify_{text_key(item.get('classify'))}")
    record["dedupe_key"] = f"{record['source']}:{record['external_id'] or record['source_url']}"
    return record


def _onehousing_title(item: dict[str, Any], property_type_label: str, block: str, sector: str, project: str) -> str:
    bedrooms = compact_spaces(item.get("number_of_bedrooms_displays"))
    parts = []
    if property_type_label == "Chung cư":
        parts.append(f"Căn {bedrooms}" if bedrooms else "Căn hộ")
        if block:
            parts.append(f"tòa {block}")
    else:
        parts.append(property_type_label or "Bất động sản")
        view = _first_text(item.get("views"))
        if view:
            parts.append(f"hướng/view {view}")
    if sector:
        parts.append(sector)
    if project:
        parts.append(project)
    return compact_spaces(" - ".join(parts))


def _onehousing_property_type(item: dict[str, Any], default: str | None) -> str:
    label = text_key(_first_text(item.get("property_type")))
    if "shophouse" in label:
        return "shophouse"
    if "biet thu" in label:
        return "villa"
    if "lien ke" in label or "nha lien ke" in label:
        return "townhouse"
    if "chung cu" in label or item.get("property_group") == "HIGH_RISE":
        return "apartment"
    return default or "other"


def _onehousing_source_url(page_url: str | None, title: str, inventory_code: str) -> str | None:
    if not inventory_code:
        return page_url
    slug = re.sub(r"[^A-Za-z0-9]+", "-", text_key(title)).strip("-")
    return f"https://onehousing.vn/bds/{slug}.{inventory_code}"


def _onehousing_datetime(value: Any) -> str | None:
    number = _numeric(value)
    if number is None:
        return None
    if number > 10_000_000_000:
        number = number / 1000
    try:
        return datetime.fromtimestamp(number, UTC).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _has_tag(item: dict[str, Any], code: str) -> bool:
    for tag in item.get("tags") or []:
        if compact_spaces(tag.get("code")) == code:
            return True
    return False


def _join_nonempty(*values: Any) -> str | None:
    text = ", ".join(compact_spaces(value) for value in values if compact_spaces(value))
    return text or None


def _first_value(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _first_text(value: Any) -> str:
    first = _first_value(value)
    return compact_spaces(first)


def _numeric(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    number = _numeric(value)
    return int(number) if number is not None else None


def _confirmed_page_project_slug(markdown: str, config: AppConfig, project_slug: str | None) -> str | None:
    if not project_slug:
        return None
    project = config.project_by_slug.get(project_slug)
    if not project:
        return None
    header_lines = []
    for line in markdown.splitlines()[:80]:
        stripped = line.strip()
        if stripped.startswith("Title:") or stripped.startswith("# "):
            header_lines.append(stripped)
    header = " ".join(header_lines)
    if not header:
        return None
    header_key = text_key(header)
    for alias in (project.name, *project.aliases):
        alias_key = text_key(alias)
        if alias_key and re.search(rf"(?:^| ){re.escape(alias_key)}(?: |$)", header_key):
            return project.slug
    return None


def _extract_address(context: str) -> str | None:
    match = re.search(r"(P\.|Phường|Xã|Quận|Huyện)\s+[^·]{2,80}", context, re.IGNORECASE)
    return compact_spaces(match.group(0)) if match else None


def _extract_bathrooms(context: str) -> int | None:
    match = re.search(r"(\d+)\s*(?:vs|wc|vệ sinh)", context, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _extract_floor(*values: str) -> int | None:
    text = " ".join(values)
    match = re.search(r"tầng\s*(\d+)|tang\s*(\d+)", text, re.IGNORECASE)
    if not match:
        return None
    return int(next(group for group in match.groups() if group))


def _extract_subdivision(*values: str) -> str | None:
    text = compact_spaces(" ".join(values))
    candidates = [
        "Sapphire",
        "Ruby",
        "Zenpark",
        "Pavilion",
        "Masteri",
        "Miami",
        "Sakura",
        "San Hô",
        "Sao Biển",
        "Ngọc Trai",
        "Vịnh Xanh",
        "Hải Âu",
        "Ánh Dương",
    ]
    lowered = text.lower()
    for candidate in candidates:
        if candidate.lower() in lowered:
            return candidate
    return None


def _extract_tower(*values: str) -> str | None:
    text = compact_spaces(" ".join(values))
    match = re.search(r"\b([A-Z]{1,3}\d{1,3}|S\d{1,3}|GS\d|R\d{1,2}|T\d{1,2})\b", text)
    return match.group(1) if match else None
