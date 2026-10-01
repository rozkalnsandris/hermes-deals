"""Read-only price detail: retailer history does not require product matching.

The canonical identity remains reviewed server data. A retailer SKU alone never
asserts cross-store equivalence, and changed packages start a separate series.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.canonical_catalog_fast_route import load_current_offers_by_product
from app.db import get_db
from app.models import OfferCandidateRecord, OfferProductLink
from app.schemas import CanonicalCurrentOfferOut

router = APIRouter()
_FIXED = {None, "fixed_package"}
_UNIT = {"unit_price_only", "example_total_plus_unit", "app_example_total_plus_unit"}


class PriceObservation(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    offer_candidate_id: UUID
    snapshot_id: UUID
    collected_at: datetime
    source_chain: str
    source_store_external_id: str | None
    source_store_name: str | None
    source_offer_id: str | None
    product_name_raw: str
    package_text_raw: str | None
    price_eur: Decimal
    regular_price_eur: Decimal | None
    discount_percent: int | None
    unit_price_eur: Decimal | None
    unit_label: str | None
    pricing_mode: str | None
    app_price_eur: Decimal | None
    requires_app: bool
    coupon_required: bool
    valid_from: date | None
    valid_until: date | None
    app_valid_from: date | None
    app_valid_until: date | None
    source_url: str
    source_image_url: str | None
    parser_version: str
    comparison_price_eur: Decimal | None


class OfferPriceIntelligence(BaseModel):
    offer_candidate_id: UUID
    canonical_product_id: UUID | None
    as_of: date
    timezone: str = "Europe/Berlin"
    history_scope: str
    history_basis: str | None
    history_truncated: bool
    observations: list[PriceObservation]
    comparison_status: str
    comparison_available: bool
    lowest_price_eur: Decimal | None
    price_spread_eur: Decimal | None
    offers: list[CanonicalCurrentOfferOut]


def _series_predicate(row: OfferCandidateRecord):
    """Conservative continuation: exact identity, package, basis and conditions."""
    fixed = row.pricing_mode in _FIXED
    known_basis = (
        bool(row.package_text_raw and row.package_text_raw.strip())
        if fixed else row.pricing_mode in _UNIT and bool(row.unit_label)
    )
    if not row.source_offer_id or not known_basis:
        return OfferCandidateRecord.id == row.id
    mode = (
        or_(OfferCandidateRecord.pricing_mode.is_(None),
            OfferCandidateRecord.pricing_mode == "fixed_package")
        if fixed else OfferCandidateRecord.pricing_mode == row.pricing_mode
    )
    return and_(
        OfferCandidateRecord.source_chain == row.source_chain,
        OfferCandidateRecord.source_store_external_id.is_not_distinct_from(row.source_store_external_id),
        OfferCandidateRecord.source_offer_id == row.source_offer_id,
        OfferCandidateRecord.product_name_raw == row.product_name_raw,
        OfferCandidateRecord.brand_raw.is_not_distinct_from(row.brand_raw),
        OfferCandidateRecord.package_text_raw.is_not_distinct_from(row.package_text_raw),
        OfferCandidateRecord.unit_label.is_not_distinct_from(row.unit_label),
        OfferCandidateRecord.requires_app == row.requires_app,
        OfferCandidateRecord.coupon_required == row.coupon_required,
        mode,
    )


def _products_for_series(db: Session, row: OfferCandidateRecord) -> set[UUID]:
    return set(db.scalars(
        select(OfferProductLink.canonical_product_id)
        .join(OfferCandidateRecord, OfferCandidateRecord.id == OfferProductLink.offer_candidate_id)
        .where(_series_predicate(row))
        .distinct()
    ).all())


def build_offer_price_intelligence(
    db: Session, offer_id: UUID, *, as_of: date, limit: int = 200,
) -> OfferPriceIntelligence:
    row = db.get(OfferCandidateRecord, offer_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Offer not found")

    if as_of == date.max:
        raise HTTPException(status_code=422, detail="Date must be before 9999-12-31")
    history_end = datetime.combine(as_of + timedelta(days=1), time.min,
                                   tzinfo=ZoneInfo("Europe/Berlin")).astimezone(timezone.utc)
    rows = list(db.scalars(
        select(OfferCandidateRecord)
        .where(_series_predicate(row), OfferCandidateRecord.collected_at < history_end)
        .order_by(OfferCandidateRecord.collected_at.desc(), OfferCandidateRecord.id.asc())
        .limit(limit + 1)
    ).all())
    has_series = len(rows) > 1
    truncated = len(rows) > limit
    rows = rows[:limit]
    fixed = row.pricing_mode in _FIXED
    basis = "package" if fixed else row.unit_label if row.pricing_mode in _UNIT else None
    observations = [PriceObservation(
        **{name: getattr(item, name) for name in PriceObservation.model_fields
           if name not in {"offer_candidate_id", "comparison_price_eur"}},
        offer_candidate_id=item.id,
        comparison_price_eur=(item.price_eur if fixed else item.unit_price_eur if basis else None),
    ) for item in rows]

    product_ids = _products_for_series(db, row)
    canonical_id = next(iter(product_ids)) if len(product_ids) == 1 else None
    offers: list[CanonicalCurrentOfferOut] = []
    status = "identity_conflict" if len(product_ids) > 1 else "identity_not_reviewed"
    if canonical_id is not None:
        status = "unsupported_price_basis" if not fixed else "no_current_offers"
        if fixed:
            candidates = load_current_offers_by_product(db, [canonical_id], as_of=as_of, collected_before=history_end)[canonical_id]
            for candidate in candidates:
                # A recycled SKU / changed package cannot inherit an older link.
                current_row = db.get(OfferCandidateRecord, candidate.offer_candidate_id)
                if _products_for_series(db, current_row) != {canonical_id}:
                    continue
                # Conditional prices must never beat an unrestricted price silently.
                if (candidate.requires_app, candidate.coupon_required) != (row.requires_app, row.coupon_required):
                    continue
                if candidate.requires_app or candidate.coupon_required:
                    if candidate.app_valid_from and as_of < candidate.app_valid_from:
                        continue
                    if candidate.app_valid_until and as_of > candidate.app_valid_until:
                        continue
                offers.append(candidate)
            if offers:
                scopes = {(offer.source_chain, offer.source_store_external_id) for offer in offers}
                status = "multi_store_comparison" if len(scopes) >= 2 else "single_store"

    available = status == "multi_store_comparison"
    lowest = min((offer.price_eur for offer in offers), default=None)
    spread = max(offer.price_eur for offer in offers) - lowest if available else None
    return OfferPriceIntelligence(
        offer_candidate_id=row.id,
        canonical_product_id=canonical_id,
        as_of=as_of,
        history_scope="retailer_product" if has_series else "single_observation" if rows else "no_observations",
        history_basis=basis,
        history_truncated=truncated,
        observations=observations,
        comparison_status=status,
        comparison_available=available,
        lowest_price_eur=lowest,
        price_spread_eur=spread,
        offers=offers,
    )


@router.get("/api/v1/offers/{offer_id}/price-intelligence", response_model=OfferPriceIntelligence)
def offer_price_intelligence(
    offer_id: UUID,
    as_of: date | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
) -> OfferPriceIntelligence:
    return build_offer_price_intelligence(
        db, offer_id,
        as_of=as_of or datetime.now(ZoneInfo("Europe/Berlin")).date(),
        limit=limit,
    )
