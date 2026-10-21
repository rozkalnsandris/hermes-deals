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
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.canonical_catalog_fast_route import load_current_offers_by_product
from app.db import get_db
from app.models import OfferCandidateRecord, OfferProductLink
from app.schemas import CanonicalCurrentOfferOut

router = APIRouter()
_FIXED = {None, "fixed_package"}
_UNIT = {"unit_price_only", "example_total_plus_unit", "app_example_total_plus_unit"}
_SERIES_FIELDS = (
    "source_chain", "source_store_external_id", "source_offer_id", "product_name_raw",
    "brand_raw", "package_text_raw", "unit_label", "requires_app", "coupon_required",
)
# Match Python str.strip() when testing whether a package has a known basis.
_WHITESPACE = "\t\n\v\f\r\x1c\x1d\x1e\x1f \x85\xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"


def history_cutoff(as_of: date) -> datetime:
    if as_of == date.max:
        raise HTTPException(status_code=422, detail="Date must be before 9999-12-31")
    return datetime.combine(as_of + timedelta(days=1), time.min,
                            tzinfo=ZoneInfo("Europe/Berlin")).astimezone(timezone.utc)


def observed_price(row: OfferCandidateRecord) -> Decimal | None:
    """Comparable source price, never today's usable household price."""
    if row.pricing_mode in _FIXED:
        return row.price_eur if row.package_text_raw and row.package_text_raw.strip() else None
    return row.unit_price_eur if row.pricing_mode in _UNIT and row.unit_label else None


def list_price_history_series(
    db: Session, *, as_of: date, query: str = "", retailer: str = "",
    sort: str = "name", offset: int = 0, limit: int = 60,
) -> tuple[list[OfferCandidateRecord], int]:
    """One latest known observation per conservative source series, paged in SQL.

    Validity is deliberately not a filter: expired offers still have history.
    Partition identity matches _series_predicate, including singleton fallbacks.
    Search fields are invariant within a series, so filtering before ranking does
    not resurrect an older observation. No cross-retailer identity is inferred.
    """
    if sort not in {"name", "retailer", "newest"} or offset < 0 or not 1 <= limit <= 100:
        raise ValueError("Invalid history pagination or sort")
    row = OfferCandidateRecord
    fixed = or_(row.pricing_mode.is_(None), row.pricing_mode == "fixed_package")
    known_basis = or_(
        and_(fixed, func.length(func.trim(row.package_text_raw, _WHITESPACE)) > 0),
        and_(row.pricing_mode.in_(sorted(_UNIT)), row.unit_label.is_not(None), row.unit_label != ""),
    )
    continuable = and_(row.source_offer_id.is_not(None), row.source_offer_id != "", known_basis)
    partition = [getattr(row, field) for field in _SERIES_FIELDS] + [
        case((fixed, "fixed_package"), else_=row.pricing_mode),
        case((continuable, None), else_=row.id),
    ]
    filters = [row.collected_at < history_cutoff(as_of)]
    if retailer:
        filters.append(row.source_chain == retailer)
    if query:
        filters.append(or_(*(
            func.lower(column).contains(query.lower(), autoescape=True)
            for column in (row.product_name_raw, row.brand_raw, row.source_offer_id)
        )))
    ranked = select(row.id, func.row_number().over(
        partition_by=partition, order_by=(row.collected_at.desc(), row.id.asc()),
    ).label("position")).where(*filters).subquery()
    latest = select(ranked.c.id).where(ranked.c.position == 1).subquery()
    total = db.scalar(select(func.count()).select_from(latest))
    order = {
        "name": (func.lower(row.product_name_raw), row.id),
        "retailer": (row.source_chain, func.lower(row.product_name_raw), row.id),
        "newest": (row.collected_at.desc(), row.id),
    }[sort]
    rows = list(db.scalars(select(row).join(latest, latest.c.id == row.id)
                          .order_by(*order).offset(offset).limit(limit)))
    return rows, total


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


def summarize_price_history(details: OfferPriceIntelligence):
    """Describe observed prices through the selected observation, never a deal score."""
    if not details.history_basis:
        return None

    def stamp(row):
        value = row.collected_at
        return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).astimezone(ZoneInfo("Europe/Berlin"))

    selected = next((row for row in details.observations
                     if row.offer_candidate_id == details.offer_candidate_id and row.comparison_price_eur is not None), None)
    if selected is None:
        return None
    selected_stamp = stamp(selected)
    rows = [row for row in details.observations
            if row.comparison_price_eur is not None and stamp(row) <= selected_stamp]
    days = {stamp(row).date() for row in rows}
    # Intra-day duplicate snapshots are not another day of price history.
    earlier = [row for row in rows if stamp(row).date() < selected_stamp.date()]
    previous_stamp = max((stamp(row) for row in earlier), default=None)
    previous_prices = {row.comparison_price_eur for row in earlier if stamp(row) == previous_stamp}
    previous = next(iter(previous_prices)) if len(previous_prices) == 1 else None
    price = selected.comparison_price_eur
    return {"price": price, "minimum": min(row.comparison_price_eur for row in rows),
            "maximum": max(row.comparison_price_eur for row in rows), "observation_count": len(rows),
            "day_count": len(days), "start": min(days), "end": max(days),
            "previous": previous, "previous_day": previous_stamp.date() if previous is not None else None,
            "change": price - previous if previous is not None else None,
            "requires_app": selected.requires_app, "coupon_required": selected.coupon_required,
            "truncated": details.history_truncated}


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
        *(getattr(OfferCandidateRecord, field).is_not_distinct_from(getattr(row, field))
          if field in {"source_store_external_id", "brand_raw", "package_text_raw", "unit_label"}
          else getattr(OfferCandidateRecord, field) == getattr(row, field)
          for field in _SERIES_FIELDS),
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

    history_end = history_cutoff(as_of)
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
    fixed_basis = fixed and bool(row.package_text_raw and row.package_text_raw.strip())
    basis = "package" if fixed_basis else row.unit_label if row.pricing_mode in _UNIT else None
    observations = [PriceObservation(
        **{name: getattr(item, name) for name in PriceObservation.model_fields
           if name not in {"offer_candidate_id", "comparison_price_eur"}},
        offer_candidate_id=item.id,
        comparison_price_eur=observed_price(item),
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
