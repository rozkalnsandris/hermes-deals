from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class SourceChain(StrEnum):
    NETTO = "netto"
    LIDL = "lidl"
    ALDI_NORD = "aldi_nord"
    EDEKA = "edeka"


class OfferCandidate(BaseModel):
    """Stable Phase-1 boundary between store parsers and the future normalization engine."""

    source_chain: SourceChain
    source_store_external_id: str | None = None
    source_store_name: str | None = None
    source_offer_id: str | None = None

    product_name_raw: str = Field(min_length=1)
    brand_raw: str | None = None
    description_raw: str | None = None
    package_text_raw: str | None = None

    price_eur: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    regular_price_eur: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    unit_price_eur: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=4)
    unit_label: str | None = None
    pricing_mode: str | None = None
    regular_unit_price_eur: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=4)
    example_weight_g: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    discount_percent: int | None = Field(default=None, ge=0, le=100)
    app_price_eur: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    requires_app: bool = False
    coupon_required: bool = False

    valid_from: date | None = None
    valid_until: date | None = None
    app_valid_from: date | None = None
    app_valid_until: date | None = None
    source_url: HttpUrl
    source_image_url: HttpUrl | None = None
    snapshot_id: UUID
    collected_at: datetime
    parser_version: str = Field(min_length=1, max_length=32)
    raw_payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_validity_window(self) -> "OfferCandidate":
        if self.valid_from is not None and self.valid_until is not None and self.valid_until < self.valid_from:
            raise ValueError("valid_until must not be earlier than valid_from")

        app_pair = (self.app_valid_from is not None, self.app_valid_until is not None)
        if app_pair[0] != app_pair[1]:
            raise ValueError("app_valid_from and app_valid_until must be provided together")
        if (
            self.app_valid_from is not None
            and self.app_valid_until is not None
            and self.app_valid_until < self.app_valid_from
        ):
            raise ValueError("app_valid_until must not be earlier than app_valid_from")
        if self.app_valid_from is not None and self.app_price_eur is None:
            raise ValueError("app validity requires app_price_eur")

        allowed_pricing_modes = {
            "fixed_package",
            "unit_price_only",
            "example_total_plus_unit",
            "app_example_total_plus_unit",
        }
        if self.pricing_mode is not None and self.pricing_mode not in allowed_pricing_modes:
            raise ValueError("unsupported pricing_mode")

        unit_basis_modes = allowed_pricing_modes - {"fixed_package"}
        if self.pricing_mode in unit_basis_modes:
            if self.unit_price_eur is None:
                raise ValueError("unit-basis pricing_mode requires unit_price_eur")
            if self.unit_label is None or not self.unit_label.strip():
                raise ValueError("unit-basis pricing_mode requires unit_label")

        if self.pricing_mode in {
            "example_total_plus_unit",
            "app_example_total_plus_unit",
        } and self.example_weight_g is None:
            raise ValueError("example-total pricing_mode requires example_weight_g")

        if self.pricing_mode == "app_example_total_plus_unit" and not self.requires_app:
            raise ValueError("app example pricing_mode requires requires_app=true")
        return self


class SourceSnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_chain: str
    source_url: str
    final_url: str | None
    scope: str | None
    collected_at: datetime
    http_status: int | None
    elapsed_ms: int | None
    content_type: str | None
    content_bytes: int
    sha256: str | None
    keyword_hits: dict[str, int]
    json_ld_blocks: int
    strategy_hint: str
    success: bool
    error: str | None


class OfferCandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_chain: str
    source_store_external_id: str | None
    source_store_name: str | None
    source_offer_id: str | None
    product_name_raw: str
    brand_raw: str | None
    description_raw: str | None
    package_text_raw: str | None
    price_eur: Decimal
    regular_price_eur: Decimal | None
    unit_price_eur: Decimal | None
    unit_label: str | None
    pricing_mode: str | None = None
    regular_unit_price_eur: Decimal | None = None
    example_weight_g: Decimal | None = None
    discount_percent: int | None
    app_price_eur: Decimal | None
    requires_app: bool
    coupon_required: bool
    valid_from: date | None
    valid_until: date | None
    app_valid_from: date | None = None
    app_valid_until: date | None = None
    source_url: str
    source_image_url: str | None
    snapshot_id: UUID
    collected_at: datetime
    parser_version: str


class CanonicalPriceObservationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    offer_candidate_id: UUID
    snapshot_id: UUID
    source_chain: str
    source_store_external_id: str | None
    source_store_name: str | None
    source_offer_id: str
    product_name_raw: str
    brand_raw: str | None
    price_eur: Decimal
    regular_price_eur: Decimal | None
    unit_price_eur: Decimal | None
    unit_label: str | None
    discount_percent: int | None
    app_price_eur: Decimal | None
    requires_app: bool
    coupon_required: bool
    valid_from: date | None
    valid_until: date | None
    app_valid_from: date | None = None
    app_valid_until: date | None = None
    collected_at: datetime
    source_url: str
    source_image_url: str | None
    parser_version: str


class CanonicalPriceHistoryOut(BaseModel):
    canonical_product_id: UUID
    display_name: str
    normalized_name: str
    brand_display: str | None
    brand_normalized: str | None
    item_quantity_value: Decimal | None
    item_quantity_unit: str | None
    pack_count: int | None
    gtin14: str | None
    observations: list[CanonicalPriceObservationOut]


class CanonicalProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    display_name: str
    normalized_name: str
    brand_display: str | None
    brand_normalized: str | None
    item_quantity_value: Decimal | None
    item_quantity_unit: str | None
    pack_count: int | None
    gtin14: str | None
    category_key: str | None
    created_at: datetime
    updated_at: datetime


class CanonicalCurrentOfferOut(BaseModel):
    offer_candidate_id: UUID
    snapshot_id: UUID
    source_chain: str
    source_store_external_id: str | None
    source_store_name: str | None
    source_offer_id: str
    product_name_raw: str
    brand_raw: str | None
    price_eur: Decimal
    regular_price_eur: Decimal | None
    unit_price_eur: Decimal | None
    unit_label: str | None
    discount_percent: int | None
    app_price_eur: Decimal | None
    requires_app: bool
    coupon_required: bool
    valid_from: date | None
    valid_until: date | None
    app_valid_from: date | None = None
    app_valid_until: date | None = None
    collected_at: datetime
    source_url: str
    source_image_url: str | None
    parser_version: str


class CanonicalCurrentOffersOut(BaseModel):
    canonical_product_id: UUID
    display_name: str
    as_of: date
    timezone: str
    offers: list[CanonicalCurrentOfferOut]


class CanonicalCurrentPriceComparisonOut(BaseModel):
    canonical_product_id: UUID
    display_name: str
    as_of: date
    timezone: str
    comparison_status: str
    comparison_available: bool
    current_offer_count: int
    retailer_count: int
    lowest_price_eur: Decimal | None
    price_spread_eur: Decimal | None
    lowest_price_offers: list[CanonicalCurrentOfferOut]
    offers: list[CanonicalCurrentOfferOut]


class CanonicalCatalogProductOut(BaseModel):
    id: UUID
    display_name: str
    normalized_name: str
    brand_display: str | None
    brand_normalized: str | None
    item_quantity_value: Decimal | None
    item_quantity_unit: str | None
    pack_count: int | None
    gtin14: str | None
    category_key: str | None
    primary_image_url: str | None = None
    as_of: date
    timezone: str
    comparison_status: str
    comparison_available: bool
    current_offer_count: int
    retailer_count: int
    lowest_price_eur: Decimal | None
    current_offers: list[CanonicalCurrentOfferOut]


class CanonicalCatalogOut(BaseModel):
    as_of: date
    timezone: str
    query: str | None
    count: int
    products: list[CanonicalCatalogProductOut]


class CanonicalRetailerSummaryOut(BaseModel):
    source_chain: str
    display_name: str
    current_offer_count: int
    current_product_count: int
    lowest_price_eur: Decimal | None


class CanonicalUiOverviewOut(BaseModel):
    as_of: date
    timezone: str
    total_products: int
    products_with_current_offers: int
    products_without_current_offers: int
    comparison_ready_products: int
    current_offer_count: int
    retailer_count: int
    retailers: list[CanonicalRetailerSummaryOut]



class BasketItemIn(BaseModel):
    canonical_product_id: UUID
    quantity: int


class BasketCompareRequest(BaseModel):
    as_of: date | None = None
    items: list[BasketItemIn]


class BasketRetailerLineOut(BaseModel):
    canonical_product_id: UUID
    display_name: str
    quantity: int
    unit_price_eur: Decimal
    line_total_eur: Decimal
    source_chain: str
    source_store_external_id: str | None
    source_store_name: str | None
    source_offer_id: str | None
    valid_from: date
    valid_until: date
    source_url: str | None
    source_image_url: str | None


class BasketRetailerSummaryOut(BaseModel):
    source_chain: str
    source_store_external_id: str | None
    source_store_name: str | None
    requested_product_count: int
    covered_product_count: int
    missing_product_ids: list[UUID]
    complete_basket: bool
    total_eur: Decimal
    lines: list[BasketRetailerLineOut]


class BasketCompareOut(BaseModel):
    as_of: date
    timezone: str
    requested_product_count: int
    requested_unit_count: int
    retailer_scope_count: int
    complete_retailer_scope_count: int
    comparison_available: bool
    best_complete_total_eur: Decimal | None
    best_complete_scopes: list[BasketRetailerSummaryOut]
    retailer_scopes: list[BasketRetailerSummaryOut]


class CurrentDealOut(BaseModel):
    offer_candidate_id: UUID
    source_chain: str
    source_store_external_id: str | None
    source_store_name: str | None
    source_offer_id: str
    product_name_raw: str
    brand_raw: str | None
    package_text_raw: str | None
    price_eur: Decimal
    regular_price_eur: Decimal | None
    unit_price_eur: Decimal | None
    unit_label: str | None
    pricing_mode: str | None = None
    regular_unit_price_eur: Decimal | None = None
    example_weight_g: Decimal | None = None
    discount_percent: Decimal | None
    app_price_eur: Decimal | None
    requires_app: bool
    coupon_required: bool
    valid_from: date | None
    valid_until: date | None
    app_valid_from: date | None = None
    app_valid_until: date | None = None
    base_price_current: bool
    app_price_current: bool
    source_url: str | None
    source_image_url: str | None
    collected_at: datetime
    canonical_product_id: UUID | None
    canonical_comparable: bool


class AvailabilityCountsOut(BaseModel):
    current: int
    upcoming: int
    unknown: int
    expired: int


class CurrentDealsOut(BaseModel):
    as_of: date
    timezone: str
    query: str | None
    retailer: str | None
    app_only: bool
    coupon_only: bool
    discount_only: bool
    image_only: bool
    available_count: int
    count: int
    retailer_counts: dict[str, int]
    feature_counts: dict[str, int]
    availability_counts: AvailabilityCountsOut
    retailer_availability: dict[str, AvailabilityCountsOut]
    deals: list[CurrentDealOut]
