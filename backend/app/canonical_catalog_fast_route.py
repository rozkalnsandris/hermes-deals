from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import Depends, Query, Response
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import CanonicalProduct, OfferCandidateRecord, OfferProductLink
from app.schemas import (
    CanonicalCatalogOut,
    CanonicalCatalogProductOut,
    CanonicalCurrentOfferOut,
    CanonicalRetailerSummaryOut,
    CanonicalUiOverviewOut,
)


_TIMEZONE = "Europe/Berlin"
_ENGINE_HEADER = "batched-current-offers-v1"


def _effective_date(as_of: date | None) -> date:
    if as_of is not None:
        return as_of
    return datetime.now(ZoneInfo(_TIMEZONE)).date()


def _current_offer(row: OfferCandidateRecord) -> CanonicalCurrentOfferOut:
    return CanonicalCurrentOfferOut(
        offer_candidate_id=row.id,
        snapshot_id=row.snapshot_id,
        source_chain=row.source_chain,
        source_store_external_id=row.source_store_external_id,
        source_store_name=row.source_store_name,
        source_offer_id=row.source_offer_id or "",
        product_name_raw=row.product_name_raw,
        brand_raw=row.brand_raw,
        price_eur=row.price_eur,
        regular_price_eur=row.regular_price_eur,
        unit_price_eur=row.unit_price_eur,
        unit_label=row.unit_label,
        discount_percent=row.discount_percent,
        app_price_eur=row.app_price_eur,
        requires_app=row.requires_app,
        coupon_required=row.coupon_required,
        valid_from=row.valid_from,
        valid_until=row.valid_until,
        app_valid_from=row.app_valid_from,
        app_valid_until=row.app_valid_until,
        collected_at=row.collected_at,
        source_url=row.source_url,
        source_image_url=row.source_image_url,
        parser_version=row.parser_version,
    )


def _comparison_summary(
    offers: list[CanonicalCurrentOfferOut],
) -> tuple[str, bool, int, int, Decimal | None]:
    retailer_keys = {
        (offer.source_chain, offer.source_store_external_id)
        for offer in offers
    }
    retailer_count = len(retailer_keys)
    current_offer_count = len(offers)

    if current_offer_count == 0:
        return (
            "no_current_offers",
            False,
            current_offer_count,
            retailer_count,
            None,
        )

    lowest_price_eur = min(offer.price_eur for offer in offers)
    if retailer_count >= 2:
        comparison_status = "multi_store_comparison"
        comparison_available = True
    else:
        comparison_status = "single_current_offer"
        comparison_available = False

    return (
        comparison_status,
        comparison_available,
        current_offer_count,
        retailer_count,
        lowest_price_eur,
    )


def load_current_offers_by_product(
    db: Session,
    canonical_product_ids: Iterable[UUID],
    *,
    as_of: date,
) -> dict[UUID, list[CanonicalCurrentOfferOut]]:
    product_ids = tuple(dict.fromkeys(canonical_product_ids))
    offers_by_product: dict[UUID, list[CanonicalCurrentOfferOut]] = {
        product_id: []
        for product_id in product_ids
    }
    if not product_ids:
        return offers_by_product

    seed_identities = (
        select(
            OfferProductLink.canonical_product_id.label("canonical_product_id"),
            OfferCandidateRecord.source_chain.label("source_chain"),
            OfferCandidateRecord.source_store_external_id.label(
                "source_store_external_id"
            ),
            OfferCandidateRecord.source_offer_id.label("source_offer_id"),
        )
        .join(
            OfferCandidateRecord,
            OfferProductLink.offer_candidate_id == OfferCandidateRecord.id,
        )
        .where(
            OfferProductLink.canonical_product_id.in_(product_ids),
            OfferCandidateRecord.source_offer_id.is_not(None),
        )
        .distinct()
        .subquery("canonical_seed_identities")
    )

    ranked = (
        select(
            seed_identities.c.canonical_product_id,
            OfferCandidateRecord.id.label("offer_candidate_id"),
            func.row_number()
            .over(
                partition_by=(
                    seed_identities.c.canonical_product_id,
                    OfferCandidateRecord.source_chain,
                    OfferCandidateRecord.source_store_external_id,
                    OfferCandidateRecord.source_offer_id,
                ),
                order_by=(
                    OfferCandidateRecord.collected_at.desc(),
                    OfferCandidateRecord.id.asc(),
                ),
            )
            .label("row_rank"),
        )
        .select_from(seed_identities)
        .join(
            OfferCandidateRecord,
            and_(
                OfferCandidateRecord.source_chain
                == seed_identities.c.source_chain,
                OfferCandidateRecord.source_store_external_id.is_not_distinct_from(
                    seed_identities.c.source_store_external_id
                ),
                OfferCandidateRecord.source_offer_id
                == seed_identities.c.source_offer_id,
            ),
        )
        .where(
            or_(
                OfferCandidateRecord.pricing_mode.is_(None),
                OfferCandidateRecord.pricing_mode == "fixed_package",
            ),
            OfferCandidateRecord.valid_from.is_not(None),
            OfferCandidateRecord.valid_until.is_not(None),
            OfferCandidateRecord.valid_from <= as_of,
            OfferCandidateRecord.valid_until >= as_of,
        )
        .subquery("ranked_canonical_current_offers")
    )

    winners = db.execute(
        select(
            ranked.c.canonical_product_id,
            OfferCandidateRecord,
        )
        .join(
            OfferCandidateRecord,
            OfferCandidateRecord.id == ranked.c.offer_candidate_id,
        )
        .where(ranked.c.row_rank == 1)
    ).all()

    rows_by_product: dict[UUID, list[OfferCandidateRecord]] = {
        product_id: []
        for product_id in product_ids
    }
    for canonical_product_id, row in winners:
        rows_by_product.setdefault(canonical_product_id, []).append(row)

    for product_id, rows in rows_by_product.items():
        rows.sort(
            key=lambda row: (
                row.price_eur,
                row.source_chain,
                row.source_store_external_id or "",
                row.source_offer_id or "",
            )
        )
        offers_by_product[product_id] = [
            _current_offer(row)
            for row in rows
        ]

    return offers_by_product


def _catalog_payload(
    *,
    db: Session,
    effective_date: date,
    q: str | None,
    retailer: str | None,
    current_only: bool,
    comparison_only: bool,
    sort: str,
    limit: int,
) -> CanonicalCatalogOut:
    products = list(
        db.scalars(
            select(CanonicalProduct).order_by(
                CanonicalProduct.brand_normalized.asc().nulls_last(),
                CanonicalProduct.normalized_name.asc(),
                CanonicalProduct.id.asc(),
            )
        ).all()
    )

    normalized_query = q.strip().casefold() if q is not None else None
    if normalized_query:
        products = [
            product
            for product in products
            if normalized_query in product.display_name.casefold()
            or normalized_query in product.normalized_name.casefold()
            or (
                product.brand_display is not None
                and normalized_query in product.brand_display.casefold()
            )
            or (
                product.brand_normalized is not None
                and normalized_query in product.brand_normalized.casefold()
            )
        ]

    offers_by_product = load_current_offers_by_product(
        db,
        (product.id for product in products),
        as_of=effective_date,
    )

    catalog_rows: list[CanonicalCatalogProductOut] = []
    for product in products:
        offers = offers_by_product.get(product.id, [])
        (
            comparison_status,
            comparison_available,
            current_offer_count,
            retailer_count,
            lowest_price_eur,
        ) = _comparison_summary(offers)
        catalog_rows.append(
            CanonicalCatalogProductOut(
                id=product.id,
                display_name=product.display_name,
                normalized_name=product.normalized_name,
                brand_display=product.brand_display,
                brand_normalized=product.brand_normalized,
                item_quantity_value=product.item_quantity_value,
                item_quantity_unit=product.item_quantity_unit,
                pack_count=product.pack_count,
                gtin14=product.gtin14,
                category_key=product.category_key,
                primary_image_url=next(
                    (
                        offer.source_image_url
                        for offer in offers
                        if offer.source_image_url
                    ),
                    None,
                ),
                as_of=effective_date,
                timezone=_TIMEZONE,
                comparison_status=comparison_status,
                comparison_available=comparison_available,
                current_offer_count=current_offer_count,
                retailer_count=retailer_count,
                lowest_price_eur=lowest_price_eur,
                current_offers=offers,
            )
        )

    if retailer:
        retailer_key = retailer.strip().casefold()
        catalog_rows = [
            product
            for product in catalog_rows
            if any(
                offer.source_chain.casefold() == retailer_key
                for offer in product.current_offers
            )
        ]

    if current_only:
        catalog_rows = [
            product
            for product in catalog_rows
            if product.current_offer_count > 0
        ]

    if comparison_only:
        catalog_rows = [
            product
            for product in catalog_rows
            if product.comparison_available
        ]

    if sort == "price_asc":
        catalog_rows.sort(
            key=lambda product: (
                product.lowest_price_eur is None,
                product.lowest_price_eur or Decimal("999999999"),
                product.display_name.casefold(),
            )
        )
    elif sort == "price_desc":
        catalog_rows.sort(
            key=lambda product: (
                product.lowest_price_eur is None,
                -(product.lowest_price_eur or Decimal("0")),
                product.display_name.casefold(),
            )
        )
    elif sort == "retailers_desc":
        catalog_rows.sort(
            key=lambda product: (
                -product.retailer_count,
                product.lowest_price_eur is None,
                product.lowest_price_eur or Decimal("999999999"),
                product.display_name.casefold(),
            )
        )
    else:
        catalog_rows.sort(
            key=lambda product: (
                product.brand_normalized is None,
                product.brand_normalized or "",
                product.normalized_name,
                str(product.id),
            )
        )

    catalog_rows = catalog_rows[:limit]
    return CanonicalCatalogOut(
        as_of=effective_date,
        timezone=_TIMEZONE,
        query=q,
        count=len(catalog_rows),
        products=catalog_rows,
    )


def installed_fast_canonical_catalog(
    response: Response,
    as_of: date | None = Query(default=None),
    q: str | None = Query(default=None, min_length=1, max_length=100),
    retailer: str | None = Query(default=None, max_length=32),
    current_only: bool = Query(default=False),
    comparison_only: bool = Query(default=False),
    sort: str = Query(
        default="name",
        pattern="^(name|price_asc|price_desc|retailers_desc)$",
    ),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> CanonicalCatalogOut:
    payload = _catalog_payload(
        db=db,
        effective_date=_effective_date(as_of),
        q=q,
        retailer=retailer,
        current_only=current_only,
        comparison_only=comparison_only,
        sort=sort,
        limit=limit,
    )
    response.headers["X-Hermes-Canonical-Engine"] = _ENGINE_HEADER
    return payload


def _overview_payload(
    *,
    db: Session,
    effective_date: date,
) -> CanonicalUiOverviewOut:
    product_ids = tuple(db.scalars(select(CanonicalProduct.id)).all())
    offers_by_product = load_current_offers_by_product(
        db,
        product_ids,
        as_of=effective_date,
    )

    retailer_offer_counts: dict[str, int] = {}
    retailer_products: dict[str, set[UUID]] = {}
    retailer_lowest_prices: dict[str, Decimal] = {}
    products_with_current = 0
    comparison_ready = 0
    current_offer_count = 0

    for product_id in product_ids:
        offers = offers_by_product.get(product_id, [])
        if offers:
            products_with_current += 1
        retailer_keys = {
            (offer.source_chain, offer.source_store_external_id)
            for offer in offers
        }
        if len(retailer_keys) >= 2:
            comparison_ready += 1
        current_offer_count += len(offers)

        seen_product_retailers: set[str] = set()
        for offer in offers:
            chain = offer.source_chain
            retailer_offer_counts[chain] = (
                retailer_offer_counts.get(chain, 0) + 1
            )
            if chain not in seen_product_retailers:
                retailer_products.setdefault(chain, set()).add(product_id)
                seen_product_retailers.add(chain)

            current_low = retailer_lowest_prices.get(chain)
            if current_low is None or offer.price_eur < current_low:
                retailer_lowest_prices[chain] = offer.price_eur

    labels = {
        "aldi_nord": "ALDI Nord",
        "edeka": "EDEKA",
        "lidl": "Lidl",
        "netto": "Netto",
    }
    retailer_rows = [
        CanonicalRetailerSummaryOut(
            source_chain=chain,
            display_name=labels.get(chain, chain),
            current_offer_count=retailer_offer_counts[chain],
            current_product_count=len(retailer_products.get(chain, set())),
            lowest_price_eur=retailer_lowest_prices.get(chain),
        )
        for chain in sorted(
            retailer_offer_counts,
            key=lambda value: labels.get(value, value).casefold(),
        )
    ]

    total_products = len(product_ids)
    return CanonicalUiOverviewOut(
        as_of=effective_date,
        timezone=_TIMEZONE,
        total_products=total_products,
        products_with_current_offers=products_with_current,
        products_without_current_offers=(
            total_products - products_with_current
        ),
        comparison_ready_products=comparison_ready,
        current_offer_count=current_offer_count,
        retailer_count=len(retailer_rows),
        retailers=retailer_rows,
    )


def installed_fast_canonical_ui_overview(
    response: Response,
    as_of: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> CanonicalUiOverviewOut:
    payload = _overview_payload(
        db=db,
        effective_date=_effective_date(as_of),
    )
    response.headers["X-Hermes-Canonical-Engine"] = _ENGINE_HEADER
    return payload
