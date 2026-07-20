from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from src.config import AppConfig
from src.text import compact_spaces, text_key

VND_BILLION = 1_000_000_000
VND_MILLION = 1_000_000


@dataclass(frozen=True)
class ParsedPrice:
    price_total_vnd: float | None = None
    price_per_m2_vnd: float | None = None
    rent_monthly_vnd: float | None = None
    is_negotiable: bool = False
    unit: str | None = None


def parse_vietnamese_number(value: object) -> float | None:
    text = compact_spaces(value)
    match = re.search(r"\d+(?:[.,]\d+)*(?:[.,]\d+)?", text)
    if not match:
        return None
    token = match.group(0)
    if "," in token and "." in token:
        token = token.replace(".", "").replace(",", ".") if token.rfind(",") > token.rfind(".") else token.replace(",", "")
    elif "," in token:
        token = token.replace(".", "").replace(",", ".")
    elif token.count(".") > 1:
        token = token.replace(".", "")
    try:
        return float(token)
    except ValueError:
        return None


def parse_price(value: object, purpose_hint: str | None = None) -> ParsedPrice:
    text = compact_spaces(value)
    key = text_key(text)
    if not key:
        return ParsedPrice()
    if "thoa thuan" in key:
        return ParsedPrice(is_negotiable=True, unit="negotiable")
    amount = parse_vietnamese_number(text)
    if amount is None:
        return ParsedPrice()

    has_per_m2 = "m2" in key or "m²" in text.lower()
    has_month = "thang" in key or purpose_hint == "rent"
    if "ty" in key or "ti" in key:
        return (
            ParsedPrice(price_per_m2_vnd=amount * VND_BILLION, unit="billion_per_m2")
            if has_per_m2
            else ParsedPrice(price_total_vnd=amount * VND_BILLION, unit="billion")
        )
    if "trieu" in key or re.search(r"\btr\b", key):
        if has_per_m2 and not has_month:
            return ParsedPrice(price_per_m2_vnd=amount * VND_MILLION, unit="million_per_m2")
        if has_month:
            return ParsedPrice(rent_monthly_vnd=amount * VND_MILLION, unit="million_month")
        return ParsedPrice(price_total_vnd=amount * VND_MILLION, unit="million")
    if purpose_hint == "rent":
        return ParsedPrice(rent_monthly_vnd=amount, unit="vnd_month")
    return ParsedPrice(price_total_vnd=amount, unit="vnd")


def parse_area(value: object) -> float | None:
    area = parse_vietnamese_number(value)
    if area is None or area <= 0 or math.isnan(area):
        return None
    return area


def parse_int(value: object) -> int | None:
    match = re.search(r"\d+", compact_spaces(value))
    return int(match.group(0)) if match else None


def parse_bedrooms(*values: object) -> int | None:
    for value in values:
        key = text_key(value)
        if not key:
            continue
        if "studio" in key:
            return 0
        patterns = [
            r"(\d+)\s*(?:pn|phong ngu|ngu|bed)",
            r"can\s+(\d+)\s*n\b",
            r"\b(\d+)\s*n(?=\d|[^a-z0-9]|$)",
            r"\b(\d+)n\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, key)
            if match:
                return int(match.group(1))
    return None


def infer_project_slug(config: AppConfig, *values: object, default: str | None = None) -> str | None:
    haystack = text_key(" ".join(compact_spaces(value) for value in values))
    alias_pairs: list[tuple[str, str]] = []
    for project in config.projects:
        options = (project.name, project.slug, *project.aliases)
        alias_pairs.extend((text_key(option), project.slug) for option in options if text_key(option))
    for alias, slug in sorted(alias_pairs, key=lambda item: len(item[0]), reverse=True):
        if re.search(rf"(?:^| ){re.escape(alias)}(?: |$)", haystack):
            return slug
    return default


def infer_property_type(*values: object, default: str | None = None) -> str:
    key = text_key(" ".join(compact_spaces(value) for value in values))
    if any(term in key for term in ("shophouse", "nha pho thuong mai")):
        return "shophouse"
    if any(term in key for term in ("biet thu", "song lap", "don lap", "tu lap")):
        return "villa"
    if any(term in key for term in ("lien ke", "nha pho", "thap tang")):
        return "townhouse"
    if any(term in key for term in ("can ho", "chung cu", "studio", "apartment")):
        return "apartment"
    if any(term in key for term in ("nha rieng", "nha mat pho", "nha hem")):
        return "house"
    return default or "other"


def normalize_view(*values: object) -> str | None:
    key = text_key(" ".join(compact_spaces(value) for value in values))
    if not key:
        return None
    if _contains_term(key, "bien", "song", "water") or any(
        term in key for term in ("view ho", "huong ho", "mat ho", "ven ho", "ho dieu hoa", "ho ngoc trai")
    ):
        return "water"
    if _contains_term(key, "vinuni"):
        return "vinuni"
    if _contains_term(key, "noi khu", "cong vien", "vuon", "be boi"):
        return "internal"
    if any(term in key for term in ("view city", "view thanh pho", "huong city", "huong thanh pho")):
        return "city"
    return None


def _contains_term(key: str, *terms: str) -> bool:
    return any(re.search(rf"(?:^| ){re.escape(term)}(?: |$)", key) for term in terms)


def normalize_furniture(*values: object) -> str | None:
    key = text_key(" ".join(compact_spaces(value) for value in values))
    if not key:
        return None
    if any(term in key for term in ("full", "day du", "du do", "cao cap", "noi that dep")):
        return "full"
    if any(term in key for term in ("co ban", "basic")):
        return "basic"
    if any(term in key for term in ("trong", "ban giao tho", "khong noi that")):
        return "empty"
    return None


def quality_flags(record: dict[str, Any], config: AppConfig) -> list[str]:
    quality = config.raw.get("quality", {})
    flags: list[str] = []
    if record.get("purpose") == "sale":
        ppm = record.get("price_per_m2_vnd")
        if ppm is None and record.get("price_total_vnd") and record.get("area_m2"):
            ppm = record["price_total_vnd"] / record["area_m2"]
        if ppm is None:
            flags.append("missing_sale_price")
        elif ppm < quality.get("sale_price_per_m2_min_vnd", 0) or ppm > quality.get("sale_price_per_m2_max_vnd", float("inf")):
            flags.append("sale_price_outlier")
    if record.get("purpose") == "rent":
        rent = record.get("rent_monthly_vnd")
        if rent is None:
            flags.append("missing_rent_price")
        elif rent < quality.get("rent_monthly_min_vnd", 0) or rent > quality.get("rent_monthly_max_vnd", float("inf")):
            flags.append("rent_outlier")
    if not record.get("area_m2"):
        flags.append("missing_area")
    return flags
