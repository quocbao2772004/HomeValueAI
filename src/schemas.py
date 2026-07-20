from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Purpose = Literal["sale", "rent"]
PropertyType = Literal["apartment", "villa", "townhouse", "shophouse", "house", "other"]


class PropertyInput(BaseModel):
    purpose: Purpose = "sale"
    project: str
    property_type: PropertyType = "apartment"
    area_m2: float = Field(..., gt=0)
    bedrooms: int | None = Field(default=None, ge=0)
    bathrooms: int | None = Field(default=None, ge=0)
    floor_number: int | None = None
    subdivision: str | None = None
    tower: str | None = None
    view: str | None = None
    furniture: str | None = None
    legal_status: str | None = None


class ComparableListing(BaseModel):
    title: str | None = None
    address: str | None = None
    project: str
    property_type: str
    purpose: str
    price_total_vnd: float | None = None
    price_per_m2_vnd: float | None = None
    rent_monthly_vnd: float | None = None
    area_m2: float | None = None
    bedrooms: int | None = None
    subdivision: str | None = None
    view: str | None = None
    furniture: str | None = None
    observed_at: str | None = None
    source_url: str | None = None
    similarity_score: float


class PriceSnapshotReference(BaseModel):
    source: str
    source_url: str | None = None
    observed_at: str | None = None
    project: str
    property_type: str
    purpose: Purpose
    label: str | None = None
    subdivision: str | None = None
    area_min_m2: float | None = None
    area_max_m2: float | None = None
    price_min_vnd: float | None = None
    price_max_vnd: float | None = None
    price_per_m2_min_vnd: float | None = None
    price_per_m2_max_vnd: float | None = None
    basis: str


class ValuationResponse(BaseModel):
    purpose: Purpose
    project: str
    property_type: str
    currency: str = "VND"
    estimate_basis: str
    p10_total_vnd: float
    p50_total_vnd: float
    p90_total_vnd: float
    p10_price_per_m2_vnd: float | None = None
    p50_price_per_m2_vnd: float | None = None
    p90_price_per_m2_vnd: float | None = None
    sample_size: int
    confidence: Literal["low", "medium", "high"]
    data_freshness: str | None
    comparable_listings: list[ComparableListing]
    reference_price_snapshots: list[PriceSnapshotReference] = []
    top_factors: list[str]
    caveat: str


class MarketTrendResponse(BaseModel):
    project: str
    property_type: str | None
    purpose: Purpose
    bedrooms: int | None
    windows: dict[str, dict[str, float | int | None]]
    reference_price_snapshots: list[PriceSnapshotReference] = []
    caveat: str


class DataEvaluationResponse(BaseModel):
    generated_at: str
    raw_listing_rows: int
    deduped_listing_rows: int
    duplicate_listing_rows: int
    duplicate_rate: float
    expected_sources: list[str]
    observed_sources: list[str]
    missing_sources: list[str]
    source_counts: list[dict[str, Any]]
    project_counts: list[dict[str, Any]]
    quality_flag_counts: list[dict[str, Any]]
    duplicate_groups: list[dict[str, Any]]
    valuation_readiness: list[dict[str, Any]]
    chart: dict[str, list[dict[str, Any]]]
    notes: list[str]


class AmenityAdviceRequest(BaseModel):
    project: str
    purpose: Purpose = "rent"
    property_type: PropertyType = "apartment"
    address: str | None = None
    subdivision: str | None = None
    tower: str | None = None
    max_places_per_category: int = Field(default=3, ge=0, le=5)


class AmenityPlace(BaseModel):
    name: str
    address: str | None = None
    rating: float | None = None
    user_ratings_total: int | None = None
    distance_m: int | None = None
    distance_km: float | None = None
    maps_url: str


class AmenityCategoryResult(BaseModel):
    key: str
    label: str
    query: str
    map_url: str
    embed_url: str
    places: list[AmenityPlace] = Field(default_factory=list)
    renter_note: str
    provider_status: str | None = None
    provider_error: str | None = None


class AmenityAdviceResponse(BaseModel):
    generated_at: str
    project: str
    location_label: str
    base_query: str
    base_map_url: str
    base_embed_url: str
    source: str
    categories: list[AmenityCategoryResult]
    advisory_notes: list[str]
    llm_advice: str | None = None


class VerifiedTransactionInput(BaseModel):
    project: str
    property_type: PropertyType = "apartment"
    purpose: Purpose = "sale"
    transaction_price_vnd: float | None = Field(default=None, gt=0)
    rent_monthly_vnd: float | None = Field(default=None, gt=0)
    area_m2: float = Field(..., gt=0)
    bedrooms: int | None = Field(default=None, ge=0)
    subdivision: str | None = None
    transaction_date: str | None = Field(default=None, description="YYYY-MM-DD")
    confidence_score: float = Field(default=0.8, ge=0, le=1)
    evidence_note: str | None = None
    source: str = "manual"


class AuthRegisterRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    email: str = Field(..., min_length=5, max_length=180)
    password: str = Field(..., min_length=6, max_length=128)


class AuthLoginRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=180)
    password: str = Field(..., min_length=6, max_length=128)


class AuthUser(BaseModel):
    id: int
    name: str
    email: str
    created_at: str
    credit_balance: int = 5
    is_pro: bool = False
    pro_expires_at: str | None = None


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: AuthUser


class PaymentOrderRequest(BaseModel):
    plan: Literal["agent_pro_monthly", "credits_100"] = "agent_pro_monthly"


class PaymentOrderResponse(BaseModel):
    order_code: str
    plan: str
    amount_vnd: int
    status: Literal["pending", "paid", "expired"]
    transfer_content: str
    qr_image_url: str
    bank_bin: str
    bank_account_no: str
    bank_account_name: str
    expires_at: str
    paid_at: str | None = None
    matched_ref_no: str | None = None
    pro_expires_at: str | None = None
    credits_added: int = 0
    credit_balance: int | None = None


class ChatRequest(BaseModel):
    message: str
    property: PropertyInput | None = None
    context: dict[str, Any] | None = None
    action: str | None = None
    idempotency_key: str | None = None


class ChatResponse(BaseModel):
    answer: str
    missing_fields: list[str] = []
    valuation: dict[str, Any] | None = None
    data: dict[str, Any] | None = None
    intent: str | None = None
    extracted: dict[str, Any] | None = None
    context: dict[str, Any] | None = None
    response_language: Literal["vi", "en"] = "vi"
    plan: str | None = None
    credits: dict[str, Any] | None = None
    advice: dict[str, Any] | None = None
    enrichment: dict[str, Any] | None = None
    entitlements: dict[str, Any] | None = None
    ui: dict[str, Any] | None = None


class CrawlResponse(BaseModel):
    fetched_at: str
    pages: list[dict[str, Any]]
    records_parsed: int
    price_snapshots_parsed: int = 0
    property_candidates_parsed: int = 0
    output_csv: str
    output_price_snapshots_csv: str | None = None
    output_property_candidates_csv: str | None = None
    db_path: str
    source_filter: str | None = None
