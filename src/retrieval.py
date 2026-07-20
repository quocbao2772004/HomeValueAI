from __future__ import annotations

import math
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import AppConfig, ProjectConfig
from src.text import compact_spaces, text_key
from src.valuation import load_market_frame, price_snapshot_references

DEFAULT_LIMIT = 3
SUBDIVISION_CANDIDATES = [
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
    "Thời Đại",
    "Phố Biển",
]


def missing_info_retrieval(
    message: str,
    fields: dict[str, Any],
    missing: list[str],
    config: AppConfig,
    db_path: str | Path,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Retrieve nearby market context to help the chatbot ask better follow-ups."""
    frame = _safe_market_frame(db_path)
    purpose = str(fields.get("purpose") or "sale")
    property_type = fields.get("property_type")
    bedrooms = _int_optional(fields.get("bedrooms"))
    area_m2 = _float_optional(fields.get("area_m2"))
    project_slug = _project_slug(fields.get("project"), config)

    scoped = _scope_frame(frame, purpose, property_type, bedrooms)
    if project_slug:
        project_scoped = scoped[scoped["project_slug"] == project_slug]
        if not project_scoped.empty:
            scoped = project_scoped

    nearest_projects = _nearest_projects(
        message=message,
        frame=_scope_frame(frame, purpose, property_type, bedrooms),
        config=config,
        project_slug=project_slug,
        purpose=purpose,
        property_type=property_type,
        area_m2=area_m2,
        limit=limit,
    )
    target_projects = [project_slug] if project_slug else [item["slug"] for item in nearest_projects]
    nearby_listings = _nearby_listings(
        frame=_scope_frame(frame, purpose, property_type, bedrooms),
        target_projects=target_projects,
        purpose=purpose,
        area_m2=area_m2,
        limit=limit,
    )
    area_hint = _area_hint(scoped)
    location_hints = _location_hints(scoped, limit)
    snapshot_hints = _snapshot_hints(config, target_projects, purpose, property_type, db_path, limit=limit)
    hint_text = _compose_hint_text(
        missing=missing,
        nearest_projects=nearest_projects,
        nearby_listings=nearby_listings,
        area_hint=area_hint,
        location_hints=location_hints,
        snapshot_hints=snapshot_hints,
        purpose=purpose,
    )
    return {
        "nearest_projects": nearest_projects,
        "nearby_listings": nearby_listings,
        "area_hint": area_hint,
        "location_hints": location_hints,
        "snapshot_hints": snapshot_hints,
        "hint_text": hint_text,
    }


def _safe_market_frame(db_path: str | Path) -> pd.DataFrame:
    try:
        frame = load_market_frame(db_path)
    except Exception:  # noqa: BLE001
        return pd.DataFrame()
    if frame.empty:
        return frame
    frame = frame.copy()
    if "quality_flags" in frame:
        frame = frame[frame["quality_flags"].apply(lambda flags: not any("outlier" in flag for flag in flags))]
    return frame


def _scope_frame(
    frame: pd.DataFrame,
    purpose: str,
    property_type: str | None,
    bedrooms: int | None,
) -> pd.DataFrame:
    if frame.empty:
        return frame
    df = frame[frame["purpose"] == purpose].copy()
    metric = "rent_monthly_vnd" if purpose == "rent" else "price_per_m2_vnd"
    if metric in df:
        df = df[pd.notna(df[metric])]
    if "area_m2" in df:
        df = df[pd.notna(df["area_m2"])]
    if property_type:
        exact_type = df[df["property_type"] == property_type]
        if not exact_type.empty:
            df = exact_type
    if bedrooms is not None and "bedrooms" in df:
        exact_bedrooms = df[df["bedrooms"] == bedrooms]
        if not exact_bedrooms.empty:
            df = exact_bedrooms
    return df


def _nearest_projects(
    message: str,
    frame: pd.DataFrame,
    config: AppConfig,
    project_slug: str | None,
    purpose: str,
    property_type: str | None,
    area_m2: float | None,
    limit: int,
) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    rows = []
    total_rows = max(len(frame), 1)
    message_key = text_key(message)
    projects = (
        [config.project_by_slug[project_slug]]
        if project_slug and project_slug in config.project_by_slug
        else config.projects
    )
    for project in projects:
        df = frame[frame["project_slug"] == project.slug]
        if df.empty:
            continue
        metric = "rent_monthly_vnd" if purpose == "rent" else "price_per_m2_vnd"
        text_score = _project_text_score(message_key, project)
        scope_boost = 1.0 if project_slug and project.slug == project_slug else 0.0
        sample_score = min(len(df) / total_rows, 1.0)
        area_score = _project_area_score(df, area_m2)
        score = scope_boost + text_score * 1.5 + sample_score * 0.7 + area_score * 0.8
        rows.append(
            {
                "slug": project.slug,
                "name": project.name,
                "sample_size": int(len(df)),
                "property_type": property_type,
                "median_area_m2": _round_optional(_series_median(df, "area_m2"), 1),
                "area_range_text": _area_range_text(df),
                "median_metric_vnd": _round_optional(_series_median(df, metric), 0),
                "median_metric_text": _metric_text(_series_median(df, metric), purpose),
                "score": round(score, 3),
            }
        )
    rows.sort(key=lambda item: (item["score"], item["sample_size"]), reverse=True)
    return rows[:limit]


def _nearby_listings(
    frame: pd.DataFrame,
    target_projects: list[str],
    purpose: str,
    area_m2: float | None,
    limit: int,
) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    df = frame.copy()
    if target_projects:
        same_projects = df[df["project_slug"].isin(target_projects)]
        if not same_projects.empty:
            df = same_projects
    if df.empty:
        return []
    df["retrieval_score"] = df.apply(lambda row: _listing_score(row, area_m2, target_projects), axis=1)
    if "observed_at" in df:
        df["observed_dt"] = pd.to_datetime(df["observed_at"], errors="coerce", utc=True)
        df = df.sort_values(["retrieval_score", "observed_dt"], ascending=[False, False])
    else:
        df = df.sort_values(["retrieval_score"], ascending=[False])
    listings = []
    for _, row in df.head(limit).iterrows():
        listings.append(
            {
                "title": _clean_optional(row.get("title")),
                "project": _clean_optional(row.get("project_name")),
                "project_slug": _clean_optional(row.get("project_slug")),
                "property_type": _clean_optional(row.get("property_type")),
                "purpose": _clean_optional(row.get("purpose")),
                "area_m2": _round_optional(row.get("area_m2"), 1),
                "bedrooms": _int_optional(row.get("bedrooms")),
                "price_text": _listing_price_text(row, purpose),
                "observed_at": _clean_optional(row.get("observed_at")),
                "source_url": _clean_optional(row.get("source_url")),
                "score": _round_optional(row.get("retrieval_score"), 3),
            }
        )
    return listings


def _area_hint(frame: pd.DataFrame) -> dict[str, Any] | None:
    if frame.empty or "area_m2" not in frame:
        return None
    values = pd.to_numeric(frame["area_m2"], errors="coerce").dropna()
    if values.empty:
        return None
    p25, median, p75 = values.quantile([0.25, 0.5, 0.75]).tolist()
    return {
        "sample_size": int(len(values)),
        "p25_m2": round(float(p25), 1),
        "median_m2": round(float(median), 1),
        "p75_m2": round(float(p75), 1),
        "range_text": f"{round(float(p25), 1):g}-{round(float(p75), 1):g} m2",
        "median_text": f"{round(float(median), 1):g} m2",
    }


def _location_hints(frame: pd.DataFrame, limit: int) -> dict[str, Any] | None:
    if frame.empty:
        return None
    subdivisions = _top_location_values(
        (_row_subdivision(row) for _, row in frame.iterrows()),
        item_key="name",
        limit=limit,
    )
    towers = _top_location_values(
        (_row_tower(row) for _, row in frame.iterrows()),
        item_key="code",
        limit=limit,
        prefer_detailed=True,
    )
    if not subdivisions and not towers:
        return None
    pieces: list[str] = []
    if subdivisions:
        pieces.append("Phân khu đang có dữ liệu: " + ", ".join(item["name"] for item in subdivisions[:4]))
    if towers:
        pieces.append("Mã tòa hay gặp: " + ", ".join(item["code"] for item in towers[:6]))
    return {
        "subdivisions": subdivisions,
        "towers": towers,
        "text": "; ".join(pieces),
    }


def _top_location_values(
    values: Any,
    item_key: str,
    limit: int,
    prefer_detailed: bool = False,
) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for value in values:
        if not value:
            continue
        counts[value] = counts.get(value, 0) + 1
    rows = sorted(counts.items(), key=lambda item: (item[1], item[0]), reverse=True)
    if prefer_detailed:
        detailed = [item for item in rows if "." in item[0]]
        broad = [item for item in rows if "." not in item[0]]
        rows = [*detailed, *broad]
    return [{item_key: value, "sample_size": count} for value, count in rows[:limit]]


def _row_subdivision(row: pd.Series) -> str | None:
    current = _clean_location_value(row.get("subdivision"))
    return parse_subdivision(current, row.get("title"), row.get("address")) or current


def _row_tower(row: pd.Series) -> str | None:
    current = parse_tower_code(_clean_location_value(row.get("tower")))
    parsed = parse_tower_code(row.get("title"), row.get("address"), row.get("source_url"))
    if parsed and (not current or ("." in parsed and "." not in current)):
        return parsed
    return current or parsed


def parse_subdivision(*values: object) -> str | None:
    key = text_key(" ".join(compact_spaces(value) for value in values if value))
    if not key:
        return None
    for candidate in SUBDIVISION_CANDIDATES:
        if text_key(candidate) in key:
            return candidate
    return None


def parse_tower_code(*values: object) -> str | None:
    text = " ".join(compact_spaces(value) for value in values if value)
    match = re.search(r"\b([A-Z]{1,3}\d{1,3}(?:\.\d{1,3})?|S\d{1,3}|GS\d|R\d{1,2}|T\d{1,2})\b", text, re.IGNORECASE)
    return match.group(1).upper() if match else None
def _snapshot_hints(
    config: AppConfig,
    target_projects: list[str],
    purpose: str,
    property_type: str | None,
    db_path: str | Path,
    limit: int,
) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    for project_slug in target_projects[:limit]:
        if not project_slug:
            continue
        for item in price_snapshot_references(config, project_slug, purpose, property_type, limit=3, db_path=db_path):
            if property_type and item.property_type != property_type:
                continue
            payload = item.model_dump()
            payload["range_text"] = _snapshot_range_text(payload)
            hints.append(payload)
            break
    return hints[:limit]


def _compose_hint_text(
    missing: list[str],
    nearest_projects: list[dict[str, Any]],
    nearby_listings: list[dict[str, Any]],
    area_hint: dict[str, Any] | None,
    location_hints: dict[str, Any] | None,
    snapshot_hints: list[dict[str, Any]],
    purpose: str,
) -> str:
    parts: list[str] = []
    if nearest_projects:
        project_bits = []
        for project in nearest_projects:
            bit = f"{project['name']} ({project['sample_size']} mẫu"
            if project.get("area_range_text"):
                bit += f", diện tích hay gặp {project['area_range_text']}"
            if project.get("median_metric_text"):
                bit += f", median {project['median_metric_text']}"
            bit += ")"
            project_bits.append(bit)
        parts.append("Dữ liệu gần nhất đang có: " + "; ".join(project_bits) + ".")
    if "area_m2" in missing and area_hint:
        parts.append(
            f"Với bộ lọc hiện tại, diện tích thường nằm quanh {area_hint['range_text']}, median {area_hint['median_text']}."
        )
    if location_hints and location_hints.get("text"):
        parts.append(str(location_hints["text"]) + ".")
    if nearby_listings:
        examples = []
        for item in nearby_listings[:2]:
            description = _listing_description(item)
            if description:
                examples.append(description)
        if examples:
            parts.append("Một vài mẫu gần nhất: " + "; ".join(examples) + ".")
    if parts:
        ask = "Bạn xác nhận giúp mình "
        ask += "dự án và diện tích cụ thể" if len(missing) > 1 else _missing_phrase(missing[0])
        ask += " để mình chốt định giá sát hơn."
        parts.append(ask)
    return " ".join(parts)


def _listing_description(item: dict[str, Any]) -> str:
    bits = []
    if item.get("project"):
        bits.append(str(item["project"]))
    if item.get("area_m2"):
        bits.append(f"{item['area_m2']:g} m2")
    if item.get("bedrooms") is not None:
        bits.append(f"{item['bedrooms']}PN")
    if item.get("price_text"):
        bits.append(str(item["price_text"]))
    return " ".join(bits)


def _listing_score(row: pd.Series, area_m2: float | None, target_projects: list[str]) -> float:
    score = 0.0
    if target_projects and row.get("project_slug") in target_projects:
        score += 0.35
    if area_m2 is not None and _float_optional(row.get("area_m2")):
        row_area = float(row["area_m2"])
        score += max(0.0, 1 - abs(row_area - area_m2) / max(area_m2, 1)) * 0.55
    else:
        score += 0.25
    return score


def _project_area_score(df: pd.DataFrame, area_m2: float | None) -> float:
    if area_m2 is None:
        return 0.0
    median = _series_median(df, "area_m2")
    if median is None:
        return 0.0
    return max(0.0, 1 - abs(median - area_m2) / max(area_m2, 1))


def _project_text_score(message_key: str, project: ProjectConfig) -> float:
    if not message_key:
        return 0.0
    names = [project.slug, project.name, *project.aliases]
    scores = []
    for name in names:
        key = text_key(name)
        if key and key in message_key:
            scores.append(1.0)
        elif key:
            ratio = SequenceMatcher(None, message_key, key).ratio()
            message_tokens = set(message_key.split())
            key_tokens = set(key.split())
            overlap = len(message_tokens & key_tokens) / len(key_tokens) if key_tokens else 0.0
            scores.append(max(ratio if ratio >= 0.55 else 0.0, overlap))
    return max(scores or [0.0])


def _project_slug(value: Any, config: AppConfig) -> str | None:
    if not value:
        return None
    text = str(value)
    if text in config.project_by_slug:
        return text
    normalized = text_key(text)
    for project in config.projects:
        names = [project.slug, project.name, *project.aliases]
        if any(text_key(name) == normalized for name in names):
            return project.slug
    return None


def _series_median(df: pd.DataFrame, column: str) -> float | None:
    if column not in df:
        return None
    values = pd.to_numeric(df[column], errors="coerce").dropna()
    if values.empty:
        return None
    return float(values.median())


def _area_range_text(df: pd.DataFrame) -> str | None:
    if "area_m2" not in df:
        return None
    values = pd.to_numeric(df["area_m2"], errors="coerce").dropna()
    if values.empty:
        return None
    p25, p75 = values.quantile([0.25, 0.75]).tolist()
    return f"{round(float(p25), 1):g}-{round(float(p75), 1):g} m2"


def _metric_text(value: float | None, purpose: str) -> str:
    if value is None:
        return ""
    if purpose == "rent":
        return f"{_format_vnd(value)}/tháng"
    return f"{_format_vnd(value)}/m2"


def _listing_price_text(row: pd.Series, purpose: str) -> str:
    if purpose == "rent":
        value = _float_optional(row.get("rent_monthly_vnd"))
        return f"{_format_vnd(value)}/tháng" if value else ""
    total = _float_optional(row.get("price_total_vnd"))
    ppm = _float_optional(row.get("price_per_m2_vnd"))
    if total and ppm:
        return f"{_format_vnd(total)} ({_format_vnd(ppm)}/m2)"
    if total:
        return _format_vnd(total)
    if ppm:
        return f"{_format_vnd(ppm)}/m2"
    return ""


def _snapshot_range_text(item: dict[str, Any]) -> str:
    if item.get("price_min_vnd") and item.get("price_max_vnd"):
        return f"{_format_vnd(item['price_min_vnd'])} - {_format_vnd(item['price_max_vnd'])}"
    if item.get("price_per_m2_min_vnd") and item.get("price_per_m2_max_vnd"):
        return f"{_format_vnd(item['price_per_m2_min_vnd'])}/m2 - {_format_vnd(item['price_per_m2_max_vnd'])}/m2"
    return ""


def _format_vnd(value: float | int | None) -> str:
    if value is None:
        return ""
    value = float(value)
    if math.isnan(value):
        return ""
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f} tỷ"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f} triệu"
    return f"{value:,.0f} VND"


def _missing_phrase(value: str) -> str:
    return {
        "project": "dự án/khu đô thị",
        "area_m2": "diện tích m2",
    }.get(value, value)


def _float_optional(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def _int_optional(value: Any) -> int | None:
    number = _float_optional(value)
    return int(number) if number is not None else None


def _round_optional(value: Any, digits: int) -> float | None:
    number = _float_optional(value)
    return round(number, digits) if number is not None else None


def _clean_optional(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = compact_spaces(str(value))
    return text or None


def _clean_location_value(value: Any) -> str | None:
    text = _clean_optional(value)
    if not text or text_key(text) in {"unknown", "nan", "na", "none", "chua ro"}:
        return None
    return text
