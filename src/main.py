from __future__ import annotations

import os
from datetime import UTC, datetime

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.amenities import build_amenity_advice
from src.auth import bearer_token, current_user_from_token, login_user, register_user
from src.chatbot import handle_chat
from src.config import load_config
from src.crawler import crawl_once
from src.database import DEFAULT_DB_PATH
from src.entitlements import resolve_entitlement
from src.env import load_app_env, resolve_project_path
from src.evaluation import evaluate_market_data
from src.news import project_news
from src.normalization import infer_project_slug
from src.payments import check_payment_order, create_pro_order, get_payment_order
from src.rate_limit import enforce_rate_limit
from src.schemas import (
    AmenityAdviceRequest,
    AmenityAdviceResponse,
    AuthLoginRequest,
    AuthRegisterRequest,
    AuthTokenResponse,
    AuthUser,
    ChatRequest,
    ChatResponse,
    CrawlResponse,
    DataEvaluationResponse,
    MarketTrendResponse,
    PaymentOrderRequest,
    PaymentOrderResponse,
    PriceSnapshotReference,
    PropertyInput,
    ValuationResponse,
    VerifiedTransactionInput,
)
from src.security import (
    bearer_or_key,
    require_admin_api_key,
    should_allow_direct_request,
    valid_admin_api_key,
    valid_internal_proxy_key,
)
from src.storage import get_store, init_storage
from src.valuation import estimate_property, market_trends, price_snapshot_references
from src.zalo_format import format_zalo_chat_response

load_app_env()
CONFIG_PATH = resolve_project_path(os.getenv("VALUATION_CONFIG_PATH", "config/projects.yaml"))
DB_PATH = resolve_project_path(os.getenv("VALUATION_DB_PATH", str(DEFAULT_DB_PATH)))
DEFAULT_CORS_ORIGINS = (
    "http://localhost:2707,http://127.0.0.1:2707,"
    "http://localhost:5173,http://127.0.0.1:5173,"
    "https://solanai.us,https://www.solanai.us"
)
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("VALUATION_CORS_ORIGINS", DEFAULT_CORS_ORIGINS).split(",")
    if origin.strip()
]

app = FastAPI(title="Vinhomes Hanoi Valuation API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PUBLIC_PATHS = {"/health"}
ADMIN_PATHS = {"/ingest/crawl", "/verified-transactions"}


@app.middleware("http")
async def protect_public_api(request: Request, call_next):
    if request.url.path in PUBLIC_PATHS:
        return await call_next(request)
    allowed_request = should_allow_direct_request(request) or valid_internal_proxy_key(
        request.headers.get("x-internal-proxy-key")
    )
    if not allowed_request:
        return JSONResponse(status_code=403, content={"detail": "API chỉ nhận request qua proxy của ứng dụng."})
    if request.url.path in ADMIN_PATHS:
        admin_key = bearer_or_key(
            request.headers.get("authorization"),
            request.headers.get("x-admin-api-key"),
        )
        if not valid_admin_api_key(admin_key):
            return JSONResponse(status_code=401, content={"detail": "Thiếu hoặc sai Admin API Key."})
    return await call_next(request)


@app.on_event("startup")
def startup() -> None:
    init_storage(DB_PATH)


def config():
    return load_config(CONFIG_PATH)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/projects")
def projects() -> list[dict[str, str | list[str] | None]]:
    cfg = config()
    return [
        {
            "slug": project.slug,
            "name": project.name,
            "aliases": list(project.aliases),
            "district_hint": project.district_hint,
        }
        for project in cfg.projects
    ]


@app.post("/auth/register", response_model=AuthTokenResponse)
def auth_register(payload: AuthRegisterRequest, request: Request):
    enforce_rate_limit(request, "auth_register", default_limit=10)
    try:
        return register_user(payload, DB_PATH)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/auth/login", response_model=AuthTokenResponse)
def auth_login(payload: AuthLoginRequest, request: Request):
    enforce_rate_limit(request, "auth_login", default_limit=20)
    try:
        return login_user(payload, DB_PATH)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.get("/auth/me", response_model=AuthUser)
def auth_me(
    request: Request,
    authorization: str | None = Header(default=None),
):
    enforce_rate_limit(request, "auth_me", default_limit=120)
    try:
        return current_user_from_token(bearer_token(authorization), DB_PATH)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.post("/payments/pro-order", response_model=PaymentOrderResponse)
def payment_create_pro_order(
    payload: PaymentOrderRequest,
    request: Request,
    authorization: str | None = Header(default=None),
):
    enforce_rate_limit(request, "payment_create", default_limit=20)
    try:
        user = current_user_from_token(bearer_token(authorization), DB_PATH)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    try:
        return create_pro_order(user, payload, DB_PATH)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/payments/{order_code}", response_model=PaymentOrderResponse)
def payment_status(
    order_code: str,
    request: Request,
    authorization: str | None = Header(default=None),
):
    enforce_rate_limit(request, "payment_status", default_limit=120)
    try:
        user = current_user_from_token(bearer_token(authorization), DB_PATH)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    try:
        return get_payment_order(user, order_code, DB_PATH)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/payments/{order_code}/check", response_model=PaymentOrderResponse)
def payment_check(
    order_code: str,
    request: Request,
    authorization: str | None = Header(default=None),
):
    enforce_rate_limit(request, "payment_check", default_limit=30)
    try:
        user = current_user_from_token(bearer_token(authorization), DB_PATH)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    try:
        return check_payment_order(user, order_code, DB_PATH)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/ingest/crawl", response_model=CrawlResponse)
def ingest_crawl(
    limit: int | None = None,
    source: str | None = None,
    authorization: str | None = Header(default=None),
    x_admin_api_key: str | None = Header(default=None, alias="X-Admin-API-Key"),
):
    require_admin_api_key(authorization, x_admin_api_key)
    try:
        return crawl_once(config(), DB_PATH, limit=limit, source_filter=source)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/valuation", response_model=ValuationResponse)
def valuation(payload: PropertyInput, request: Request):
    enforce_rate_limit(request, "valuation", default_limit=120)
    try:
        return estimate_property(payload, config(), DB_PATH)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/market-trends", response_model=MarketTrendResponse)
def trends(
    request: Request,
    project: str,
    purpose: str = "sale",
    property_type: str | None = None,
    bedrooms: int | None = None,
):
    enforce_rate_limit(request, "market_trends", default_limit=180)
    try:
        return market_trends(config(), project, purpose, property_type, bedrooms, DB_PATH)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/price-snapshots", response_model=list[PriceSnapshotReference])
def price_snapshots(
    request: Request,
    project: str,
    purpose: str = "sale",
    property_type: str | None = None,
    limit: int = 12,
):
    enforce_rate_limit(request, "price_snapshots", default_limit=180)
    try:
        return price_snapshot_references(config(), project, purpose, property_type, limit=limit, db_path=DB_PATH)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/evaluation", response_model=DataEvaluationResponse)
def evaluation(request: Request):
    enforce_rate_limit(request, "evaluation", default_limit=60)
    try:
        return evaluate_market_data(config(), DB_PATH)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/news")
def news(request: Request, project: str, limit: int = 6, location: str | None = None):
    enforce_rate_limit(request, "news", default_limit=120)
    try:
        return project_news(config(), project, limit=max(1, min(limit, 10)), location_label=location)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/amenities/advice", response_model=AmenityAdviceResponse)
def amenities_advice(payload: AmenityAdviceRequest, request: Request):
    enforce_rate_limit(request, "amenities", default_limit=60)
    try:
        return build_amenity_advice(payload, config())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/verified-transactions")
def verified_transaction(
    payload: VerifiedTransactionInput,
    authorization: str | None = Header(default=None),
    x_admin_api_key: str | None = Header(default=None, alias="X-Admin-API-Key"),
) -> dict[str, int | str]:
    require_admin_api_key(authorization, x_admin_api_key)
    cfg = config()
    project_slug = infer_project_slug(cfg, payload.project, default=payload.project)
    project = cfg.project_by_slug.get(project_slug or "")
    if not project:
        raise HTTPException(status_code=422, detail="Không nhận diện được project trong config.")
    if payload.purpose == "sale" and not payload.transaction_price_vnd:
        raise HTTPException(status_code=422, detail="Giao dịch bán cần transaction_price_vnd.")
    if payload.purpose == "rent" and not payload.rent_monthly_vnd:
        raise HTTPException(status_code=422, detail="Giao dịch thuê cần rent_monthly_vnd.")

    record = {
        "created_at": datetime.now(UTC).isoformat(),
        "project_slug": project.slug,
        "project_name": project.name,
        "property_type": payload.property_type,
        "purpose": payload.purpose,
        "transaction_price_vnd": payload.transaction_price_vnd,
        "rent_monthly_vnd": payload.rent_monthly_vnd,
        "area_m2": payload.area_m2,
        "bedrooms": payload.bedrooms,
        "subdivision": payload.subdivision,
        "transaction_date": payload.transaction_date,
        "confidence_score": payload.confidence_score,
        "evidence_note": payload.evidence_note,
        "source": payload.source,
    }
    inserted_id = get_store(DB_PATH).insert_verified_transaction(record)
    return {"status": "created", "id": inserted_id}


@app.get("/entitlements/me")
def entitlements_me(authorization: str | None = Header(default=None)):
    user = _optional_current_user(authorization)
    return resolve_entitlement(user).model()


@app.post("/export/pdf/check")
def export_pdf_check(authorization: str | None = Header(default=None)):
    user = _optional_current_user(authorization)
    entitlements = resolve_entitlement(user)
    if not entitlements.flags.get("pdf_export"):
        raise HTTPException(status_code=403, detail="Xuất PDF chỉ dành cho Agent Pro.")
    return {"allowed": True, "plan": entitlements.plan}


@app.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, request: Request, authorization: str | None = Header(default=None)):
    enforce_rate_limit(request, "chat", default_limit=60)
    user = _optional_current_user(authorization)
    return handle_chat(payload, config(), DB_PATH, user=user)


@app.post("/zalo/chat", response_model=ChatResponse)
def zalo_chat(payload: ChatRequest, request: Request, authorization: str | None = Header(default=None)):
    enforce_rate_limit(request, "zalo_chat", default_limit=60)
    user = _optional_current_user(authorization)
    return format_zalo_chat_response(handle_chat(payload, config(), DB_PATH, user=user))


def _optional_current_user(authorization: str | None) -> AuthUser | None:
    if not authorization:
        return None
    try:
        return current_user_from_token(bearer_token(authorization), DB_PATH)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
