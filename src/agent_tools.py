from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.amenities import amenity_context, build_amenity_advice
from src.config import AppConfig
from src.schemas import AmenityAdviceRequest, AmenityAdviceResponse

MAPS_AMENITY_SEARCH = "maps_amenity_search"


@dataclass(frozen=True)
class AgentToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class AgentToolResult:
    name: str
    arguments: dict[str, Any]
    data: dict[str, Any]


def maps_amenity_search_tool(
    arguments: dict[str, Any],
    config: AppConfig,
) -> tuple[AmenityAdviceResponse, AgentToolResult]:
    request = AmenityAdviceRequest(
        project=str(arguments.get("project") or ""),
        purpose="rent",
        property_type=str(arguments.get("property_type") or "apartment"),
        address=_clean_optional(arguments.get("address")),
        subdivision=_clean_optional(arguments.get("subdivision")),
        tower=_clean_optional(arguments.get("tower")),
        max_places_per_category=int(arguments.get("max_places_per_category") or 3),
    )
    advice = build_amenity_advice(request, config, include_llm=False)
    result = AgentToolResult(
        name=MAPS_AMENITY_SEARCH,
        arguments=request.model_dump(exclude_none=True),
        data=amenity_context(advice),
    )
    return advice, result


def _clean_optional(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
