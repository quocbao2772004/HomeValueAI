from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from math import atan2, cos, radians, sin, sqrt
from typing import Any
from urllib.parse import quote_plus

import requests

from src.config import AppConfig
from src.llm import generate_answer
from src.normalization import infer_project_slug
from src.schemas import (
    AmenityAdviceRequest,
    AmenityAdviceResponse,
    AmenityCategoryResult,
    AmenityPlace,
)
from src.text import compact_spaces, text_key

AMENITY_CATEGORIES = (
    {
        "key": "commute",
        "label": "Giao thông",
        "terms": "trạm xe buýt ga metro bãi gửi xe",
        "nearby_query": "trạm xe buýt",
        "renter_note": "Hợp với người đi làm hằng ngày; nên kiểm tra quãng đường tới văn phòng và giờ cao điểm.",
    },
    {
        "key": "grocery",
        "label": "Siêu thị",
        "terms": "siêu thị cửa hàng tiện lợi chợ",
        "nearby_query": "siêu thị",
        "renter_note": "Quan trọng cho sinh hoạt thường ngày; ưu tiên căn có nhu yếu phẩm trong bán kính đi bộ hoặc đi xe ngắn.",
    },
    {
        "key": "school",
        "label": "Trường học",
        "terms": "trường học mầm non tiểu học",
        "nearby_query": "trường học",
        "renter_note": "Hữu ích với gia đình có trẻ nhỏ; nên kiểm tra tuyến đưa đón và thời gian di chuyển thực tế.",
    },
    {
        "key": "health",
        "label": "Y tế",
        "terms": "bệnh viện phòng khám nhà thuốc",
        "nearby_query": "bệnh viện",
        "renter_note": "Là điểm cộng về an toàn, đặc biệt với gia đình có trẻ nhỏ hoặc người lớn tuổi.",
    },
    {
        "key": "shopping",
        "label": "Ăn uống mua sắm",
        "terms": "trung tâm thương mại nhà hàng cafe",
        "nearby_query": "trung tâm thương mại",
        "renter_note": "Tăng độ tiện lợi và trải nghiệm sống, nhưng cũng nên để ý tiếng ồn nếu căn quá sát khu đông người.",
    },
    {
        "key": "green",
        "label": "Công viên",
        "terms": "công viên hồ khu vui chơi",
        "nearby_query": "công viên",
        "renter_note": "Là lợi thế cho căn thuê dài hạn, nhất là nhóm khách cần không gian đi bộ, thể thao hoặc trẻ em.",
    },
)

PLACES_API_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
SERPAPI_SEARCH_URL = "https://serpapi.com/search.json"


def build_amenity_advice(
    request: AmenityAdviceRequest,
    config: AppConfig,
    *,
    include_llm: bool = True,
    message: str | None = None,
) -> AmenityAdviceResponse:
    project = _resolve_project(request.project, config)
    location_label = _location_label(request, project.name, project.district_hint)
    serpapi_key = _serpapi_api_key()
    if serpapi_key:
        categories, source = _serpapi_categories(request, location_label, serpapi_key)
        response = AmenityAdviceResponse(
            generated_at=datetime.now(UTC).isoformat(),
            project=project.name,
            location_label=location_label,
            base_query=location_label,
            base_map_url=_maps_search_url(location_label),
            base_embed_url=_maps_embed_url(location_label),
            source=source,
            categories=categories,
            advisory_notes=_advisory_notes(categories, source),
            llm_advice=None,
        )
        if include_llm:
            response.llm_advice = generate_answer(
                "amenity",
                message or f"Tư vấn tiện ích quanh {location_label}",
                amenity_context(response),
                fallback_key="amenity",
            )
        return response

    api_key = _google_maps_api_key()
    categories = [
        _category_result(category, location_label, api_key, request.max_places_per_category)
        for category in AMENITY_CATEGORIES
    ]
    source = _source_from_categories(categories, api_key)
    response = AmenityAdviceResponse(
        generated_at=datetime.now(UTC).isoformat(),
        project=project.name,
        location_label=location_label,
        base_query=location_label,
        base_map_url=_maps_search_url(location_label),
        base_embed_url=_maps_embed_url(location_label),
        source=source,
        categories=categories,
        advisory_notes=_advisory_notes(categories, source),
        llm_advice=None,
    )
    if include_llm:
        response.llm_advice = generate_answer(
            "amenity",
            message or f"Tư vấn tiện ích quanh {location_label}",
            amenity_context(response),
            fallback_key="amenity",
        )
    return response


def amenity_context(response: AmenityAdviceResponse) -> dict[str, Any]:
    return {
        "project": response.project,
        "location_label": response.location_label,
        "source": response.source,
        "source_label": _source_label(response.source),
        "base_map_url": response.base_map_url,
        "categories": [category.model_dump() for category in response.categories],
        "places_found": sum(len(category.places) for category in response.categories),
        "category_count": len(response.categories),
        "advisory_notes": response.advisory_notes,
        "advisory_text": " ".join(response.advisory_notes),
        "advisory_text_en": _advisory_text_en(response),
        "top_category_text": _top_category_text(response.categories),
    }


def _advisory_text_en(response: AmenityAdviceResponse) -> str:
    found = sum(len(category.places) for category in response.categories)
    if found:
        strongest = max(response.categories, key=lambda category: len(category.places))
        return (
            f"I found {found} nearby place result(s). The strongest amenity group is {strongest.label}; "
            "open the map links to verify real distance and travel time."
        )
    return (
        "Map search links are ready for the main amenity groups. "
        "Open each group to verify real distance and travel time."
    )


def _resolve_project(slug_or_name: str, config: AppConfig):
    slug = infer_project_slug(config, slug_or_name, default=slug_or_name)
    project = config.project_by_slug.get(str(slug or ""))
    if not project:
        raise ValueError("Không nhận diện được project để tìm tiện ích.")
    return project


def _location_label(request: AmenityAdviceRequest, project_name: str, district_hint: str | None) -> str:
    parts = [request.address, request.tower, request.subdivision, project_name, district_hint, "Hà Nội"]
    cleaned: list[str] = []
    seen: set[str] = set()
    for part in parts:
        text = _clean_location_part(part)
        key = text_key(text)
        if text and key not in seen:
            cleaned.append(text)
            seen.add(key)
    return ", ".join(cleaned)


def _clean_location_part(value: Any) -> str:
    text = compact_spaces(value)
    if not text:
        return ""
    text = re.sub(r"\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\]\([^)]*", " ", text)
    text = re.sub(r"\bĐăng\s+\d+\s+(phút|giờ|ngày|tuần|tháng|năm)\b.*", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bDang\s+\d+\s+(phut|gio|ngay|tuan|thang|nam)\b.*", " ", text, flags=re.IGNORECASE)
    chunks = []
    for chunk in re.split(r"[,|;]+", text):
        clean = compact_spaces(chunk).strip(" -_[]()")
        key = text_key(clean)
        if not clean or any(term in key for term in ("batdongsan", "http", "www", "dang tin", "dang ban")):
            continue
        chunks.append(clean)
    return ", ".join(chunks[:3])


def _category_result(
    category: dict[str, str],
    base_query: str,
    api_key: str | None,
    max_places: int,
) -> AmenityCategoryResult:
    query = f"{category['terms']} gần {base_query}"
    places: list[AmenityPlace] = []
    provider_status = None
    provider_error = None
    if api_key and max_places > 0:
        places, provider_status, provider_error = _google_places(query, api_key, max_places)
    return AmenityCategoryResult(
        key=category["key"],
        label=category["label"],
        query=query,
        map_url=_maps_search_url(query),
        embed_url=_maps_embed_url(query),
        places=places,
        renter_note=category["renter_note"],
        provider_status=provider_status,
        provider_error=provider_error,
    )


def _serpapi_categories(
    request: AmenityAdviceRequest,
    location_label: str,
    api_key: str,
) -> tuple[list[AmenityCategoryResult], str]:
    building, status, error = _serpapi_place_location(location_label, api_key)
    if not building:
        categories = [
            AmenityCategoryResult(
                key=category["key"],
                label=category["label"],
                query=f"{_nearby_query(category)} gần {location_label}",
                map_url=_maps_search_url(f"{_nearby_query(category)} gần {location_label}"),
                embed_url=_maps_embed_url(f"{_nearby_query(category)} gần {location_label}"),
                places=[],
                renter_note=category["renter_note"],
                provider_status=status,
                provider_error=error,
            )
            for category in AMENITY_CATEGORIES
        ]
        return categories, "serpapi_error"

    categories = [
        _serpapi_category_result(category, building, api_key, request.max_places_per_category)
        for category in AMENITY_CATEGORIES
    ]
    statuses = {category.provider_status for category in categories if category.provider_status}
    if statuses and not statuses.issubset({"OK", "ZERO_RESULTS"}):
        return categories, "serpapi_error"
    return categories, "serpapi_google_maps"


def _serpapi_place_location(query: str, api_key: str) -> tuple[dict[str, Any] | None, str | None, str | None]:
    payload, status, error = _serpapi_search(
        {
            "engine": "google_maps",
            "type": "search",
            "q": query,
            "hl": "vi",
            "gl": "vn",
        },
        api_key,
    )
    if not payload:
        return None, status, error
    if status and status not in {"OK", "ZERO_RESULTS"}:
        return None, status, error
    place = payload.get("place_results")
    if not place:
        local_results = payload.get("local_results") or []
        place = local_results[0] if local_results else None
    if not place:
        return None, "ZERO_RESULTS", f"Không tìm thấy vị trí: {query}"
    gps = place.get("gps_coordinates") or {}
    lat = _optional_float(gps.get("latitude"))
    lng = _optional_float(gps.get("longitude"))
    if lat is None or lng is None:
        return None, "NO_COORDINATES", f"Không có tọa độ cho vị trí: {query}"
    return {
        "name": place.get("title") or query,
        "address": place.get("address"),
        "lat": lat,
        "lng": lng,
    }, "OK", None


def resolve_location_coordinates(query: str) -> dict[str, Any] | None:
    """Resolve a human location label to coordinates using configured map providers."""
    label = str(query or "").strip()
    if not label:
        return None

    serpapi_key = _serpapi_api_key()
    if serpapi_key:
        place, status, error = _serpapi_place_location(label, serpapi_key)
        if place:
            return {**place, "provider": "serpapi_google_maps", "provider_status": status}
        if status not in {"REQUEST_DENIED", "REQUEST_ERROR"} and not error:
            return None

    google_key = _google_maps_api_key()
    if google_key:
        place, status, _error = _google_place_location(label, google_key)
        if place:
            return {**place, "provider": "google_places", "provider_status": status}
    return None


def _serpapi_category_result(
    category: dict[str, str],
    building: dict[str, Any],
    api_key: str,
    limit: int,
) -> AmenityCategoryResult:
    query = _nearby_query(category)
    payload, status, error = _serpapi_search(
        {
            "engine": "google_maps",
            "type": "search",
            "q": query,
            "ll": f"@{building['lat']},{building['lng']},15z",
            "hl": "vi",
            "gl": "vn",
        },
        api_key,
    )
    places: list[AmenityPlace] = []
    if payload:
        for item in (payload.get("local_results") or [])[: max(limit * 3, limit)]:
            gps = item.get("gps_coordinates") or {}
            lat = _optional_float(gps.get("latitude"))
            lng = _optional_float(gps.get("longitude"))
            if lat is None or lng is None:
                continue
            distance_m = round(_haversine_distance_m(building["lat"], building["lng"], lat, lng))
            name = str(item.get("title") or "").strip()
            if not name:
                continue
            address = item.get("address")
            places.append(
                AmenityPlace(
                    name=name,
                    address=address,
                    rating=_optional_float(item.get("rating")),
                    user_ratings_total=_optional_int(item.get("reviews")),
                    distance_m=distance_m,
                    distance_km=round(distance_m / 1000, 2),
                    maps_url=_maps_search_url(", ".join(part for part in [name, address] if part) or name),
                )
            )
    places.sort(key=lambda place: place.distance_m if place.distance_m is not None else 10**9)
    places = places[:limit]
    return AmenityCategoryResult(
        key=category["key"],
        label=category["label"],
        query=f"{query} gần {building['name']}",
        map_url=_maps_search_url(f"{query} gần {building['name']}"),
        embed_url=_maps_embed_url(f"{query} gần {building['name']}"),
        places=places,
        renter_note=category["renter_note"],
        provider_status=status or ("OK" if places else "ZERO_RESULTS"),
        provider_error=error,
    )


def _serpapi_search(params: dict[str, Any], api_key: str) -> tuple[dict[str, Any] | None, str | None, str | None]:
    timeout = _float_env("SERPAPI_TIMEOUT_SECONDS", 10.0)
    try:
        response = requests.get(SERPAPI_SEARCH_URL, params={**params, "api_key": api_key}, timeout=timeout)
        try:
            payload = response.json()
        except ValueError:
            payload = {}
    except Exception:  # noqa: BLE001
        return None, "REQUEST_ERROR", "Không gọi được SerpApi Google Maps."
    if not response.ok:
        error = str(payload.get("error") or f"HTTP {response.status_code}") if isinstance(payload, dict) else f"HTTP {response.status_code}"
        if response.status_code == 429:
            return payload, "QUOTA_EXCEEDED", error
        if response.status_code in {401, 403}:
            return payload, "REQUEST_DENIED", error
        return payload, "REQUEST_ERROR", error
    if payload.get("error"):
        return payload, "REQUEST_DENIED", str(payload.get("error"))
    return payload, "OK", None


def _nearby_query(category: dict[str, str]) -> str:
    return str(category.get("nearby_query") or category["terms"])


def _google_places(query: str, api_key: str, limit: int) -> tuple[list[AmenityPlace], str | None, str | None]:
    timeout = _float_env("GOOGLE_PLACES_TIMEOUT_SECONDS", 3.0)
    try:
        response = requests.get(
            PLACES_API_URL,
            params={"query": query, "key": api_key, "language": "vi", "region": "vn"},
            timeout=timeout,
        )
        payload = response.json() if response.ok else {}
    except Exception:  # noqa: BLE001
        return [], "REQUEST_ERROR", "Không gọi được Google Places API."

    provider_status = str(payload.get("status") or "")
    provider_error = payload.get("error_message")
    if provider_status and provider_status not in {"OK", "ZERO_RESULTS"}:
        return [], provider_status, str(provider_error or "")

    places = []
    for item in payload.get("results", [])[:limit]:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        address = item.get("formatted_address")
        maps_query = ", ".join(part for part in [name, address] if part)
        places.append(
            AmenityPlace(
                name=name,
                address=address,
                rating=_optional_float(item.get("rating")),
                user_ratings_total=_optional_int(item.get("user_ratings_total")),
                maps_url=_maps_search_url(maps_query or name),
            )
        )
    return places, provider_status or None, str(provider_error) if provider_error else None


def _google_place_location(query: str, api_key: str) -> tuple[dict[str, Any] | None, str | None, str | None]:
    timeout = _float_env("GOOGLE_PLACES_TIMEOUT_SECONDS", 3.0)
    try:
        response = requests.get(
            PLACES_API_URL,
            params={"query": query, "key": api_key, "language": "vi", "region": "vn"},
            timeout=timeout,
        )
        payload = response.json() if response.ok else {}
    except Exception:  # noqa: BLE001
        return None, "REQUEST_ERROR", "Không gọi được Google Places API."

    provider_status = str(payload.get("status") or "")
    provider_error = payload.get("error_message")
    if provider_status and provider_status not in {"OK", "ZERO_RESULTS"}:
        return None, provider_status, str(provider_error or "")

    for item in payload.get("results", []):
        location = ((item.get("geometry") or {}).get("location") or {}) if isinstance(item, dict) else {}
        lat = _optional_float(location.get("lat"))
        lng = _optional_float(location.get("lng"))
        name = str(item.get("name") or "").strip()
        if lat is None or lng is None or not name:
            continue
        return {
            "name": name,
            "address": item.get("formatted_address"),
            "lat": lat,
            "lng": lng,
        }, provider_status or "OK", None
    return None, provider_status or "ZERO_RESULTS", "Không tìm thấy tọa độ phù hợp."


def _source_from_categories(categories: list[AmenityCategoryResult], api_key: str | None) -> str:
    if not api_key:
        return "google_maps_search"
    if any(category.places for category in categories):
        return "google_places"
    statuses = {category.provider_status for category in categories if category.provider_status}
    if statuses and not statuses.issubset({"OK", "ZERO_RESULTS"}):
        return "google_places_error"
    return "google_places"


def _advisory_notes(categories: list[AmenityCategoryResult], source: str) -> list[str]:
    found = sum(len(category.places) for category in categories)
    if found:
        strongest = max(categories, key=lambda category: len(category.places))
        return [
            f"Tìm thấy {found} điểm tiện ích trong {len(categories)} nhóm quanh vị trí này.",
            f"Nhóm có nhiều kết quả rõ nhất là {strongest.label}; nên mở map để kiểm tra khoảng cách và tuyến đi thực tế.",
            "Với căn thuê, ưu tiên giao thông, siêu thị và y tế trước; trường học/công viên là điểm cộng theo nhu cầu gia đình.",
        ]
    if source == "serpapi_error":
        status = _first_provider_status(categories)
        notes = [
            "Chưa lấy được địa điểm cụ thể quanh vị trí này, nhưng đã chuẩn bị sẵn các nhóm tìm kiếm trên bản đồ.",
            "Vẫn có thể mở từng nhóm trên bản đồ để xem kết quả thực tế, khoảng cách và thời gian di chuyển.",
        ]
        if status not in {"QUOTA_EXCEEDED", "REQUEST_DENIED", "REQUEST_ERROR"}:
            notes.append("Nên thử tên tòa/phân khu rõ hơn, ví dụ S2.05 Vinhomes Smart City hoặc The Sapphire 2 Vinhomes Smart City.")
        return notes
    if source == "google_places_error":
        status = _first_provider_status(categories)
        notes = [
            "Chưa lấy được địa điểm cụ thể quanh vị trí này, nhưng đã chuẩn bị sẵn các nhóm tìm kiếm trên bản đồ.",
            "Vẫn có thể mở từng nhóm trên bản đồ để xem kết quả thực tế, khoảng cách và thời gian di chuyển.",
        ]
        if status not in {"QUOTA_EXCEEDED", "REQUEST_DENIED", "REQUEST_ERROR"}:
            notes.append("Khi có tên tòa/phân khu rõ hơn, kết quả tìm kiếm sẽ sát vị trí căn hơn.")
        return notes
    if source == "google_maps_search":
        return [
            "Đã chuẩn bị sẵn các truy vấn bản đồ theo từng nhóm tiện ích quanh vị trí này.",
            "Mở từng nhóm trên bản đồ để xem kết quả thực tế, khoảng cách và thời gian di chuyển.",
            "Khi tư vấn thuê, nên kiểm tra giao thông, siêu thị và y tế trước; trường học/công viên là điểm cộng theo nhu cầu.",
        ]
    return [
        "Chưa tìm thấy kết quả tiện ích cụ thể cho vị trí này.",
        "Nên mở Google Maps và thử tìm theo tên tòa/phân khu cụ thể hơn.",
    ]


def _first_provider_status(categories: list[AmenityCategoryResult]) -> str | None:
    for category in categories:
        if category.provider_status and category.provider_status not in {"OK", "ZERO_RESULTS"}:
            return category.provider_status
    return None


def _top_category_text(categories: list[AmenityCategoryResult]) -> str:
    summaries = []
    for category in categories:
        if category.places:
            names = ", ".join(place.name for place in category.places[:2])
            summaries.append(f"{category.label}: {names}")
        else:
            summaries.append(f"{category.label}: mở map để kiểm tra")
    return "; ".join(summaries[:4])


def _source_label(source: str) -> str:
    if source == "serpapi_google_maps":
        return "kết quả địa điểm cụ thể"
    if source == "serpapi_error":
        return "truy vấn bản đồ dự phòng"
    if source == "google_places":
        return "kết quả địa điểm cụ thể"
    if source == "google_places_error":
        return "truy vấn bản đồ dự phòng"
    return "truy vấn bản đồ"


def _maps_search_url(query: str) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={quote_plus(query)}"


def _maps_embed_url(query: str) -> str:
    return f"https://www.google.com/maps?q={quote_plus(query)}&output=embed"


def _google_maps_api_key() -> str | None:
    key = os.getenv("GOOGLE_MAPS_API_KEY") or os.getenv("GOOGLE_PLACES_API_KEY")
    if not key:
        return None
    value = key.strip().strip('"').strip("'")
    return value or None


def _serpapi_api_key() -> str | None:
    key = os.getenv("SERPAPI_API_KEY")
    if not key:
        # Compatibility: older local tests stored a SerpApi key under GOOGLE_MAPS_API_KEY.
        candidate = _clean_key(os.getenv("GOOGLE_MAPS_API_KEY"))
        if candidate and _looks_like_serpapi_key(candidate):
            return candidate
        return None
    return _clean_key(key)


def _clean_key(value: str | None) -> str | None:
    if not value:
        return None
    clean = value.strip().strip('"').strip("'")
    return clean or None


def _looks_like_serpapi_key(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdefABCDEF" for char in value)


def _haversine_distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius_m = 6_371_000
    phi1 = radians(lat1)
    phi2 = radians(lat2)
    d_phi = radians(lat2 - lat1)
    d_lambda = radians(lng2 - lng1)
    a = sin(d_phi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(d_lambda / 2) ** 2
    return 2 * radius_m * atan2(sqrt(a), sqrt(1 - a))


def _optional_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default
