from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from threading import Lock
from time import monotonic
from typing import Any

import yaml
from pydantic import ValidationError

from src.agent_tools import maps_amenity_search_tool
from src.amenities import amenity_context, build_amenity_advice
from src.config import AppConfig
from src.credits import InsufficientCreditsError, charge_credits, credit_summary, has_credits
from src.entitlements import Entitlement, resolve_entitlement
from src.env import PROJECT_ROOT, load_app_env, resolve_project_path
from src.llm import detect_response_language, generate_answer
from src.news import project_news
from src.normalization import (
    infer_project_slug,
    infer_property_type,
    normalize_furniture,
    normalize_view,
    parse_area,
    parse_bedrooms,
)
from src.retrieval import missing_info_retrieval
from src.schemas import (
    AmenityAdviceRequest,
    AmenityAdviceResponse,
    AuthUser,
    ChatRequest,
    ChatResponse,
    PropertyInput,
    ValuationResponse,
)
from src.text import compact_spaces, text_key
from src.valuation import estimate_property, market_trends, price_snapshot_references

MANUAL_AMENITY_ACTION = "manual_amenity_search"
PROPERTY_FIELD_NAMES = set(PropertyInput.model_fields.keys())
_VALUATION_AMENITY_CACHE: dict[tuple[str, ...], tuple[float, AmenityAdviceResponse]] = {}
_VALUATION_AMENITY_CACHE_LOCK = Lock()


@dataclass
class ChatRuntime:
    user: AuthUser | None
    entitlement: Entitlement
    db_path: str | Path
    language: str
    credit_event: dict[str, Any] | None = None
    enrichment: dict[str, Any] = field(default_factory=dict)


def handle_chat(
    payload: ChatRequest,
    config: AppConfig,
    db_path: str | Path,
    user: AuthUser | None = None,
) -> ChatResponse:
    message = compact_spaces(payload.message)
    runtime = ChatRuntime(
        user=user,
        entitlement=resolve_entitlement(user),
        db_path=db_path,
        language=detect_response_language(message),
    )
    parsed = _parse_property_fields(message, config)
    intent = _resolve_intent(message, parsed, payload.context)
    parsed = _merge_context_fields(parsed, payload.context)
    if payload.property:
        parsed = {**payload.property.model_dump(exclude_none=True), **{key: value for key, value in parsed.items() if value is not None}}

    if intent == "greeting":
        response = _handle_simple_intent("greeting", message, config, runtime)
        return _finalize_response(response, runtime)
    if intent == "thanks":
        response = _handle_simple_intent("thanks", message, config, runtime)
        return _finalize_response(response, runtime)
    if intent == "help":
        response = _handle_simple_intent("help", message, config, runtime)
        return _finalize_response(response, runtime)
    if intent == "news":
        response = _handle_news(message, parsed, config, runtime)
        return _finalize_response(response, runtime)
    if intent == "trend":
        response = _handle_trend(message, parsed, config, db_path, runtime)
        return _finalize_response(response, runtime)
    if intent == "snapshot":
        response = _handle_snapshot(message, parsed, config, db_path, runtime)
        return _finalize_response(response, runtime)
    if intent == "amenity":
        response = _handle_amenity(message, parsed, config, payload, runtime)
        return _finalize_response(response, runtime)
    response = _handle_valuation(message, parsed, config, db_path, payload, runtime)
    return _finalize_response(response, runtime)


def _handle_simple_intent(intent: str, message: str, config: AppConfig, runtime: ChatRuntime) -> ChatResponse:
    context = {
        "market": config.raw.get("market", {}),
        "projects": [{"slug": project.slug, "name": project.name} for project in config.projects],
        "plan": runtime.entitlement.plan,
    }
    return ChatResponse(
        answer=generate_answer(intent, message, context),
        missing_fields=[],
        intent=intent,
        extracted={},
    )


def _handle_news(message: str, fields: dict[str, Any], config: AppConfig, runtime: ChatRuntime) -> ChatResponse:
    missing = _missing_project(fields)
    if missing:
        context = _missing_context_without_db(missing, fields)
        context["plan"] = runtime.entitlement.plan
        return ChatResponse(
            answer=generate_answer("news_missing", message, context, fallback_key="news_missing"),
            missing_fields=missing,
            intent="news",
            extracted=fields,
            data={},
            context=_chat_context("news", missing, fields),
        )
    project = str(fields["project"])
    if not runtime.entitlement.flags.get("news_search"):
        context = {
            "project": _project_display(project),
            "plan": runtime.entitlement.plan,
        }
        return ChatResponse(
            answer=generate_answer("news_basic", message, context, fallback_key="news_basic"),
            missing_fields=[],
            intent="news",
            extracted=fields,
            data={},
            context=_chat_context("news", [], fields),
        )
    news_data = _news_enrichment(config, project, limit=4, location_label=_project_location_label(config, project))
    outlook = _news_only_outlook(news_data) if runtime.entitlement.flags.get("pro_outlook") else None
    runtime.enrichment = _enrichment_payload(None, news_data, outlook)
    answer = generate_answer(
        "news",
        message,
        {
            "project": _project_display(project),
            "news": news_data,
            "news_summary_text": _news_summary_sentence(news_data or {}),
            "outlook": outlook,
            "outlook_summary_text": (outlook or {}).get("summary") or "",
            "plan": runtime.entitlement.plan,
        },
        fallback_key="news",
    )
    data: dict[str, Any] = {}
    if news_data:
        data["news"] = news_data
    if outlook:
        data["outlook"] = outlook
    return ChatResponse(
        answer=answer,
        missing_fields=[],
        intent="news",
        extracted=fields,
        data=data,
        context=_chat_context("news", [], fields, runtime.enrichment),
    )


def _handle_valuation(
    message: str,
    fields: dict[str, Any],
    config: AppConfig,
    db_path: str | Path,
    payload: ChatRequest,
    runtime: ChatRuntime,
) -> ChatResponse:
    missing = _missing_for_valuation(fields)
    if missing:
        rent_budget_response = _rent_budget_response_without_area(message, fields, config, db_path, runtime, missing)
        if rent_budget_response:
            return rent_budget_response
        context = _missing_context(missing, fields, message, config, db_path)
        context["plan"] = runtime.entitlement.plan
        return ChatResponse(
            answer=generate_answer(
                "valuation_missing",
                message,
                context,
                fallback_key="valuation_missing",
            ),
            missing_fields=missing,
            data={"retrieval_suggestions": context.get("retrieval_suggestions")},
            intent="valuation",
            extracted=fields,
            context=_chat_context("valuation", missing, fields),
        )
    credit_cost = runtime.entitlement.costs.get("valuation", 0)
    if not has_credits(runtime.user, credit_cost, db_path):
        return _credit_block_response("valuation", credit_cost, fields, runtime)
    try:
        prop = PropertyInput(**_property_fields(fields))
        result = estimate_property(prop, config, db_path)
    except (ValidationError, ValueError) as exc:
        return ChatResponse(
            answer=generate_answer("error", message, {"error": str(exc), "fields": fields}, fallback_key="error"),
            missing_fields=[],
            intent="valuation",
            extracted=fields,
            context=_chat_context("valuation", [], fields),
        )

    refs = result.reference_price_snapshots
    if credit_cost > 0:
        try:
            runtime.credit_event = charge_credits(
                runtime.user,
                "valuation",
                credit_cost,
                db_path,
                idempotency_key=payload.idempotency_key,
                metadata={"intent": "valuation", "project": prop.project, "area_m2": prop.area_m2},
            ).model()
        except InsufficientCreditsError:
            return _credit_block_response("valuation", credit_cost, fields, runtime)

    enrichment_policy = _valuation_enrichment_policy(message, prop, fields, runtime, payload.context)
    amenity_advice = None
    news_data = None
    enrichment_jobs: dict[str, Any] = {}
    if enrichment_policy["map"] or enrichment_policy["news"]:
        with ThreadPoolExecutor(max_workers=2) as executor:
            if enrichment_policy["map"]:
                enrichment_jobs["map"] = executor.submit(_valuation_amenity_advice, message, result, prop, config)
            if enrichment_policy["news"]:
                enrichment_jobs["news"] = executor.submit(_valuation_news, config, prop, runtime)
            for kind, future in enrichment_jobs.items():
                try:
                    value = future.result()
                except Exception:  # noqa: BLE001
                    value = None
                if kind == "map":
                    amenity_advice = value
                elif kind == "news":
                    news_data = value
    outlook = (
        _build_outlook(result, prop, news_data)
        if runtime.entitlement.flags.get("pro_outlook") and (news_data or enrichment_policy["outlook"])
        else None
    )
    runtime.enrichment = _enrichment_payload(amenity_advice, news_data, outlook)

    answer_example = _format_valuation_answer(result, prop, amenity_advice, news_data, outlook, runtime.entitlement, fields)
    answer_example_en = _format_valuation_answer_en(result, prop, amenity_advice, news_data, outlook, runtime.entitlement, fields)
    answer = generate_answer(
        "valuation",
        message,
        _valuation_answer_context(result, prop, answer_example, amenity_advice, answer_example_en, news_data, outlook, runtime.entitlement, fields),
        fallback_key="valuation",
    )
    data = {"reference_price_snapshots": [item.model_dump() for item in refs]}
    if amenity_advice:
        data["amenity_advice"] = amenity_advice.model_dump()
    if news_data:
        data["news"] = news_data
    if outlook:
        data["outlook"] = outlook
    ui = None
    manual_amenity_offer = _basic_manual_amenity_offer(message, fields, runtime)
    if manual_amenity_offer:
        data.update(manual_amenity_offer["data"])
        ui = manual_amenity_offer["ui"]
    context_enrichment = runtime.enrichment or _prior_enrichment_for_context(payload.context, prop.project)
    return ChatResponse(
        answer=answer,
        missing_fields=[],
        valuation=result.model_dump(),
        data=data,
        intent="valuation",
        extracted=fields,
        context=_chat_context("valuation", [], fields, context_enrichment),
        ui=ui,
    )


def _handle_trend(message: str, fields: dict[str, Any], config: AppConfig, db_path: str | Path, runtime: ChatRuntime) -> ChatResponse:
    missing = _missing_project(fields)
    if missing:
        context = _missing_context(missing, fields, message, config, db_path)
        context["plan"] = runtime.entitlement.plan
        return ChatResponse(
            answer=generate_answer("trend_missing", message, context, fallback_key="trend_missing"),
            missing_fields=missing,
            data={"retrieval_suggestions": context.get("retrieval_suggestions")},
            intent="trend",
            extracted=fields,
            context=_chat_context("trend", missing, fields),
        )
    try:
        data = market_trends(
            config,
            fields["project"],
            fields.get("purpose", "sale"),
            fields.get("property_type"),
            fields.get("bedrooms"),
            db_path,
        )
    except ValueError as exc:
        return ChatResponse(
            answer=generate_answer("error", message, {"error": str(exc), "fields": fields}, fallback_key="error"),
            missing_fields=[],
            intent="trend",
            extracted=fields,
            context=_chat_context("trend", [], fields),
        )

    windows = data.get("windows", {})
    primary = windows.get("1m") or windows.get("3m") or {}
    refs = data.get("reference_price_snapshots") or []
    news_data = None
    if runtime.entitlement.flags.get("news_search") and fields.get("project"):
        news_data = _news_enrichment(config, str(fields["project"]), limit=4)
        runtime.enrichment = _enrichment_payload(None, news_data, _trend_outlook(data, news_data) if runtime.entitlement.flags.get("pro_outlook") else None)
    answer = generate_answer(
        "trend",
        message,
        {
            "project": data.get("project"),
            "property_type": data.get("property_type"),
            "property_type_label": _property_type_label(data.get("property_type") or "all"),
            "property_type_label_en": _property_type_label_en(data.get("property_type") or "all"),
            "purpose": data.get("purpose"),
            "purpose_label": _purpose_label(data.get("purpose")),
            "purpose_label_en": _purpose_label_en(data.get("purpose")),
            "bedrooms": data.get("bedrooms"),
            "windows": windows,
            "primary_median": primary.get("median"),
            "primary_median_text": _format_vnd(primary.get("median")) if primary.get("median") else "chưa đủ dữ liệu",
            "primary_sample_size": primary.get("sample_size", 0),
            "snapshot_reference_count": len(refs),
            "snapshot_count_text": _snapshot_count_text(len(refs)),
            "snapshot_count_text_en": _snapshot_count_text_en(len(refs)),
            "caveat": data.get("caveat"),
            "news": news_data,
            "plan": runtime.entitlement.plan,
        },
    )
    if news_data:
        data["news"] = news_data
    if runtime.enrichment.get("outlook"):
        data["outlook"] = runtime.enrichment["outlook"]
    return ChatResponse(answer=answer, intent="trend", extracted=fields, data=data, context=_chat_context("trend", [], fields))


def _handle_snapshot(message: str, fields: dict[str, Any], config: AppConfig, db_path: str | Path, runtime: ChatRuntime) -> ChatResponse:
    missing = _missing_project(fields)
    if missing:
        context = _missing_context(missing, fields, message, config, db_path)
        context["plan"] = runtime.entitlement.plan
        return ChatResponse(
            answer=generate_answer(
                "snapshot_missing",
                message,
                context,
                fallback_key="snapshot_missing",
            ),
            missing_fields=missing,
            data={"retrieval_suggestions": context.get("retrieval_suggestions")},
            intent="snapshot",
            extracted=fields,
            context=_chat_context("snapshot", missing, fields),
        )
    refs = price_snapshot_references(
        config,
        fields["project"],
        fields.get("purpose", "sale"),
        fields.get("property_type"),
        db_path=db_path,
    )
    if not refs:
        return ChatResponse(
            answer=generate_answer("no_snapshot", message, {"fields": fields, "plan": runtime.entitlement.plan}, fallback_key="no_snapshot"),
            intent="snapshot",
            extracted=fields,
            data={"reference_price_snapshots": []},
            context=_chat_context("snapshot", [], fields),
    )
    first = refs[0]
    range_text = _snapshot_range_text(first.model_dump())
    answer = generate_answer(
        "snapshot",
        message,
        {
            "project": first.project,
            "property_type": first.property_type,
            "property_type_label": _property_type_label(first.property_type),
            "property_type_label_en": _property_type_label_en(first.property_type),
            "purpose": first.purpose,
            "purpose_label": _purpose_label(first.purpose),
            "purpose_label_en": _purpose_label_en(first.purpose),
            "reference_count": len(refs),
            "first_label": first.label or first.property_type,
            "first_reference": first.model_dump(),
            "range_text": range_text,
            "plan": runtime.entitlement.plan,
        },
    )
    return ChatResponse(
        answer=answer,
        intent="snapshot",
        extracted=fields,
        data={"reference_price_snapshots": [item.model_dump() for item in refs]},
        context=_chat_context("snapshot", [], fields),
    )


def _handle_amenity(
    message: str,
    fields: dict[str, Any],
    config: AppConfig,
    payload: ChatRequest,
    runtime: ChatRuntime,
) -> ChatResponse:
    missing = _missing_project(fields)
    if missing:
        context = _missing_context_without_db(missing, fields)
        context["plan"] = runtime.entitlement.plan
        return ChatResponse(
            answer=generate_answer("amenity_missing", message, context, fallback_key="amenity_missing"),
            missing_fields=missing,
            intent="amenity",
            extracted=fields,
            data={},
            context=_chat_context("amenity", missing, fields),
        )
    credit_cost = runtime.entitlement.costs.get("manual_amenity_search", 0)
    is_manual_action = payload.action == MANUAL_AMENITY_ACTION
    if credit_cost > 0 and not is_manual_action:
        return _manual_amenity_confirm_response(message, fields, credit_cost, runtime)
    if credit_cost > 0 and runtime.user is None:
        return _login_required_response("amenity", fields, runtime)
    if not has_credits(runtime.user, credit_cost, runtime.db_path):
        return _credit_block_response("manual_amenity_search", credit_cost, fields, runtime)
    try:
        advice, tool_result = maps_amenity_search_tool(
            {
                "project": fields["project"],
                "property_type": fields.get("property_type", "apartment"),
                "address": fields.get("address"),
                "subdivision": fields.get("subdivision"),
                "tower": fields.get("tower"),
                "max_places_per_category": 3,
            },
            config,
        )
    except ValueError as exc:
        return ChatResponse(
            answer=generate_answer("error", message, {"error": str(exc), "fields": fields}, fallback_key="error"),
            missing_fields=[],
            intent="amenity",
            extracted=fields,
            context=_chat_context("amenity", [], fields),
        )
    if credit_cost > 0:
        try:
            runtime.credit_event = charge_credits(
                runtime.user,
                "manual_amenity_search",
                credit_cost,
                runtime.db_path,
                idempotency_key=payload.idempotency_key,
                metadata={"intent": "amenity", "project": fields.get("project")},
            ).model()
        except InsufficientCreditsError:
            return _credit_block_response("manual_amenity_search", credit_cost, fields, runtime)
    answer = generate_answer(
        "amenity",
        message,
        {
            **amenity_context(advice),
            "plan": runtime.entitlement.plan,
            "agent_tool": {
                "name": tool_result.name,
                "arguments": tool_result.arguments,
                "data": tool_result.data,
            },
        },
        fallback_key="amenity",
    )
    advice.llm_advice = answer
    runtime.enrichment = _enrichment_payload(advice, None, None)
    return ChatResponse(
        answer=answer,
        missing_fields=[],
        intent="amenity",
        extracted=fields,
        data={
            "amenity_advice": advice.model_dump(),
            "agent_tool": {
                "name": tool_result.name,
                "arguments": tool_result.arguments,
            },
        },
        context=_chat_context("amenity", [], fields, runtime.enrichment),
    )


def _detect_intent(message: str) -> str:
    key = text_key(message)
    rules = _intent_rules()
    if _is_greeting_only(key, rules):
        return "greeting"
    if _is_thanks_only(key, rules):
        return "thanks"
    if any(term in key for term in rules.get("help_terms", [])):
        return "help"
    if _is_trend_question(key, rules):
        return "trend"
    if _is_news_question(key):
        return "news"
    if any(term in key for term in rules.get("snapshot_terms", [])):
        return "snapshot"
    if any(term in key for term in rules.get("amenity_terms", [])):
        return "amenity"
    return "valuation"


def _resolve_intent(message: str, fields: dict[str, Any], context: dict[str, Any] | None) -> str:
    intent = _detect_intent(message)
    if intent == "news" and _has_current_valuation_request(message, fields):
        return "valuation"
    if intent != "valuation":
        return intent
    pending_intent = str((context or {}).get("pending_intent") or "")
    if pending_intent not in {"amenity", "valuation", "trend", "snapshot", "news"}:
        return intent
    missing_fields = {str(item) for item in (context or {}).get("missing_fields") or []}
    if missing_fields and missing_fields.intersection(fields):
        return pending_intent
    if _looks_like_short_followup(message, fields):
        return pending_intent
    return intent


def _has_current_valuation_request(message: str, fields: dict[str, Any]) -> bool:
    key = text_key(message)
    has_property_detail = bool(fields.get("area_m2") or fields.get("bedrooms") is not None)
    has_valuation_language = any(
        term in key
        for term in (
            "dinh gia",
            "gia",
            "ban",
            "mua",
            "thue",
            "cho thue",
            "rent",
            "sale",
            "sell",
            "buy",
            "estimate",
        )
    )
    return has_property_detail and has_valuation_language


def _is_trend_question(key: str, rules: dict[str, Any]) -> bool:
    if any(term in key for term in rules.get("trend_terms", [])):
        return True
    trend_phrases = (
        "ba thang",
        "3 thang",
        "gan day gia",
        "gia gan day",
        "tang hay giam",
        "tang hay la giam",
        "bien dong gia",
        "xu the gia",
    )
    return any(term in key for term in trend_phrases)


def _is_news_question(key: str) -> bool:
    news_terms = (
        "tin tuc",
        "tin moi",
        "co tin gi",
        "news",
        "su kien",
        "quy hoach",
        "ha tang",
        "thi cong",
        "mo rong",
        "xay them",
        "xay moi",
        "sap mo",
        "sap xay",
        "tuong lai",
        "trien vong",
        "outlook",
        "mot nam nua",
        "1 nam nua",
        "nam nua",
        "thang 7",
        "anh huong den gia",
        "co tang gia",
        "co giam gia",
        "chac chan tang",
        "chac chan giam",
    )
    return any(term in key for term in news_terms)


def _merge_context_fields(fields: dict[str, Any], context: dict[str, Any] | None) -> dict[str, Any]:
    extracted = (context or {}).get("extracted")
    if not isinstance(extracted, dict):
        return fields
    clean_extracted = {key: value for key, value in extracted.items() if value is not None}
    clean_fields = {key: value for key, value in fields.items() if value is not None}
    return {**clean_extracted, **clean_fields}


def _looks_like_short_followup(message: str, fields: dict[str, Any]) -> bool:
    key = text_key(message)
    tokens = key.split()
    if not tokens or len(tokens) > 8:
        return False
    followup_keys = {"project", "area_m2", "bedrooms", "subdivision", "tower", "view", "furniture"}
    return bool(followup_keys.intersection(fields))


def _chat_context(
    intent: str,
    missing_fields: list[str],
    fields: dict[str, Any],
    enrichment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = {
        "pending_intent": intent if missing_fields else None,
        "missing_fields": missing_fields,
        "extracted": fields,
    }
    if enrichment:
        context["enrichment"] = enrichment
    return context


def _property_fields(fields: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in fields.items() if key in PROPERTY_FIELD_NAMES and value is not None}


def _finalize_response(response: ChatResponse, runtime: ChatRuntime) -> ChatResponse:
    entitlements = runtime.entitlement.model()
    response.response_language = runtime.language if runtime.language in {"vi", "en"} else "vi"
    response.plan = runtime.entitlement.plan
    response.entitlements = entitlements
    response.enrichment = runtime.enrichment or response.enrichment
    if response.credits is None:
        response.credits = runtime.credit_event or _default_credit_state(runtime)
    if response.advice is None:
        response.advice = _advice_metadata(response.extracted or {}, runtime)
    return response


def _default_credit_state(runtime: ChatRuntime) -> dict[str, Any]:
    user = runtime.user
    balance = user.credit_balance if user else None
    status = "pro_waived" if runtime.entitlement.is_pro else "not_charged"
    return {
        "status": status,
        "action": None,
        "required": 0,
        "charged": 0,
        "balance_before": balance,
        "balance_after": balance,
        "idempotency_key": None,
    }


def _advice_metadata(fields: dict[str, Any], runtime: ChatRuntime) -> dict[str, Any]:
    return {
        "user_side": fields.get("user_side") or "unknown",
        "transaction_goal": fields.get("transaction_goal") or "unknown",
        "expected_transaction_time": fields.get("expected_transaction_time"),
        "plan": runtime.entitlement.plan,
    }


def _manual_amenity_confirm_response(
    message: str,
    fields: dict[str, Any],
    credit_cost: int,
    runtime: ChatRuntime,
) -> ChatResponse:
    project = _project_display(fields.get("project"))
    if runtime.language == "en":
        answer = (
            f"I can check nearby amenities for {project}. This is a separate map lookup and costs "
            f"{credit_cost} credits on the Basic plan; tap the button below when you want to run it."
        )
        label = f"Check amenities - {credit_cost} credits"
    else:
        answer = (
            f"Mình có thể tra tiện ích quanh {project}. Đây là lượt tra bản đồ riêng và sẽ dùng "
            f"{credit_cost} điểm ở Gói Cơ Bản; bấm nút bên dưới khi bạn muốn chạy."
        )
        label = f"Tra tiện ích - {credit_cost} điểm"
    context = _chat_context("amenity", [], fields)
    return ChatResponse(
        answer=answer,
        missing_fields=[],
        intent="amenity",
        extracted=fields,
        context=context,
        data={
            "amenity_pending": {
                "project": fields.get("project"),
                "cost": credit_cost,
            }
        },
        ui={
            "actions": [
                {
                    "type": MANUAL_AMENITY_ACTION,
                    "label": label,
                    "message": message if message else f"Tra tiện ích quanh {project}",
                    "context": context,
                    "cost": credit_cost,
                }
            ],
            "requires_confirmation": True,
        },
    )


def _credit_block_response(action: str, credit_cost: int, fields: dict[str, Any], runtime: ChatRuntime) -> ChatResponse:
    balance = runtime.user.credit_balance if runtime.user else None
    if runtime.language == "en":
        answer = f"This action needs {credit_cost} credits. Your current balance is {balance or 0}; please top up or upgrade to Agent Pro."
    else:
        answer = f"Thao tác này cần {credit_cost} điểm. Ví hiện có {balance or 0} điểm; bạn nạp thêm hoặc nâng cấp Agent Pro để tiếp tục."
    return ChatResponse(
        answer=answer,
        intent="billing",
        extracted=fields,
        data={},
        context=_chat_context("billing", [], fields),
        credits=credit_summary(action, credit_cost, runtime.user),
        ui={"billing_required": True, "open_pricing": True},
    )


def _login_required_response(intent: str, fields: dict[str, Any], runtime: ChatRuntime) -> ChatResponse:
    answer = (
        "Please sign in before running this paid lookup."
        if runtime.language == "en"
        else "Bạn đăng nhập trước khi chạy lượt tra cứu có tính điểm nhé."
    )
    return ChatResponse(
        answer=answer,
        intent=intent,
        extracted=fields,
        data={},
        context=_chat_context(intent, [], fields),
        credits=credit_summary(intent, runtime.entitlement.costs.get("manual_amenity_search", 0), runtime.user),
        ui={"login_required": True},
    )


def _basic_manual_amenity_offer(
    message: str,
    fields: dict[str, Any],
    runtime: ChatRuntime,
) -> dict[str, Any] | None:
    credit_cost = runtime.entitlement.costs.get("manual_amenity_search", 0)
    if runtime.entitlement.is_pro or credit_cost <= 0 or not fields.get("project"):
        return None
    project = _project_display(fields.get("project"))
    label = f"Check amenities - {credit_cost} credits" if runtime.language == "en" else f"Tra tiện ích - {credit_cost} điểm"
    context = _chat_context("amenity", [], fields)
    return {
        "data": {
            "amenity_pending": {
                "project": fields.get("project"),
                "cost": credit_cost,
            }
        },
        "ui": {
            "actions": [
                {
                    "type": MANUAL_AMENITY_ACTION,
                    "label": label,
                    "message": message if message else f"Tra tiện ích quanh {project}",
                    "context": context,
                    "cost": credit_cost,
                }
            ],
            "requires_confirmation": True,
        },
    }


def _rent_budget_response_without_area(
    message: str,
    fields: dict[str, Any],
    config: AppConfig,
    db_path: str | Path,
    runtime: ChatRuntime,
    missing: list[str],
) -> ChatResponse | None:
    if missing != ["area_m2"] or fields.get("purpose") != "rent" or not fields.get("budget_vnd") or not fields.get("project"):
        return None
    if fields.get("user_side") not in {None, "tenant", "buyer"}:
        return None
    trend = _rent_budget_trend(config, fields, db_path)
    primary = _primary_trend_window(trend.get("windows") or {})
    answer = _format_rent_budget_answer(fields, trend, primary, runtime.language)
    data: dict[str, Any] = {"market_trend": trend}
    ui = None
    manual_amenity_offer = _basic_manual_amenity_offer(message, fields, runtime)
    if manual_amenity_offer:
        data.update(manual_amenity_offer["data"])
        ui = manual_amenity_offer["ui"]
    return ChatResponse(
        answer=answer,
        missing_fields=[],
        data=data,
        intent="valuation",
        extracted=fields,
        context=_chat_context("valuation", [], fields),
        ui=ui,
    )


def _rent_budget_trend(config: AppConfig, fields: dict[str, Any], db_path: str | Path) -> dict[str, Any]:
    attempts = (
        (fields.get("property_type"), fields.get("bedrooms")),
        (fields.get("property_type"), None),
        (None, fields.get("bedrooms")),
        (None, None),
    )
    for property_type, bedrooms in attempts:
        try:
            return market_trends(config, fields["project"], "rent", property_type, bedrooms, db_path)
        except ValueError:
            continue
    return {
        "project": _project_display(fields.get("project")),
        "property_type": fields.get("property_type"),
        "purpose": "rent",
        "bedrooms": fields.get("bedrooms"),
        "windows": {},
        "reference_price_snapshots": [],
        "caveat": "",
    }


def _primary_trend_window(windows: dict[str, Any]) -> dict[str, Any]:
    for key in ("1m", "3m", "6m", "12m"):
        item = windows.get(key)
        if isinstance(item, dict) and item.get("median"):
            return item
    return {}


def _format_rent_budget_answer(
    fields: dict[str, Any],
    trend: dict[str, Any],
    primary: dict[str, Any],
    language: str,
) -> str:
    budget = float(fields.get("budget_vnd") or 0)
    median = float(primary.get("median") or 0)
    low = float(primary.get("p10") or 0)
    high = float(primary.get("p90") or 0)
    project = _project_display(fields.get("project") or trend.get("project"))
    bedrooms = fields.get("bedrooms")
    bedroom_text = f"{bedrooms}-bedroom" if language == "en" and bedrooms is not None else (f"{bedrooms}PN" if bedrooms is not None else "căn")
    if language == "en":
        if median:
            position = _budget_position_text_en(budget, low, median, high)
            range_text = _format_market_money_range_en(low, high, "rent") + "/month" if low and high else _format_market_money_en(median, "rent") + "/month"
            return (
                f"With a budget of {_format_market_money_en(budget, 'rent')}/month for a {bedroom_text} unit at {project}, "
                f"this budget looks {position} versus the current rental reference band around {range_text}.\n\n"
                "I still need the exact area, tower/subdivision, and furniture condition before pricing a specific unit. "
                "For a family with children, prioritize transport, groceries, healthcare, school access, and lift/lobby convenience."
            )
        return (
            f"With a budget of {_format_market_money_en(budget, 'rent')}/month for {project}, I can give an initial fit check, "
            "but I still need the area and tower/subdivision to price a specific unit."
        )
    if median:
        position = _budget_position_text(budget, low, median, high)
        range_text = _format_market_money_range(low, high, "rent") + "/tháng" if low and high else _format_market_money(median, "rent") + "/tháng"
        return (
            f"Với ngân sách {_format_market_money(budget, 'rent')}/tháng cho căn {bedroom_text} tại {project}, "
            f"mức này {position} so với mặt bằng thuê tham khảo quanh {range_text}.\n\n"
            "Mình vẫn cần thêm diện tích, tòa/phân khu và tình trạng nội thất để chốt một căn cụ thể. "
            "Nếu ở với con nhỏ, nên ưu tiên giao thông, siêu thị, y tế, trường học và độ thuận tiện sảnh/thang máy."
        )
    return (
        f"Với ngân sách {_format_market_money(budget, 'rent')}/tháng tại {project}, mình có thể đánh giá sơ bộ độ phù hợp, "
        "nhưng vẫn cần thêm diện tích và tòa/phân khu để chốt sát hơn. Nếu ở với con nhỏ, nên ưu tiên trường học, "
        "siêu thị, y tế, giao thông và độ thuận tiện sảnh/thang máy."
    )


def _budget_position_text(budget: float, low: float, median: float, high: float) -> str:
    if high and budget >= high:
        return "đang khá thoải mái"
    if median and budget >= median:
        return "đang ở mức tương đối phù hợp"
    if low and budget >= low:
        return "có thể phù hợp nhưng nên lọc kỹ tòa, diện tích và nội thất"
    return "hơi chặt, nên cân nhắc căn nhỏ hơn hoặc nội thất cơ bản"


def _budget_position_text_en(budget: float, low: float, median: float, high: float) -> str:
    if high and budget >= high:
        return "comfortable"
    if median and budget >= median:
        return "reasonably suitable"
    if low and budget >= low:
        return "possible, but you should filter carefully by tower, area, and furniture"
    return "tight, so a smaller or more basic unit may fit better"


@lru_cache(maxsize=1)
def _intent_rules() -> dict[str, list[str]]:
    load_app_env()
    raw_path = os.getenv("VALUATION_INTENT_RULES_PATH")
    path = resolve_project_path(raw_path) if raw_path else PROJECT_ROOT / "prompts" / "intent_rules.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {str(key): [str(item) for item in value] for key, value in (data or {}).items() if isinstance(value, list)}


def _is_greeting_only(key: str, rules: dict[str, list[str]]) -> bool:
    normalized = compact_spaces(re.sub(r"[^a-z0-9 ]+", " ", key)).strip()
    if not normalized:
        return True
    if normalized in set(rules.get("greeting_phrases", [])):
        return True
    tokens = normalized.split()
    domain_terms = set(rules.get("domain_terms", []))
    greeting_starts = set(rules.get("greeting_starts", []))
    return len(tokens) <= 3 and tokens[0] in greeting_starts and not any(
        token in domain_terms for token in tokens[1:]
    )


def _is_thanks_only(key: str, rules: dict[str, list[str]]) -> bool:
    normalized = compact_spaces(re.sub(r"[^a-z0-9 ]+", " ", key)).strip()
    return normalized in set(rules.get("thanks_phrases", []))


def _parse_property_fields(message: str, config: AppConfig) -> dict[str, Any]:
    project_slug = infer_project_slug(config, message, default=None)
    project = config.project_by_slug.get(project_slug or "")
    area = _parse_area_from_message(message)
    fields: dict[str, Any] = {
        "purpose": _parse_purpose(message),
        "project": project.slug if project else None,
        "property_type": _parse_property_type(message),
        "area_m2": area,
        "bedrooms": parse_bedrooms(message),
        "bathrooms": _parse_bathrooms(message),
        "subdivision": _parse_subdivision(message),
        "tower": _parse_tower(message),
        "view": normalize_view(message),
        "furniture": normalize_furniture(message),
        "user_side": _parse_user_side(message),
        "transaction_goal": _parse_transaction_goal(message),
        "expected_transaction_time": _parse_expected_transaction_time(message),
        "asking_price_vnd": _parse_money_context(message, asking=True),
        "budget_vnd": _parse_money_context(message, asking=False),
    }
    return {key: value for key, value in fields.items() if value is not None}


def _parse_purpose(message: str) -> str | None:
    key = text_key(message)
    if any(term in key for term in ("thue", "cho thue", "rent", "rental", "lease", "for rent")):
        return "rent"
    if any(term in key for term in ("ban", "mua", "chuyen nhuong", "sell", "sale", "buy", "purchase", "for sale")):
        return "sale"
    return None


def _parse_property_type(message: str) -> str | None:
    prop_type = infer_property_type(message, default=None)
    return prop_type if prop_type != "other" else None


def _parse_area_from_message(message: str) -> float | None:
    for match in re.finditer(
        r"(\d+(?:[,.]\d+)?)\s*(?:m2|m²|mét|met|sqm|sq\.?\s*m|square\s*meters?)\b",
        message,
        re.IGNORECASE,
    ):
        prefix = message[max(0, match.start() - 18) : match.start()].lower()
        if "triệu" in prefix or "trieu" in text_key(prefix):
            continue
        area = parse_area(match.group(1))
        if area:
            return area
    return None


def _parse_bathrooms(message: str) -> int | None:
    match = re.search(r"(\d+)\s*(?:wc|vs|ve sinh|vệ sinh)", message, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _parse_subdivision(message: str) -> str | None:
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
        "Thời Đại",
        "Phố Biển",
    ]
    key = text_key(message)
    for candidate in candidates:
        if text_key(candidate) in key:
            return candidate
    return None


def _parse_tower(message: str) -> str | None:
    match = re.search(r"\b([A-Z]{1,3}\d{1,3}(?:\.\d{1,3})?|S\d{1,3}|GS\d|R\d{1,2}|T\d{1,2})\b", message, re.IGNORECASE)
    return match.group(1).upper() if match else None


def _parse_user_side(message: str) -> str | None:
    key = text_key(message)
    if any(
        term in key
        for term in (
            "mua duoc khong",
            "co mua duoc",
            "co nen mua",
            "chu nha chao",
            "nguoi ban chao",
            "seller asks",
            "seller asking",
            "should i buy",
        )
    ):
        return "buyer"
    if any(
        term in key
        for term in (
            "di thue",
            "tim thue",
            "muon thue",
            "can thue",
            "thue de o",
            "tenant",
            "rent an apartment",
            "lease an apartment",
            "looking to rent",
        )
    ):
        return "tenant"
    if any(term in key for term in ("cho thue", "chu nha cho thue", "landlord")):
        return "landlord"
    if any(term in key for term in ("toi muon ban", "can ban", "chu nha", "owner", "sell my", "i want to sell")):
        return "seller"
    if any(term in key for term in ("toi muon mua", "can mua", "nguoi mua", "budget", "buy", "purchase")):
        return "buyer"
    return None


def _parse_transaction_goal(message: str) -> str | None:
    key = text_key(message)
    if any(term in key for term in ("ban nhanh", "chot nhanh", "quick", "urgent", "trong mot thang", "1 thang", "30 ngay")):
        return "quick_transaction"
    if any(term in key for term in ("gia tot nhat", "toi da gia", "maximize", "cao nhat")):
        return "maximize_price"
    if any(term in key for term in ("mua de o", "o thuc", "own use")):
        return "own_use"
    if any(term in key for term in ("dau tu", "investment", "yield")):
        return "investment"
    if any(term in key for term in ("can bang", "hop ly", "balanced")):
        return "balanced"
    return None


def _parse_expected_transaction_time(message: str) -> str | None:
    key = text_key(message)
    if any(term in key for term in ("trong tuan", "7 ngay", "this week")):
        return "this_week"
    if any(term in key for term in ("trong thang", "trong mot thang", "mot thang", "1 thang", "30 ngay", "this month")):
        return "this_month"
    if any(term in key for term in ("3 thang", "quy nay", "quarter")):
        return "this_quarter"
    return None


def _parse_money_context(message: str, *, asking: bool) -> float | None:
    key = text_key(message)
    markers = (
        ("rao", "dang chao", "chu nha chao", "nguoi ban chao", "gia chao", "chao", "muon ban", "asking", "asks")
        if asking
        else ("ngan sach", "budget", "toi da", "co khoang", "afford", "can spend")
    )
    if not any(marker in key for marker in markers):
        return None
    for match in re.finditer(r"(\d+(?:[,.]\d+)?)\s*(ty|tỷ|trieu|triệu|m|bn|billion)", message, re.IGNORECASE):
        unit = text_key(match.group(2))
        suffix = message[match.end() : match.end() + 2].lower()
        if unit == "m" and suffix.startswith(("2", "²")):
            continue
        value = float(match.group(1).replace(",", "."))
        if unit in {"ty", "bn", "billion"}:
            return value * 1_000_000_000
        return value * 1_000_000
    return None


def _missing_for_valuation(fields: dict[str, Any]) -> list[str]:
    missing = _missing_project(fields)
    if not fields.get("area_m2"):
        missing.append("area_m2")
    return missing


def _missing_project(fields: dict[str, Any]) -> list[str]:
    return [] if fields.get("project") else ["project"]


def _missing_context(
    missing: list[str],
    fields: dict[str, Any],
    message: str,
    config: AppConfig,
    db_path: str | Path,
) -> dict[str, Any]:
    labels = {
        "project": "dự án/khu đô thị",
        "area_m2": "diện tích m2",
    }
    labels_en = {
        "project": "the project or urban area",
        "area_m2": "the area in square meters",
    }
    retrieval = missing_info_retrieval(message, fields, missing, config, db_path)
    return {
        "missing_fields": missing,
        "missing_labels": ", ".join(labels.get(item, item) for item in missing),
        "missing_labels_en": ", ".join(labels_en.get(item, item) for item in missing),
        "extracted": fields,
        "retrieval_suggestions": retrieval,
        "retrieval_hint_text": _public_missing_hint_text(missing, fields, retrieval),
    }


def _missing_context_without_db(missing: list[str], fields: dict[str, Any]) -> dict[str, Any]:
    labels = {
        "project": "dự án/khu đô thị",
    }
    labels_en = {
        "project": "the project or urban area",
    }
    return {
        "missing_fields": missing,
        "missing_labels": ", ".join(labels.get(item, item) for item in missing),
        "missing_labels_en": ", ".join(labels_en.get(item, item) for item in missing),
        "extracted": fields,
        "retrieval_hint_text": "",
    }


def _public_missing_hint_text(missing: list[str], fields: dict[str, Any], retrieval: dict[str, Any]) -> str:
    pieces: list[str] = []
    project = _project_display(fields.get("project"))
    if "area_m2" in missing:
        area_hint = retrieval.get("area_hint") if isinstance(retrieval, dict) else None
        if isinstance(area_hint, dict) and area_hint.get("range_text"):
            pieces.append(
                f"Với nhóm căn tương tự ở {project}, diện tích thường gặp nằm khoảng {area_hint['range_text']}."
            )
        pieces.append("Bạn gửi thêm diện tích căn là mình sẽ chốt được khoảng giá sát hơn.")
    if "project" in missing:
        nearest = retrieval.get("nearest_projects") if isinstance(retrieval, dict) else None
        if isinstance(nearest, list) and nearest:
            names = ", ".join(compact_spaces(item.get("name")) for item in nearest[:3] if isinstance(item, dict) and item.get("name"))
            if names:
                pieces.append(f"Mình có thể hỗ trợ các khu như {names}.")
        pieces.append("Bạn cho mình tên dự án hoặc khu đô thị trước nhé.")
    return " ".join(piece for piece in pieces if piece)


def _snapshot_range_text(item: dict[str, Any]) -> str:
    if item.get("price_min_vnd") and item.get("price_max_vnd"):
        return f"{_format_vnd(item['price_min_vnd'])} - {_format_vnd(item['price_max_vnd'])}"
    if item.get("price_per_m2_min_vnd") and item.get("price_per_m2_max_vnd"):
        return f"{_format_vnd(item['price_per_m2_min_vnd'])}/m2 - {_format_vnd(item['price_per_m2_max_vnd'])}/m2"
    return "chưa có khoảng giá rõ"


def _format_valuation_answer(
    result: ValuationResponse,
    prop: PropertyInput,
    amenity_advice: AmenityAdviceResponse | None = None,
    news_data: dict[str, Any] | None = None,
    outlook: dict[str, Any] | None = None,
    entitlement: Entitlement | None = None,
    extracted_fields: dict[str, Any] | None = None,
) -> str:
    purpose_label = "giá thuê" if result.purpose == "rent" else "giá bán"
    monthly_suffix = "/tháng" if result.purpose == "rent" else ""
    lines = [
        f"Với căn {result.project} {_format_area(prop.area_m2)}{_bedroom_suffix(prop)}, {purpose_label} hợp lý nên neo quanh {_format_market_money(result.p50_total_vnd, result.purpose)}{monthly_suffix}.",
        f"Biên thương lượng thực tế nên giữ trong khoảng {_format_market_money_range(result.p10_total_vnd, result.p90_total_vnd, result.purpose)}{monthly_suffix}, tùy tầng, view, nội thất và tốc độ cần chốt.",
        f"Độ tin cậy hiện ở mức {_confidence_label(result.confidence)}.",
    ]
    advice_lines = _transaction_advice_lines(result, prop, extracted_fields or {})
    if advice_lines:
        lines.extend(advice_lines)
    analysis = _valuation_analysis_lines(result, prop)
    if analysis:
        lines.append(" ".join(analysis[:2]))
    factors = _valuation_adjustment_lines(result, prop)[:3]
    if factors:
        lines.append("Yếu tố cần soi kỹ:")
        lines.extend(_public_factor_text(item) for item in factors)
    if entitlement and entitlement.is_pro and amenity_advice:
        lines.append("Tiện ích nổi bật: " + " ".join(_amenity_price_lines(amenity_advice, result)[:2]))
    if entitlement and entitlement.is_pro and news_data:
        news_summary = _news_summary_sentence(news_data)
        if news_summary:
            lines.append(news_summary)
    if entitlement and entitlement.is_pro and outlook:
        lines.append(str(outlook.get("summary") or ""))
    missing_optional = _missing_optional_detail_lines(prop)
    if missing_optional:
        lines.append("Để chốt sát hơn, bạn nên bổ sung " + ", ".join(missing_optional[:3]) + ".")
    lines.append("Đây là mức tham khảo từ thông tin thị trường công khai đã được làm sạch, chưa phải cam kết giá chốt.")
    return "\n\n".join(line for line in lines if line)


def _format_valuation_answer_en(
    result: ValuationResponse,
    prop: PropertyInput,
    amenity_advice: AmenityAdviceResponse | None = None,
    news_data: dict[str, Any] | None = None,
    outlook: dict[str, Any] | None = None,
    entitlement: Entitlement | None = None,
    extracted_fields: dict[str, Any] | None = None,
) -> str:
    purpose_label = "rental price" if result.purpose == "rent" else "sale price"
    monthly_suffix = "/month" if result.purpose == "rent" else ""
    lines = [
        f"For this {_format_area(prop.area_m2)}{_bedroom_suffix_en(prop)} unit at {result.project}, a reasonable {purpose_label} anchor is around {_format_market_money_en(result.p50_total_vnd, result.purpose)}{monthly_suffix}.",
        f"A practical negotiation band is {_format_market_money_range_en(result.p10_total_vnd, result.p90_total_vnd, result.purpose)}{monthly_suffix}, depending on floor, view, furniture, and how quickly you need to close.",
        f"Confidence is {_confidence_label_en(result.confidence)}.",
    ]
    advice_lines = _transaction_advice_lines_en(result, prop, extracted_fields or {})
    if advice_lines:
        lines.extend(advice_lines)
    factors = _valuation_adjustment_lines_en(result, prop)[:3]
    if factors:
        lines.append("Key checks:")
        lines.extend(_public_factor_text_en(item) for item in factors)
    if entitlement and entitlement.is_pro and amenity_advice:
        lines.append("Nearby amenity context: " + " ".join(_amenity_price_lines_en(amenity_advice, result)[:2]))
    if entitlement and entitlement.is_pro and news_data:
        news_summary = _news_summary_sentence_en(news_data)
        if news_summary:
            lines.append(news_summary)
    if entitlement and entitlement.is_pro and outlook:
        lines.append(str(outlook.get("summary_en") or outlook.get("summary") or ""))
    missing_optional = _missing_optional_detail_lines_en(prop)
    if missing_optional:
        lines.append("For a sharper estimate, add " + ", ".join(missing_optional[:3]) + ".")
    lines.append("This is a market reference from cleaned public market information, not a guaranteed closed price.")
    return "\n\n".join(line for line in lines if line)


def _valuation_answer_context(
    result: ValuationResponse,
    prop: PropertyInput,
    answer_example: str,
    amenity_advice: AmenityAdviceResponse | None = None,
    answer_example_en: str | None = None,
    news_data: dict[str, Any] | None = None,
    outlook: dict[str, Any] | None = None,
    entitlement: Entitlement | None = None,
    extracted_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    monthly_suffix = "/tháng" if result.purpose == "rent" else ""
    missing_optional = _missing_optional_detail_lines(prop)
    safe_factors = [_public_factor_text(factor) for factor in result.top_factors if factor]
    context = {
        "purpose": result.purpose,
        "purpose_label": _purpose_label(result.purpose),
        "purpose_label_en": _purpose_label_en(result.purpose),
        "project": result.project,
        "property": prop.model_dump(),
        "property_type": result.property_type,
        "property_type_label": _property_type_label(result.property_type),
        "property_type_label_en": _property_type_label_en(result.property_type),
        "area_m2": prop.area_m2,
        "area_text": _format_area(prop.area_m2),
        "bedrooms": prop.bedrooms,
        "bedrooms_text": f" {prop.bedrooms}PN" if prop.bedrooms is not None else "",
        "p10_total_vnd": result.p10_total_vnd,
        "p50_total_vnd": result.p50_total_vnd,
        "p90_total_vnd": result.p90_total_vnd,
        "p10_total_text": f"{_format_market_money(result.p10_total_vnd, result.purpose)}{monthly_suffix}",
        "p50_total_text": f"{_format_market_money(result.p50_total_vnd, result.purpose)}{monthly_suffix}",
        "p90_total_text": f"{_format_market_money(result.p90_total_vnd, result.purpose)}{monthly_suffix}",
        "range_total_text": f"{_format_market_money_range(result.p10_total_vnd, result.p90_total_vnd, result.purpose)}{monthly_suffix}",
        "price_per_m2_text": _valuation_price_per_m2_text(result),
        "confidence": result.confidence,
        "confidence_label": _confidence_label(result.confidence),
        "confidence_label_en": _confidence_label_en(result.confidence),
        "confidence_percent": _confidence_percent(result),
        "data_freshness": result.data_freshness,
        "top_factors": safe_factors,
        "top_factor_text": _valuation_top_factor_text(result),
        "analysis_lines": _valuation_analysis_lines(result, prop),
        "adjustment_lines": _valuation_adjustment_lines(result, prop),
        "adjustment_lines_en": _valuation_adjustment_lines_en(result, prop),
        "missing_optional_details": missing_optional,
        "missing_optional_text": ", ".join(missing_optional),
        "comparable_range_text": _comparable_range_text(result) or "",
        "reference_snapshot_count": len(result.reference_price_snapshots),
        "answer_example": answer_example,
        "example_answer": answer_example,
        "answer_example_en": answer_example_en or "",
        "plan": entitlement.plan if entitlement else "basic",
        "user_side": (extracted_fields or {}).get("user_side") or "unknown",
        "transaction_goal": (extracted_fields or {}).get("transaction_goal") or "unknown",
        "expected_transaction_time": (extracted_fields or {}).get("expected_transaction_time"),
        "asking_price_vnd": (extracted_fields or {}).get("asking_price_vnd"),
        "budget_vnd": (extracted_fields or {}).get("budget_vnd"),
        "transaction_advice": _transaction_advice_lines(result, prop, extracted_fields or {}),
        "transaction_advice_en": _transaction_advice_lines_en(result, prop, extracted_fields or {}),
    }
    if amenity_advice:
        context["amenity_advice"] = amenity_context(amenity_advice)
        context["amenity_text"] = " ".join(_amenity_summary_lines(amenity_advice))
    if news_data:
        context["news"] = news_data
    if outlook:
        context["outlook"] = outlook
    return context


def _transaction_advice_lines(
    result: ValuationResponse,
    prop: PropertyInput,
    fields: dict[str, Any],
) -> list[str]:
    user_side = compact_spaces(fields.get("user_side")).lower()
    goal = compact_spaces(fields.get("transaction_goal")).lower()
    expected_time = compact_spaces(fields.get("expected_transaction_time")).lower()
    asking_price = _float_or_none(fields.get("asking_price_vnd"))
    budget = _float_or_none(fields.get("budget_vnd"))
    lines: list[str] = []
    if result.purpose == "sale":
        if user_side == "buyer" and asking_price:
            lines.append(_buyer_asking_advice(result, asking_price))
        if user_side == "seller" and (goal == "quick_transaction" or expected_time in {"this_week", "this_month"}):
            quick_low = max(float(result.p10_total_vnd), float(result.p50_total_vnd) * 0.95)
            quick_high = min(float(result.p90_total_vnd), float(result.p50_total_vnd) * 0.98)
            listing_anchor = min(float(result.p90_total_vnd), float(result.p50_total_vnd) * 1.02)
            lines.append(
                "Nếu cần bán trong khoảng một tháng, nên đăng quanh "
                f"{_format_market_money(listing_anchor, 'sale')} nếu còn dư địa thương lượng; "
                f"vùng chốt nhanh nên chuẩn bị khoảng {_format_market_money_range(quick_low, quick_high, 'sale')}."
            )
        elif user_side == "seller" and goal == "maximize_price":
            lines.append(
                "Nếu ưu tiên tối đa giá bán hơn tốc độ, có thể neo giá chào gần nửa trên của khoảng tham chiếu, "
                "nhưng cần chứng minh bằng tòa, tầng, view và tình trạng nội thất."
            )
    elif result.purpose == "rent":
        if user_side == "tenant" and budget:
            position = _budget_position_text(budget, float(result.p10_total_vnd), float(result.p50_total_vnd), float(result.p90_total_vnd))
            lines.append(
                f"Với ngân sách {_format_market_money(budget, 'rent')}/tháng, mức này {position} "
                f"so với khoảng thuê {_format_market_money_range(result.p10_total_vnd, result.p90_total_vnd, 'rent')}/tháng."
            )
        elif user_side == "landlord" and goal == "quick_transaction":
            quick_low = max(float(result.p10_total_vnd), float(result.p50_total_vnd) * 0.95)
            quick_high = float(result.p50_total_vnd)
            lines.append(
                "Nếu muốn có khách thuê nhanh, nên ưu tiên vùng giá "
                f"{_format_market_money_range(quick_low, quick_high, 'rent')}/tháng và mô tả rõ nội thất, phí dịch vụ."
            )
    return lines[:2]


def _transaction_advice_lines_en(
    result: ValuationResponse,
    prop: PropertyInput,
    fields: dict[str, Any],
) -> list[str]:
    user_side = compact_spaces(fields.get("user_side")).lower()
    goal = compact_spaces(fields.get("transaction_goal")).lower()
    expected_time = compact_spaces(fields.get("expected_transaction_time")).lower()
    asking_price = _float_or_none(fields.get("asking_price_vnd"))
    budget = _float_or_none(fields.get("budget_vnd"))
    lines: list[str] = []
    if result.purpose == "sale":
        if user_side == "buyer" and asking_price:
            lines.append(_buyer_asking_advice_en(result, asking_price))
        if user_side == "seller" and (goal == "quick_transaction" or expected_time in {"this_week", "this_month"}):
            quick_low = max(float(result.p10_total_vnd), float(result.p50_total_vnd) * 0.95)
            quick_high = min(float(result.p90_total_vnd), float(result.p50_total_vnd) * 0.98)
            listing_anchor = min(float(result.p90_total_vnd), float(result.p50_total_vnd) * 1.02)
            lines.append(
                "If you need to sell within about one month, list around "
                f"{_format_market_money_en(listing_anchor, 'sale')} if you still want negotiation room; "
                f"a faster closing band is about {_format_market_money_range_en(quick_low, quick_high, 'sale')}."
            )
    elif result.purpose == "rent" and user_side == "tenant" and budget:
        position = _budget_position_text_en(budget, float(result.p10_total_vnd), float(result.p50_total_vnd), float(result.p90_total_vnd))
        lines.append(
            f"With a budget of {_format_market_money_en(budget, 'rent')}/month, this looks {position} "
            f"versus the rental band of {_format_market_money_range_en(result.p10_total_vnd, result.p90_total_vnd, 'rent')}/month."
        )
    return lines[:2]


def _buyer_asking_advice(result: ValuationResponse, asking_price: float) -> str:
    if asking_price > float(result.p90_total_vnd):
        position = "cao hơn vùng tham chiếu cao"
    elif asking_price >= float(result.p50_total_vnd):
        position = "nằm ở nửa trên của khoảng tham chiếu"
    elif asking_price >= float(result.p10_total_vnd):
        position = "nằm trong khoảng có thể cân nhắc"
    else:
        position = "thấp hơn mặt bằng tham chiếu, cần kiểm tra kỹ pháp lý/chất lượng căn"
    target_low = max(float(result.p10_total_vnd), float(result.p50_total_vnd) * 0.97)
    target_high = min(float(result.p90_total_vnd), asking_price, float(result.p50_total_vnd) * 1.02)
    return (
        f"Mức chủ nhà chào {_format_market_money(asking_price, 'sale')} đang {position}. "
        f"Nếu tòa, tầng, view hoặc nội thất không nổi bật, nên thương lượng về gần "
        f"{_format_market_money_range(target_low, target_high, 'sale')} trước khi chốt."
    )


def _buyer_asking_advice_en(result: ValuationResponse, asking_price: float) -> str:
    if asking_price > float(result.p90_total_vnd):
        position = "above the high side of the reference band"
    elif asking_price >= float(result.p50_total_vnd):
        position = "in the upper half of the reference band"
    elif asking_price >= float(result.p10_total_vnd):
        position = "within the negotiable reference band"
    else:
        position = "below the reference band, so legal status and unit quality need careful checking"
    target_low = max(float(result.p10_total_vnd), float(result.p50_total_vnd) * 0.97)
    target_high = min(float(result.p90_total_vnd), asking_price, float(result.p50_total_vnd) * 1.02)
    return (
        f"The seller's asking price of {_format_market_money_en(asking_price, 'sale')} is {position}. "
        f"If tower, floor, view, or furniture are not clearly strong, negotiate closer to "
        f"{_format_market_money_range_en(target_low, target_high, 'sale')} before closing."
    )


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _valuation_enrichment_policy(
    message: str,
    prop: PropertyInput,
    fields: dict[str, Any],
    runtime: ChatRuntime,
    prior_context: dict[str, Any] | None = None,
) -> dict[str, bool]:
    if not runtime.entitlement.is_pro:
        return {"map": False, "news": False, "outlook": False}
    can_map = bool(runtime.entitlement.flags.get("auto_map_enrichment"))
    can_news = bool(runtime.entitlement.flags.get("news_search"))
    explicit_map = _message_requests_map(message)
    explicit_news = _message_requests_news_or_outlook(message)
    has_prior_map = _context_has_project_enrichment(prior_context, "maps", prop.project)
    has_prior_news = _context_has_project_enrichment(prior_context, "news", prop.project)
    map_allowed = can_map and _has_location_for_map(prop) and (explicit_map or not has_prior_map)
    news_allowed = (
        can_news
        and _should_search_news_for_valuation(message, prop, fields)
        and (explicit_news or not has_prior_news)
    )
    outlook_allowed = news_allowed or _message_requests_outlook(message)
    return {"map": map_allowed, "news": news_allowed, "outlook": outlook_allowed}


def _has_location_for_map(prop: PropertyInput) -> bool:
    return bool(compact_spaces(prop.project))


def _context_has_project_enrichment(context: dict[str, Any] | None, key: str, project: str) -> bool:
    enrichment = (context or {}).get("enrichment")
    if not isinstance(enrichment, dict):
        return False
    data = enrichment.get(key)
    if not isinstance(data, dict):
        return False
    if key == "maps":
        prior_project = compact_spaces(data.get("project"))
        return not prior_project or text_key(prior_project) == text_key(project)
    if key == "news":
        items = data.get("items")
        return isinstance(items, list) and bool(items)
    return bool(data)


def _prior_enrichment_for_context(context: dict[str, Any] | None, project: str) -> dict[str, Any] | None:
    enrichment = (context or {}).get("enrichment")
    if not isinstance(enrichment, dict):
        return None
    maps = enrichment.get("maps")
    if isinstance(maps, dict):
        prior_project = compact_spaces(maps.get("project"))
        if prior_project and text_key(prior_project) != text_key(project):
            return None
    return enrichment


def _message_requests_map(message: str) -> bool:
    key = text_key(message)
    terms = (
        "tien ich",
        "tien tich",
        "xung quanh",
        "gan day",
        "gan do",
        "nearby",
        "around",
        "map",
        "ban do",
        "truong hoc",
        "sieu thi",
        "benh vien",
        "cong vien",
        "giao thong",
        "bus",
        "metro",
    )
    return any(term in key for term in terms)


def _should_search_news_for_valuation(message: str, prop: PropertyInput, fields: dict[str, Any]) -> bool:
    if _message_requests_news_or_outlook(message):
        return True
    user_side = compact_spaces(fields.get("user_side")).lower()
    goal = compact_spaces(fields.get("transaction_goal")).lower()
    if prop.purpose == "sale":
        return True
    return user_side in {"buyer", "seller"} or goal in {"investment", "maximize_price", "minimize_price"}


def _message_requests_news_or_outlook(message: str) -> bool:
    key = text_key(message)
    terms = (
        "tin tuc",
        "tin moi",
        "news",
        "su kien",
        "event",
        "quy hoach",
        "ha tang",
        "giao thong",
        "mo rong",
        "xay them",
        "xay moi",
        "thi cong",
        "sap mo",
        "sap xay",
        "tuong lai",
        "trien vong",
        "outlook",
        "mot nam",
        "1 nam",
        "nam nua",
        "thang 7",
        "anh huong den gia",
        "tang gia",
        "giam gia",
        "co tang",
        "co giam",
    )
    return any(term in key for term in terms)


def _message_requests_outlook(message: str) -> bool:
    key = text_key(message)
    terms = (
        "tuong lai",
        "trien vong",
        "outlook",
        "mot nam",
        "1 nam",
        "nam nua",
        "tang gia",
        "giam gia",
        "co tang",
        "co giam",
    )
    return any(term in key for term in terms)


def _valuation_amenity_advice(
    message: str,
    result: ValuationResponse,
    prop: PropertyInput,
    config: AppConfig,
) -> AmenityAdviceResponse | None:
    first = result.comparable_listings[0] if result.comparable_listings else None
    cache_key = _valuation_amenity_cache_key(prop, first)
    cached = _get_cached_valuation_amenity(cache_key)
    if cached is not None:
        return cached
    request = AmenityAdviceRequest(
        project=prop.project,
        purpose=prop.purpose,
        property_type=prop.property_type,
        address=first.address if first else None,
        subdivision=prop.subdivision or (first.subdivision if first else None),
        tower=prop.tower,
        max_places_per_category=3,
    )
    try:
        advice = build_amenity_advice(request, config, include_llm=False, message=message)
    except ValueError:
        return None
    _set_cached_valuation_amenity(cache_key, advice)
    return advice


def _valuation_amenity_cache_key(prop: PropertyInput, first: Any | None) -> tuple[str, ...]:
    subdivision = prop.subdivision or (getattr(first, "subdivision", None) if first else None)
    parts = (
        prop.project,
        prop.purpose,
        prop.property_type,
        subdivision,
        prop.tower,
    )
    return tuple(text_key(str(part or "")) for part in parts)


def _valuation_amenity_cache_ttl() -> int:
    raw_value = os.getenv("MAPS_ENRICHMENT_CACHE_TTL_SECONDS") or os.getenv("AMENITY_CACHE_TTL_SECONDS") or "1800"
    try:
        return max(0, int(raw_value))
    except ValueError:
        return 1800


def _get_cached_valuation_amenity(cache_key: tuple[str, ...]) -> AmenityAdviceResponse | None:
    ttl = _valuation_amenity_cache_ttl()
    if ttl <= 0:
        return None
    now = monotonic()
    with _VALUATION_AMENITY_CACHE_LOCK:
        cached = _VALUATION_AMENITY_CACHE.get(cache_key)
        if not cached:
            return None
        created_at, advice = cached
        if now - created_at > ttl:
            _VALUATION_AMENITY_CACHE.pop(cache_key, None)
            return None
        return advice.model_copy(deep=True)


def _set_cached_valuation_amenity(cache_key: tuple[str, ...], advice: AmenityAdviceResponse) -> None:
    ttl = _valuation_amenity_cache_ttl()
    if ttl <= 0:
        return
    with _VALUATION_AMENITY_CACHE_LOCK:
        _VALUATION_AMENITY_CACHE[cache_key] = (monotonic(), advice.model_copy(deep=True))


def _valuation_news(config: AppConfig, prop: PropertyInput, runtime: ChatRuntime) -> dict[str, Any] | None:
    if not runtime.entitlement.flags.get("news_search"):
        return None
    return _news_enrichment(config, prop.project, limit=4, location_label=_property_location_label(config, prop))


def _news_enrichment(
    config: AppConfig,
    project: str,
    limit: int = 4,
    *,
    location_label: str | None = None,
) -> dict[str, Any] | None:
    try:
        raw = project_news(config, project, limit=limit, location_label=location_label)
    except Exception:  # noqa: BLE001
        return {
            "status": "error",
            "items": [],
            "summary": "Chưa lấy được tin tức mới ở thời điểm này.",
        }
    items = []
    for item in raw.get("items") or []:
        title = compact_spaces(item.get("title"))
        url = compact_spaces(item.get("url"))
        if not title or not url:
            continue
        event_status = compact_spaces(item.get("event_status") or item.get("status")) or "unknown"
        proximity_status = compact_spaces(item.get("proximity_status")) or "unverified"
        evidence_strength = compact_spaces(item.get("evidence_strength")) or "low"
        items.append(
            {
                "title": title,
                "source": compact_spaces(item.get("source_name") or item.get("source")) or "Nguồn tin",
                "source_name": compact_spaces(item.get("source_name") or item.get("source")) or "Nguồn tin",
                "published_text": compact_spaces(item.get("published_text")),
                "published_at": compact_spaces(item.get("published_at")),
                "url": url,
                "source_url": url,
                "aspect": compact_spaces(item.get("affected_aspect") or item.get("aspect")) or _news_aspect(title),
                "affected_aspect": compact_spaces(item.get("affected_aspect") or item.get("aspect")) or _news_aspect(title),
                "direction": compact_spaces(item.get("impact_direction") or item.get("direction")) or "monitor",
                "impact_direction": compact_spaces(item.get("impact_direction") or item.get("direction")) or "monitor",
                "horizon": compact_spaces(item.get("impact_horizon") or item.get("horizon")) or "short",
                "impact_horizon": compact_spaces(item.get("impact_horizon") or item.get("horizon")) or "short",
                "status": event_status,
                "event_status": event_status,
                "evidence_strength": evidence_strength,
                "proximity_status": proximity_status,
                "proximity_text": compact_spaces(item.get("proximity_text")),
                "distance_m": item.get("distance_m"),
                "distance_km": item.get("distance_km"),
                "matched_location": item.get("matched_location"),
                "event_date": item.get("event_date"),
                "expected_end_date": item.get("expected_end_date"),
                "summary": compact_spaces(item.get("summary")),
                "main_insight": (
                    proximity_status == "verified_nearby"
                    and evidence_strength != "low"
                    and event_status not in {"unknown", "rumored"}
                ),
            }
        )
    return {
        "status": raw.get("status") or "ok",
        "project": raw.get("project") or _project_display(project),
        "location_context": raw.get("location_context"),
        "nearby_verified_count": raw.get("nearby_verified_count") or 0,
        "generated_at": raw.get("generated_at"),
        "items": items[:limit],
        "summary": raw.get("summary") or _news_summary_from_items(items),
    }


def _build_outlook(result: ValuationResponse, prop: PropertyInput, news_data: dict[str, Any] | None) -> dict[str, Any]:
    spread_ratio = (result.p90_total_vnd - result.p10_total_vnd) / max(result.p50_total_vnd, 1)
    if result.confidence == "high" and spread_ratio <= 0.35:
        tone = "ổn định"
        risk = "biên thương lượng không quá rộng"
    elif spread_ratio >= 0.65:
        tone = "cần thận trọng"
        risk = "khoảng thương lượng còn rộng"
    else:
        tone = "trung tính"
        risk = "cần đối chiếu thêm tầng, view và nội thất"
    news_items = (news_data or {}).get("items") or []
    verified_news = [
        item
        for item in news_items
        if item.get("proximity_status") == "verified_nearby"
        and item.get("event_status") not in {"unknown", "rumored"}
        and item.get("evidence_strength") != "low"
    ]
    positive_factors = [
        _news_factor_text(item)
        for item in verified_news
        if item.get("impact_direction") in {"positive", "mixed"}
    ][:3]
    risk_factors = [
        _news_factor_text(item)
        for item in verified_news
        if item.get("impact_direction") in {"negative", "mixed"}
    ][:3]
    if positive_factors and not risk_factors:
        direction = "neutral_to_positive"
    elif risk_factors and not positive_factors:
        direction = "neutral"
    elif positive_factors and risk_factors:
        direction = "unclear"
    else:
        direction = "neutral"
    confidence = "medium" if verified_news and result.confidence in {"medium", "high"} else "low"
    news_note = (
        f" Có {len(verified_news)} sự kiện gần vị trí đã xác minh để theo dõi."
        if verified_news
        else " Chưa có sự kiện gần vị trí được xác minh; các tin còn lại chỉ nên dùng như bối cảnh khu vực."
    )
    return {
        "tone": tone,
        "risk": risk,
        "direction": direction,
        "horizon": "1-3 months" if verified_news else "3-6 months",
        "confidence": confidence,
        "summary": f"Triển vọng ngắn hạn: {tone}; {risk}.{news_note}",
        "summary_en": f"Short-term outlook: {tone}; {risk}.{news_note}",
        "positive_factors": positive_factors,
        "risk_factors": risk_factors,
        "reasoning_notes": [
            "Chỉ tính tin gần vị trí khi đã xác minh khoảng cách bằng provider bản đồ.",
            "Không tạo dự báo phần trăm tăng/giảm giá từ tin tức.",
        ],
        "drivers": [
            "chất lượng căn và tốc độ cần giao dịch",
            "mặt bằng tiện ích quanh vị trí",
            "diễn biến tin tức và nguồn cung trong khu",
        ],
        "no_appreciation_forecast": True,
    }


def _property_location_label(config: AppConfig, prop: PropertyInput) -> str:
    slug = infer_project_slug(config, prop.project, default=prop.project)
    project_cfg = config.project_by_slug.get(str(slug or ""))
    project_name = project_cfg.name if project_cfg else compact_spaces(prop.project)
    district = compact_spaces(project_cfg.district_hint if project_cfg else "")
    market = config.raw.get("market") if isinstance(config.raw, dict) else None
    city = compact_spaces((market or {}).get("city") if isinstance(market, dict) else "") or "Hà Nội"
    parts = [prop.tower, prop.subdivision, project_name, district, city]
    cleaned: list[str] = []
    seen: set[str] = set()
    for part in parts:
        text = compact_spaces(part)
        key = text_key(text)
        if text and key not in seen:
            cleaned.append(text)
            seen.add(key)
    return ", ".join(cleaned)


def _project_location_label(config: AppConfig, project: str) -> str:
    slug = infer_project_slug(config, project, default=project)
    project_cfg = config.project_by_slug.get(str(slug or ""))
    project_name = project_cfg.name if project_cfg else compact_spaces(project)
    district = compact_spaces(project_cfg.district_hint if project_cfg else "")
    market = config.raw.get("market") if isinstance(config.raw, dict) else None
    city = compact_spaces((market or {}).get("city") if isinstance(market, dict) else "") or "Hà Nội"
    return ", ".join(part for part in (project_name, district, city) if compact_spaces(part))


def _trend_outlook(data: dict[str, Any], news_data: dict[str, Any] | None) -> dict[str, Any]:
    windows = data.get("windows") or {}
    primary = windows.get("1m") or windows.get("3m") or {}
    sample = int(primary.get("sample_size") or 0)
    tone = "cần theo dõi thêm" if sample < 10 else "có thể dùng làm tham chiếu ngắn hạn"
    news_count = len((news_data or {}).get("items") or [])
    return {
        "tone": tone,
        "summary": f"Xu hướng hiện {tone}; nên đối chiếu thêm tin mới và mặt bằng căn cụ thể.",
        "drivers": ["thanh khoản gần đây", "nguồn cung cùng phân khúc", "tin tức thị trường"],
        "news_count": news_count,
        "no_appreciation_forecast": True,
    }


def _news_only_outlook(news_data: dict[str, Any] | None) -> dict[str, Any]:
    news_items = (news_data or {}).get("items") or []
    verified = [
        item
        for item in news_items
        if item.get("proximity_status") == "verified_nearby"
        and item.get("event_status") not in {"unknown", "rumored"}
        and item.get("evidence_strength") != "low"
    ]
    has_positive = any(str(item.get("impact_direction")) == "positive" for item in verified)
    has_negative = any(str(item.get("impact_direction")) == "negative" for item in verified)
    if has_positive and has_negative:
        direction = "mixed"
        tone = "có cả yếu tố hỗ trợ và rủi ro"
    elif has_positive:
        direction = "neutral_to_positive"
        tone = "nghiêng trung tính đến tích cực"
    elif has_negative:
        direction = "neutral_to_negative"
        tone = "cần thận trọng trong ngắn hạn"
    else:
        direction = "unclear"
        tone = "chưa đủ cơ sở kết luận"
    return {
        "direction": direction,
        "horizon": "3-6 months" if verified else "unclear",
        "confidence": "medium" if verified else "low",
        "summary": f"Triển vọng theo tin tức hiện {tone}; chưa phải cam kết giá sẽ tăng hoặc giảm.",
        "drivers": [_news_factor_text(item) for item in verified[:3]],
        "news_count": len(news_items),
        "verified_news_count": len(verified),
        "no_appreciation_forecast": True,
    }


def _enrichment_payload(
    amenity_advice: AmenityAdviceResponse | None,
    news_data: dict[str, Any] | None,
    outlook: dict[str, Any] | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if amenity_advice:
        payload["maps"] = {
            "status": "ok",
            "project": amenity_advice.project,
            "location_label": amenity_advice.location_label,
            "base_map_url": amenity_advice.base_map_url,
            "categories": [
                {
                    "key": category.key,
                    "label": category.label,
                    "map_url": category.map_url,
                    "places": [
                        {
                            "name": place.name,
                            "address": place.address,
                            "rating": place.rating,
                            "distance_m": place.distance_m,
                            "maps_url": place.maps_url,
                        }
                        for place in category.places[:3]
                    ],
                }
                for category in amenity_advice.categories[:6]
            ],
        }
    if news_data:
        payload["news"] = news_data
    if outlook:
        payload["outlook"] = outlook
    return payload


def _amenity_summary_lines(advice: AmenityAdviceResponse) -> list[str]:
    lines = list(advice.advisory_notes[:2])
    populated = [category for category in advice.categories if category.places]
    if populated:
        names = []
        for category in populated[:3]:
            first_place = category.places[0]
            names.append(f"{category.label}: {first_place.name}")
        lines.append("Một số điểm nên kiểm tra trên map: " + "; ".join(names) + ".")
    else:
        labels = ", ".join(category.label.lower() for category in advice.categories[:4])
        lines.append(f"Đã chuẩn bị truy vấn map cho {labels}; mở từng nhóm để xem kết quả thực tế quanh căn.")
    return lines[:3]


def _news_aspect(title: str) -> str:
    key = text_key(title)
    if any(term in key for term in ("lai suat", "tin dung", "ngan hang")):
        return "finance"
    if any(term in key for term in ("ha tang", "duong", "metro", "giao thong")):
        return "infrastructure"
    if any(term in key for term in ("phap ly", "quy hoach", "chinh sach")):
        return "policy"
    if any(term in key for term in ("nguon cung", "mo ban", "ban giao")):
        return "supply"
    return "market"


def _news_summary_from_items(items: list[dict[str, Any]]) -> str:
    if not items:
        return "Chưa có tin mới đủ rõ để đưa vào nhận định."
    verified = [item for item in items if item.get("proximity_status") == "verified_nearby"]
    first = verified[0] if verified else items[0]
    source = f" ({first.get('source')})" if first.get("source") else ""
    distance = _news_distance_text(first)
    if verified:
        return f"Tin gần vị trí cần theo dõi: {first.get('title')}{source}{f', {distance}' if distance else ''}."
    return f"Tin khu vực cần theo dõi, chưa xác minh khoảng cách: {first.get('title')}{source}."


def _news_summary_sentence(news_data: dict[str, Any]) -> str:
    items = news_data.get("items") or []
    if not items:
        return "Tin tức: hiện chưa có sự kiện mới đủ rõ để đưa vào khuyến nghị."
    verified = [item for item in items if item.get("proximity_status") == "verified_nearby"]
    first = verified[0] if verified else items[0]
    source = first.get("source") or "nguồn tin"
    status = _news_status_label(first.get("event_status") or first.get("status"))
    distance = _news_distance_text(first)
    if verified:
        return f"Tin gần vị trí cần theo dõi: {first.get('title')} ({source}, {status}{f', {distance}' if distance else ''})."
    return f"Tin tức khu vực cần theo dõi: {first.get('title')} ({source}); hiện chưa xác minh được khoảng cách tới vị trí định giá."


def _news_summary_sentence_en(news_data: dict[str, Any]) -> str:
    items = news_data.get("items") or []
    if not items:
        return "News: there is no clear new event to add to the recommendation right now."
    verified = [item for item in items if item.get("proximity_status") == "verified_nearby"]
    first = verified[0] if verified else items[0]
    source = first.get("source") or "source"
    status = first.get("event_status") or first.get("status") or "unknown"
    distance = _news_distance_text(first)
    if verified:
        return f"Nearby news to watch: {first.get('title')} ({source}, {status}{f', {distance}' if distance else ''})."
    return f"Area news to monitor: {first.get('title')} ({source}); distance to the valuation location has not been verified."


def _news_factor_text(item: dict[str, Any]) -> str:
    title = compact_spaces(item.get("title"))
    source = compact_spaces(item.get("source"))
    status = _news_status_label(item.get("event_status") or item.get("status"))
    distance = _news_distance_text(item)
    meta = ", ".join(part for part in (source, status, distance) if part)
    return f"{title}{f' ({meta})' if meta else ''}"


def _news_distance_text(item: dict[str, Any]) -> str:
    distance_km = item.get("distance_km")
    try:
        value = float(distance_km)
    except (TypeError, ValueError):
        return ""
    return f"cách khoảng {value:.1f} km".replace(".", ",")


def _news_status_label(value: object) -> str:
    return {
        "completed": "đã hoàn thành",
        "under_construction": "đang thi công",
        "officially_announced": "đã công bố",
        "confirmed": "đã xác nhận",
        "proposed": "đề xuất/nghiên cứu",
        "rumored": "chưa xác thực",
        "unknown": "chưa rõ trạng thái",
        "reference": "tin tham khảo",
    }.get(str(value or "unknown"), str(value or "chưa rõ trạng thái"))


def _amenity_price_lines(advice: AmenityAdviceResponse, result: ValuationResponse) -> list[str]:
    verb = "giá thuê" if result.purpose == "rent" else "giá bán"
    lines: list[str] = []
    populated = [category for category in advice.categories if category.places]
    if populated:
        for category in populated[:4]:
            names = ", ".join(place.name for place in category.places[:2])
            lines.append(
                f"{category.label}: có {names} gần đây, là yếu tố thường nâng đỡ {verb} của căn."
            )
        lines.append(
            "Càng nhiều tiện ích thiết yếu như giao thông, siêu thị và y tế trong bán kính đi bộ thì "
            f"{verb} càng dễ nằm ở nhóm cao của khoảng ước tính."
        )
    else:
        labels = ", ".join(category.label.lower() for category in advice.categories[:4])
        lines.append(
            f"Có thể mở các nhóm {labels} trên bản đồ để đối chiếu khoảng cách thực tế, từ đó đánh giá {verb} nên nằm gần phần cao hay thấp của khoảng."
        )
    return lines[:5]


def _amenity_price_lines_en(advice: AmenityAdviceResponse, result: ValuationResponse) -> list[str]:
    noun = "rent" if result.purpose == "rent" else "sale price"
    lines: list[str] = []
    populated = [category for category in advice.categories if category.places]
    if populated:
        for category in populated[:4]:
            names = ", ".join(place.name for place in category.places[:2])
            lines.append(f"{category.label}: nearby options include {names}, which can support {noun} positioning.")
    else:
        labels = ", ".join(category.label.lower() for category in advice.categories[:4])
        lines.append(f"Open the {labels} map groups to verify real distance before positioning the {noun} near the high or low side of the band.")
    return lines[:5]


def _valuation_analysis_lines(result: ValuationResponse, prop: PropertyInput) -> list[str]:
    area_text = _format_area(prop.area_m2)
    bedroom_text = f"{prop.bedrooms}PN " if prop.bedrooms is not None else ""
    lines = [
        f"Diện tích {area_text} thuộc nhóm {bedroom_text}{_property_type_label(result.property_type)} tại {result.project}.",
    ]
    proxy_note = _proxy_scope_note(result)
    if proxy_note:
        lines.append(proxy_note)
    comp_range = _comparable_range_text(result)
    if comp_range:
        lines.append(comp_range)
    verified_count = _verified_comparable_count(result)
    if verified_count:
        lines.append("Có thêm nguồn giao dịch đã xác thực để đối chiếu, nên mức tham chiếu đáng tin hơn.")
    else:
        lines.append("Nguồn giao dịch chốt phù hợp còn hạn chế, nên cần giữ biên thương lượng khi ra quyết định.")
    return lines


def _valuation_adjustment_lines(result: ValuationResponse, prop: PropertyInput) -> list[str]:
    if result.purpose == "rent":
        positive = [
            "+ Full nội thất: mức trung vị sẽ sát nhóm giá tốt hơn nếu căn đúng full nội thất; dữ liệu hiện tại chưa đủ căn trống/cơ bản để tách riêng premium.",
            "+ View hồ/công viên/nội khu: có thể kéo giá thuê lên nếu view thật sự thoáng; cần view/hướng cụ thể để lượng hóa.",
            "+ Tòa/phân khu tốt và tầng đẹp: có thể tăng giá khi gần tiện ích, sảnh/thang thuận tiện, tầng không quá thấp hoặc quá cao.",
        ]
        negative = [
            "- Nội thất cơ bản hoặc căn trống: thường thấp hơn nhóm full nội thất tương tự.",
            "- View bí/đối diện tòa khác, tầng bất tiện hoặc xa tiện ích: thường làm giá thuê giảm.",
        ]
    else:
        positive = [
            "+ Full nội thất/hoàn thiện đẹp: có thể hỗ trợ giá bán nếu người mua vào ở ngay.",
            "+ View hồ/công viên/nội khu và tầng đẹp: thường giúp thanh khoản và mức chào bán tốt hơn.",
            "+ Tòa/phân khu có tiện ích, pháp lý và vận hành tốt: có thể kéo giá lên so với mặt bằng chung.",
        ]
        negative = [
            "- Nội thất xuống cấp hoặc cần sửa chữa: thường làm người mua chiết khấu khi đàm phán.",
            "- View bí, tầng kém thuận tiện hoặc xa tiện ích: thường làm giá bán thấp hơn nhóm đẹp.",
        ]
    if prop.furniture == "full":
        positive[0] = "+ Full nội thất: giúp căn dễ thuyết phục nhóm khách muốn vào ở hoặc khai thác ngay."
    elif prop.furniture in {"basic", "empty"}:
        negative[0] = "- Nội thất cơ bản/trống: thường cần chiết khấu so với căn hoàn thiện đẹp."
    if prop.view:
        positive[1] = f"+ View {prop.view}: nếu view thật sự thoáng, có thể hỗ trợ thanh khoản và mức chào."
    return positive + negative


def _valuation_adjustment_lines_en(result: ValuationResponse, prop: PropertyInput) -> list[str]:
    if result.purpose == "rent":
        positive = [
            "+ Full furniture: supports the rental level when the unit is truly move-in ready.",
            "+ Open park, lake, or internal view: can support rent if the actual view is clear.",
            "+ Strong tower/subdivision and convenient floor: can help when lobby, lifts, and daily amenities are easy to access.",
        ]
        negative = [
            "- Basic or empty furniture: usually needs a discount versus a fully furnished unit.",
            "- Blocked view, inconvenient floor, or weaker amenity access: can reduce rental appeal.",
        ]
    else:
        positive = [
            "+ Full furniture or good finishing: can support the sale price for buyers who want to move in quickly.",
            "+ Open park, lake, or internal view and a good floor: can improve liquidity and asking-price strength.",
            "+ Tower/subdivision with strong amenities, legal clarity, and good operations: can position the unit above the average band.",
        ]
        negative = [
            "- Worn furniture or repair needs: usually gives buyers room to negotiate a discount.",
            "- Blocked view, inconvenient floor, or weaker amenity access: can pull the sale price below stronger units.",
        ]
    if prop.furniture == "full":
        positive[0] = "+ Full furniture: helps persuade buyers or tenants who want immediate use."
    elif prop.furniture in {"basic", "empty"}:
        negative[0] = "- Basic or empty furniture: usually needs a discount versus well-finished units."
    if prop.view:
        positive[1] = f"+ {prop.view.title()} view: if the view is genuinely open, it can support liquidity and pricing."
    return positive + negative


def _missing_optional_detail_lines(prop: PropertyInput) -> list[str]:
    missing = []
    if not prop.subdivision and not prop.tower:
        missing.append("Tòa/phân khu")
    if prop.floor_number is None:
        missing.append("Tầng")
    if not prop.furniture:
        missing.append("Tình trạng nội thất")
    if not prop.view:
        missing.append("Hướng ban công/view")
    return missing


def _missing_optional_detail_lines_en(prop: PropertyInput) -> list[str]:
    missing = []
    if not prop.subdivision and not prop.tower:
        missing.append("tower or subdivision")
    if prop.floor_number is None:
        missing.append("floor number")
    if not prop.furniture:
        missing.append("furniture condition")
    if not prop.view:
        missing.append("balcony direction or view")
    return missing


def _proxy_scope_note(result: ValuationResponse) -> str | None:
    comps = result.comparable_listings
    if not comps:
        return None
    same_project = sum(1 for item in comps if item.project == result.project)
    if same_project >= max(1, len(comps) // 2):
        return None
    return (
        f"Nguồn cùng dự án còn mỏng, nên cần đối chiếu thêm nhóm {_property_type_label(result.property_type)} "
        "tương tự trong các khu Vinhomes Hà Nội."
    )


def _comparable_range_text(result: ValuationResponse) -> str | None:
    values = []
    for item in result.comparable_listings:
        value = item.rent_monthly_vnd if result.purpose == "rent" else item.price_total_vnd
        if value:
            values.append(float(value))
    if not values:
        return None
    verb = "chào thuê" if result.purpose == "rent" else "chào bán"
    suffix = "/tháng" if result.purpose == "rent" else ""
    return (
        f"Các căn tương tự đang được {verb} quanh "
        f"{_format_market_money_range(min(values), max(values), result.purpose)}{suffix}."
    )


def _verified_comparable_count(result: ValuationResponse) -> int:
    # ComparableListing intentionally hides storage internals; verified rows currently have no public source_url.
    return sum(1 for item in result.comparable_listings if not item.source_url)


def _public_factor_text(value: str) -> str:
    text = compact_spaces(value)
    replacements = {
        "listing": "thông tin thị trường",
        "Dataset": "Nguồn thị trường",
        "dataset": "nguồn thị trường",
        "P10-P90": "khoảng thấp-cao",
        "P10": "mức thấp",
        "P50": "mức tham chiếu",
        "P90": "mức cao",
        "top mẫu so sánh": "nhóm căn tương tự",
        "sample size": "độ phủ dữ liệu",
        "giao dịch sau lọc nhiễu": "thông tin đã kiểm tra",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _public_factor_text_en(value: str) -> str:
    text = _public_factor_text(value)
    return (
        text.replace("Full nội thất", "Full furniture")
        .replace("View", "View")
        .replace("Nội thất cơ bản/trống", "Basic or empty furniture")
    )


def _confidence_label(value: str | None) -> str:
    return {"low": "cần đối chiếu thêm", "medium": "khá", "high": "tốt"}.get(value or "", "khá")


def _confidence_label_en(value: str | None) -> str:
    return {"low": "needs more cross-checking", "medium": "moderate", "high": "good"}.get(value or "", "moderate")


def _bedroom_suffix(prop: PropertyInput) -> str:
    return f" {prop.bedrooms}PN" if prop.bedrooms is not None else ""


def _bedroom_suffix_en(prop: PropertyInput) -> str:
    return f" {prop.bedrooms}-bedroom" if prop.bedrooms is not None else ""


def _project_display(value: object) -> str:
    text = compact_spaces(value)
    if not text:
        return "khu vực này"
    return text.replace("-", " ").title() if text == text.lower() else text


def _confidence_percent(result: ValuationResponse) -> int:
    score = {"low": 52, "medium": 68, "high": 78}.get(result.confidence, 60)
    if result.sample_size >= 100:
        score += 6
    elif result.sample_size >= 50:
        score += 4
    elif result.sample_size < 15:
        score -= 5
    if result.p50_total_vnd:
        spread_ratio = (result.p90_total_vnd - result.p10_total_vnd) / max(result.p50_total_vnd, 1)
        if spread_ratio < 0.25:
            score += 4
        elif spread_ratio > 0.8:
            score -= 4
    return max(40, min(88, int(round(score))))


def _format_area(value: float | int | None) -> str:
    if value is None:
        return ""
    number = float(value)
    return f"{number:.0f}m²" if number.is_integer() else f"{number:.1f}m²"


def _format_market_money(value: float | int | None, purpose: str) -> str:
    if value is None:
        return "N/A"
    value = float(value)
    if purpose == "rent":
        return f"{_trim_decimal(value / 1_000_000)} triệu"
    if value >= 1_000_000_000:
        return f"{_trim_decimal(value / 1_000_000_000, digits=2)} tỷ"
    if value >= 1_000_000:
        return f"{_trim_decimal(value / 1_000_000)} triệu"
    return f"{value:,.0f} VND"


def _format_market_money_range(low: float | int | None, high: float | int | None, purpose: str) -> str:
    if low is None or high is None:
        return f"{_format_market_money(low, purpose)} - {_format_market_money(high, purpose)}"
    low_value = float(low)
    high_value = float(high)
    if purpose == "rent":
        return f"{_trim_decimal(low_value / 1_000_000)} - {_trim_decimal(high_value / 1_000_000)} triệu"
    if low_value >= 1_000_000_000 and high_value >= 1_000_000_000:
        return f"{_trim_decimal(low_value / 1_000_000_000, digits=2)} - {_trim_decimal(high_value / 1_000_000_000, digits=2)} tỷ"
    if low_value >= 1_000_000 and high_value >= 1_000_000:
        return f"{_trim_decimal(low_value / 1_000_000)} - {_trim_decimal(high_value / 1_000_000)} triệu"
    return f"{low_value:,.0f} - {high_value:,.0f} VND"


def _format_market_money_en(value: float | int | None, purpose: str) -> str:
    if value is None:
        return "N/A"
    value = float(value)
    if purpose == "rent":
        return f"{_trim_decimal(value / 1_000_000)} million VND"
    if value >= 1_000_000_000:
        return f"{_trim_decimal(value / 1_000_000_000, digits=2)} billion VND"
    if value >= 1_000_000:
        return f"{_trim_decimal(value / 1_000_000)} million VND"
    return f"{value:,.0f} VND"


def _format_market_money_range_en(low: float | int | None, high: float | int | None, purpose: str) -> str:
    if low is None or high is None:
        return f"{_format_market_money_en(low, purpose)} - {_format_market_money_en(high, purpose)}"
    low_value = float(low)
    high_value = float(high)
    if purpose == "rent":
        return f"{_trim_decimal(low_value / 1_000_000)} - {_trim_decimal(high_value / 1_000_000)} million VND"
    if low_value >= 1_000_000_000 and high_value >= 1_000_000_000:
        return f"{_trim_decimal(low_value / 1_000_000_000, digits=2)} - {_trim_decimal(high_value / 1_000_000_000, digits=2)} billion VND"
    if low_value >= 1_000_000 and high_value >= 1_000_000:
        return f"{_trim_decimal(low_value / 1_000_000)} - {_trim_decimal(high_value / 1_000_000)} million VND"
    return f"{low_value:,.0f} - {high_value:,.0f} VND"


def _valuation_price_per_m2_text(result: ValuationResponse) -> str:
    if not result.p50_price_per_m2_vnd:
        return ""
    suffix = "/tháng" if result.purpose == "rent" else ""
    return f"Giá trung vị theo m2 khoảng {_format_market_money(result.p50_price_per_m2_vnd, result.purpose)}/m2{suffix}."


def _valuation_top_factor_text(result: ValuationResponse) -> str:
    factors = [_public_factor_text(factor) for factor in result.top_factors if factor]
    if not factors:
        return ""
    return "Yếu tố ảnh hưởng chính: " + "; ".join(factors[:3]) + "."


def _trim_decimal(value: float, digits: int = 1) -> str:
    text = f"{value:.{digits}f}"
    return text.rstrip("0").rstrip(".")


def _format_vnd(value: float | int | None) -> str:
    if value is None:
        return "N/A"
    value = float(value)
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f} tỷ VND"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f} triệu VND"
    return f"{value:,.0f} VND"


def _format_vnd_en(value: float | int | None) -> str:
    if value is None:
        return "N/A"
    value = float(value)
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f} billion VND"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f} million VND"
    return f"{value:,.0f} VND"


def _price_per_m2_text(value: float | int | None) -> str:
    return f"Đơn giá tham chiếu khoảng {_format_vnd(value)}/m2. " if value else ""


def _top_factor_text(factors: list[str]) -> str:
    return f"Yếu tố chính: {factors[0]}" if factors else ""


def _snapshot_count_text(count: int) -> str:
    return f"Có thêm {count} snapshot bảng giá để đối chiếu." if count else ""


def _snapshot_count_text_en(count: int) -> str:
    return f"There are {count} additional reference price snapshots for cross-checking." if count else ""


def _purpose_label(value: str | None) -> str:
    return {"sale": "bán", "rent": "thuê"}.get(value or "", value or "")


def _purpose_label_en(value: str | None) -> str:
    return {"sale": "sale", "rent": "rent"}.get(value or "", value or "")


def _property_type_label(value: str | None) -> str:
    return {
        "apartment": "căn hộ",
        "villa": "biệt thự",
        "townhouse": "liền kề",
        "shophouse": "shophouse",
        "house": "nhà phố",
        "other": "BĐS",
        "all": "tất cả loại hình",
    }.get(value or "", value or "")


def _property_type_label_en(value: str | None) -> str:
    return {
        "apartment": "apartment",
        "villa": "villa",
        "townhouse": "townhouse",
        "shophouse": "shophouse",
        "house": "house",
        "other": "property",
        "all": "all property types",
    }.get(value or "", value or "")
