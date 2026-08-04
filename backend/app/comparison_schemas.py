from __future__ import annotations

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.pricing_normalizer import PricingMode


class ComparisonBasisOut(BaseModel):
    quantity_value: Decimal = Field(gt=0)
    quantity_unit: Literal["g", "ml", "count"]
    display_unit: Literal["kg", "l", "piece"]


class ComparisonFamilySummaryOut(BaseModel):
    id: UUID
    family_key: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    normalized_name: str = Field(min_length=1)
    variant_key: str | None
    basis: ComparisonBasisOut
    identity_equivalent: Literal[False] = False


class ComparisonOfferOut(BaseModel):
    offer_candidate_id: UUID
    canonical_product_id: UUID | None
    source_chain: str
    source_store_external_id: str | None
    source_offer_id: str
    package_price_eur: Decimal | None = Field(default=None, gt=0)
    normalized_unit_price_eur: Decimal | None = Field(
        default=None,
        gt=0,
    )
    normalized_display_unit: Literal["kg", "l", "piece"] | None
    pricing_mode: PricingMode
    family_membership_accepted: bool
    pricing_ready: bool
    blocked_reason: str | None = None

    @model_validator(mode="after")
    def validate_pricing_readiness(self) -> "ComparisonOfferOut":
        if self.pricing_ready:
            if not self.family_membership_accepted:
                raise ValueError(
                    "pricing_ready requires accepted family membership"
                )
            if self.canonical_product_id is None:
                raise ValueError(
                    "pricing_ready requires canonical product"
                )
            if self.normalized_unit_price_eur is None:
                raise ValueError(
                    "pricing_ready requires normalized unit price"
                )
            if self.normalized_display_unit is None:
                raise ValueError(
                    "pricing_ready requires normalized display unit"
                )
        return self


class ComparisonFamilyMemberOut(BaseModel):
    canonical_product_id: UUID
    display_name: str = Field(min_length=1)
    brand_display: str | None
    relation_type: Literal["direct_peer", "substitute"]
    membership_review_status: Literal["accepted"]


class ComparisonFamilyDetailOut(BaseModel):
    family: ComparisonFamilySummaryOut
    members: list[ComparisonFamilyMemberOut]
    identity_equivalent: Literal[False] = False


class ComparisonFamilyCurrentOffersOut(BaseModel):
    family: ComparisonFamilySummaryOut
    comparison_mode: Literal["normalized_unit_basis"]
    identity_equivalent: Literal[False] = False
    comparison_available: bool
    comparable_offer_count: int = Field(ge=0)
    blocked_offer_count: int = Field(ge=0)
    lowest_normalized_unit_price_eur: Decimal | None
    normalized_unit_price_spread_eur: Decimal | None
    package_price_comparison_available: bool
    offers: list[ComparisonOfferOut]
