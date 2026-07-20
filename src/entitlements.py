from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from src.env import load_app_env
from src.schemas import AuthUser

TRUE_VALUES = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Entitlement:
    plan: str
    label: str
    is_authenticated: bool
    is_pro: bool
    credit_balance: int | None
    costs: dict[str, int]
    flags: dict[str, bool]

    def model(self) -> dict[str, Any]:
        return {
            "plan": self.plan,
            "label": self.label,
            "is_authenticated": self.is_authenticated,
            "is_pro": self.is_pro,
            "credit_balance": self.credit_balance,
            "costs": self.costs,
            "flags": self.flags,
        }


def resolve_entitlement(user: AuthUser | None) -> Entitlement:
    load_app_env()
    is_pro = _is_active_pro(user) if user else False
    plan = "agent_pro" if is_pro else "basic"
    costs = {
        "valuation": 0 if is_pro else int(os.getenv("BASIC_VALUATION_CREDIT_COST", "1")),
        "manual_amenity_search": 0 if is_pro else int(os.getenv("BASIC_MANUAL_MAP_CREDIT_COST", "2")),
    }
    flags = {
        "auto_map_enrichment": is_pro and _flag("ENABLE_AUTO_MAP_ENRICHMENT", True),
        "news_search": is_pro and _flag("ENABLE_NEWS_SEARCH", True),
        "pro_outlook": is_pro and _flag("ENABLE_PRO_OUTLOOK", True),
        "pdf_export": is_pro and _flag("ENABLE_PRO_PDF", True),
        "advisor_prompt_v2": _flag("ENABLE_ADVISOR_PROMPT_V2", True),
        "plan_entitlements": _flag("ENABLE_PLAN_ENTITLEMENTS", True),
    }
    return Entitlement(
        plan=plan,
        label="Agent Pro" if is_pro else "Gói Cơ Bản",
        is_authenticated=user is not None,
        is_pro=is_pro,
        credit_balance=user.credit_balance if user else None,
        costs=costs,
        flags=flags,
    )


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in TRUE_VALUES


def _is_active_pro(user: AuthUser | None) -> bool:
    if not user:
        return False
    if user.is_pro:
        return True
    value = user.pro_expires_at
    if not value:
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")) > datetime.now(UTC)
    except ValueError:
        return False
