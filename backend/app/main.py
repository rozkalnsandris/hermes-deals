from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, Response
from sqlalchemy import and_, or_, select, text
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import CanonicalProduct, OfferCandidateRecord, OfferProductLink, SourceSnapshot
from app.schemas import BasketCompareOut, BasketCompareRequest, BasketRetailerLineOut, BasketRetailerSummaryOut, CanonicalCatalogOut, CanonicalCatalogProductOut, CanonicalCurrentOfferOut, CanonicalCurrentOffersOut, CanonicalCurrentPriceComparisonOut, CanonicalPriceHistoryOut, CanonicalPriceObservationOut, CanonicalProductOut, CanonicalRetailerSummaryOut, CanonicalUiOverviewOut, CurrentDealOut, CurrentDealsOut, OfferCandidate, OfferCandidateOut, SourceChain, SourceSnapshotOut
from app.settings import get_settings
from app.source_config import SourceConfig, load_sources

from app.review_queue import (
    ReviewDecisionRequest,
    ReviewDraftRequest,
    approve_review_item,
    get_review_item,
    list_review_items,
    reject_review_item,
    reopen_review_item,
    review_item_dict,
    review_summary,
    save_review_draft,
)

from app.lidl_weekly_review_bridge import create_review_from_page_alert_hint
from app.lidl_review_preview import ReviewPreviewUnavailable, resolve_review_preview

app = FastAPI(
    title="Hermes Deals API",
    version="0.3.12",
    description="Private family shopping intelligence platform — Phase 5G B15F worker-pre-rendered provenance-bound Lidl Review previews.",
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)


@app.get("/api/health")
def health(db: Session = Depends(get_db)) -> dict[str, object]:
    db.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "service": "hermes-deals-api",
        "phase": "5G-B15F",
        "version": "0.3.12",
        "time": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/v1/contracts/offer-candidate")
def offer_candidate_contract() -> dict[str, object]:
    return OfferCandidate.model_json_schema()


UNIT_BASIS_PRICING_MODES = {
    "unit_price_only",
    "example_total_plus_unit",
    "app_example_total_plus_unit",
}


def _is_unit_basis_offer(row: OfferCandidateRecord) -> bool:
    return row.pricing_mode in UNIT_BASIS_PRICING_MODES


def _canonical_price_eligible_clause():
    return or_(
        OfferCandidateRecord.pricing_mode.is_(None),
        OfferCandidateRecord.pricing_mode == "fixed_package",
    )


def _active_source_config(source_chain: SourceChain) -> SourceConfig | None:
    settings = get_settings()
    matches = [
        source
        for source in load_sources(settings.sources_config)
        if source.enabled and source.chain == source_chain.value
    ]
    if len(matches) > 1:
        raise RuntimeError(
            f"Multiple enabled source configs for {source_chain.value}"
        )
    return matches[0] if matches else None


def _apply_active_store_offer_filter(query, source_chain: SourceChain):
    source = _active_source_config(source_chain)
    if source is not None and source.store_external_id:
        query = query.where(
            OfferCandidateRecord.source_store_external_id
            == source.store_external_id
        )
    return query


@app.get("/api/v1/sources/latest", response_model=list[SourceSnapshotOut])
def latest_sources(db: Session = Depends(get_db)) -> list[SourceSnapshot]:
    result: list[SourceSnapshot] = []
    for chain in SourceChain:
        query = select(SourceSnapshot).where(
            SourceSnapshot.source_chain == chain.value
        )
        source = _active_source_config(chain)
        if source is not None and source.store_external_id:
            query = query.where(SourceSnapshot.scope == source.scope)

        row = db.scalar(
            query.order_by(SourceSnapshot.collected_at.desc()).limit(1)
        )
        if row is not None:
            result.append(row)
    return result


@app.get("/api/v1/offers/latest/{source_chain}", response_model=list[OfferCandidateOut])
def latest_offers(
    source_chain: SourceChain,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[OfferCandidateRecord]:
    latest_snapshot_query = select(OfferCandidateRecord.snapshot_id).where(
        OfferCandidateRecord.source_chain == source_chain.value
    )
    latest_snapshot_query = _apply_active_store_offer_filter(
        latest_snapshot_query,
        source_chain,
    )
    latest_snapshot_id = db.scalar(
        latest_snapshot_query
        .order_by(OfferCandidateRecord.collected_at.desc())
        .limit(1)
    )
    if latest_snapshot_id is None:
        raise HTTPException(
            status_code=404,
            detail=f"No parsed offers for {source_chain.value}",
        )

    offers_query = select(OfferCandidateRecord).where(
        OfferCandidateRecord.snapshot_id == latest_snapshot_id,
        OfferCandidateRecord.source_chain == source_chain.value,
    )
    offers_query = _apply_active_store_offer_filter(
        offers_query,
        source_chain,
    )

    return list(
        db.scalars(
            offers_query
            .order_by(OfferCandidateRecord.product_name_raw.asc())
            .limit(limit)
        ).all()
    )




UI_INDEX_PATH = Path(__file__).resolve().parent / "ui" / "index.html"


@app.get("/ui", response_class=HTMLResponse, include_in_schema=False)
def family_ui() -> HTMLResponse:
    if not UI_INDEX_PATH.exists():
        raise HTTPException(status_code=503, detail="UI bundle is not available")
    return HTMLResponse(UI_INDEX_PATH.read_text(encoding="utf-8"))


@app.get(
    "/api/v1/catalog",
    response_model=CanonicalCatalogOut,
)
def canonical_catalog(
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
    effective_date = (
        as_of
        if as_of is not None
        else datetime.now(ZoneInfo("Europe/Berlin")).date()
    )

    stmt = select(CanonicalProduct).order_by(
        CanonicalProduct.brand_normalized.asc().nulls_last(),
        CanonicalProduct.normalized_name.asc(),
        CanonicalProduct.id.asc(),
    )
    products = list(db.scalars(stmt).all())

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

    catalog_rows: list[CanonicalCatalogProductOut] = []
    for product in products:
        comparison = canonical_product_current_price_comparison(
            canonical_product_id=product.id,
            as_of=effective_date,
            db=db,
        )
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
                        for offer in comparison.offers
                        if offer.source_image_url
                    ),
                    None,
                ),
                as_of=comparison.as_of,
                timezone=comparison.timezone,
                comparison_status=comparison.comparison_status,
                comparison_available=comparison.comparison_available,
                current_offer_count=comparison.current_offer_count,
                retailer_count=comparison.retailer_count,
                lowest_price_eur=comparison.lowest_price_eur,
                current_offers=comparison.offers,
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
        timezone="Europe/Berlin",
        query=q,
        count=len(catalog_rows),
        products=catalog_rows,
    )


@app.get(
    "/api/v1/ui/overview",
    response_model=CanonicalUiOverviewOut,
)
def canonical_ui_overview(
    as_of: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> CanonicalUiOverviewOut:
    effective_date = (
        as_of
        if as_of is not None
        else datetime.now(ZoneInfo("Europe/Berlin")).date()
    )

    catalog = canonical_catalog(
        as_of=effective_date,
        q=None,
        retailer=None,
        current_only=False,
        comparison_only=False,
        sort="name",
        limit=500,
        db=db,
    )

    retailer_offer_counts: dict[str, int] = {}
    retailer_products: dict[str, set[UUID]] = {}
    retailer_lowest_prices: dict[str, Decimal] = {}

    for product in catalog.products:
        seen_product_retailers: set[str] = set()
        for offer in product.current_offers:
            chain = offer.source_chain
            retailer_offer_counts[chain] = (
                retailer_offer_counts.get(chain, 0) + 1
            )
            if chain not in seen_product_retailers:
                retailer_products.setdefault(chain, set()).add(product.id)
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

    products_with_current = sum(
        1
        for product in catalog.products
        if product.current_offer_count > 0
    )
    comparison_ready = sum(
        1
        for product in catalog.products
        if product.comparison_available
    )
    current_offer_count = sum(
        product.current_offer_count
        for product in catalog.products
    )

    return CanonicalUiOverviewOut(
        as_of=effective_date,
        timezone="Europe/Berlin",
        total_products=catalog.count,
        products_with_current_offers=products_with_current,
        products_without_current_offers=(
            catalog.count - products_with_current
        ),
        comparison_ready_products=comparison_ready,
        current_offer_count=current_offer_count,
        retailer_count=len(retailer_rows),
        retailers=retailer_rows,
    )




@app.get(
    "/api/v1/deals/current",
    response_model=CurrentDealsOut,
)
def current_deals(
    as_of: date | None = Query(default=None),
    q: str | None = Query(default=None, min_length=1, max_length=100),
    retailer: str | None = Query(default=None, max_length=32),
    view: str = Query(default="current", pattern="^(current|upcoming)$"),
    app_only: bool = Query(default=False),
    coupon_only: bool = Query(default=False),
    discount_only: bool = Query(default=False),
    image_only: bool = Query(default=False),
    sort: str = Query(
        default="name",
        pattern="^(name|price_asc|price_desc|newest|discount_desc)$",
    ),
    limit: int = Query(default=250, ge=1, le=500),
    db: Session = Depends(get_db),
) -> CurrentDealsOut:
    effective_date = (
        as_of
        if as_of is not None
        else datetime.now(ZoneInfo("Europe/Berlin")).date()
    )

    rows = list(
        db.scalars(
            select(OfferCandidateRecord).where(
                OfferCandidateRecord.source_offer_id.is_not(None),
            )
        ).all()
    )

    # Preserve the existing /deals/current contract: store scope is part
    # of the stable offer identity, not a global pre-filter. This matters
    # for retailer/store-specific observations and is covered by the
    # existing store-scope dedup regression.
    scoped_rows = rows

    def price_windows(row: OfferCandidateRecord) -> list[tuple[date, date]]:
        windows: list[tuple[date, date]] = []
        if row.valid_from is not None and row.valid_until is not None:
            windows.append((row.valid_from, row.valid_until))
        if (
            row.app_price_eur is not None
            and row.app_valid_from is not None
            and row.app_valid_until is not None
        ):
            windows.append((row.app_valid_from, row.app_valid_until))
        return windows

    def availability_state(row: OfferCandidateRecord) -> str:
        windows = price_windows(row)
        if any(start <= effective_date <= end for start, end in windows):
            return "current"
        if any(start > effective_date for start, _ in windows):
            return "upcoming"
        if windows and all(end < effective_date for _, end in windows):
            return "expired"
        return "unknown"

    # Deduplicate inside each state. A future observation with the same stable
    # retailer identity must not hide a still-current campaign observation.
    newest_by_state_identity: dict[
        tuple[str, str, str | None, str],
        OfferCandidateRecord,
    ] = {}
    for row in scoped_rows:
        if row.source_offer_id is None:
            continue
        state = availability_state(row)
        key = (
            state,
            row.source_chain,
            row.source_store_external_id,
            row.source_offer_id,
        )
        existing = newest_by_state_identity.get(key)
        if existing is None or (
            row.collected_at,
            str(row.id),
        ) > (
            existing.collected_at,
            str(existing.id),
        ):
            newest_by_state_identity[key] = row

    availability_counts = {
        "current": 0,
        "upcoming": 0,
        "unknown": 0,
        "expired": 0,
    }
    retailer_availability: dict[str, dict[str, int]] = {
        chain.value: {
            "current": 0,
            "upcoming": 0,
            "unknown": 0,
            "expired": 0,
        }
        for chain in SourceChain
    }

    # Stable source_offer_id remains the primary identity contract. A reviewed
    # completeness-rescue publication may additionally supersede an exact
    # physical-deal duplicate that arrived through another source identity.
    from app.completeness_rescue_read import (
        dedupe_completeness_rescue_publications,
    )

    visible_state_rows = dedupe_completeness_rescue_publications(
        (key[0], row)
        for key, row in newest_by_state_identity.items()
    )

    current_rows: list[OfferCandidateRecord] = []
    for state, row in visible_state_rows:
        availability_counts[state] += 1
        retailer_availability[row.source_chain][state] += 1
        if state == view:
            current_rows.append(row)

    normalized_query = q.strip().casefold() if q is not None else None
    if normalized_query:
        current_rows = [
            row
            for row in current_rows
            if normalized_query in row.product_name_raw.casefold()
            or (
                row.brand_raw is not None
                and normalized_query in row.brand_raw.casefold()
            )
            or (
                row.description_raw is not None
                and normalized_query in row.description_raw.casefold()
            )
            or (
                row.package_text_raw is not None
                and normalized_query in row.package_text_raw.casefold()
            )
        ]

    def has_app(row: OfferCandidateRecord) -> bool:
        return row.app_price_eur is not None or row.requires_app

    def has_discount(row: OfferCandidateRecord) -> bool:
        return bool(
            (
                row.regular_price_eur is not None
                and row.regular_price_eur > row.price_eur
            )
            or (
                row.discount_percent is not None
                and row.discount_percent > 0
            )
        )

    retailer_counts: dict[str, int] = {}
    for row in current_rows:
        retailer_counts[row.source_chain] = retailer_counts.get(row.source_chain, 0) + 1

    feature_counts = {
        "app": sum(1 for row in current_rows if has_app(row)),
        "coupon": sum(1 for row in current_rows if row.coupon_required),
        "discount": sum(1 for row in current_rows if has_discount(row)),
        "image": sum(1 for row in current_rows if row.source_image_url),
        "canonical": 0,
    }

    if retailer:
        retailer_key = retailer.strip().casefold()
        current_rows = [
            row for row in current_rows
            if row.source_chain.casefold() == retailer_key
        ]

    if app_only:
        current_rows = [row for row in current_rows if has_app(row)]
    if coupon_only:
        current_rows = [row for row in current_rows if row.coupon_required]
    if discount_only:
        current_rows = [row for row in current_rows if has_discount(row)]
    if image_only:
        current_rows = [row for row in current_rows if row.source_image_url]

    def saving(row: OfferCandidateRecord) -> Decimal:
        if (
            row.regular_price_eur is not None
            and row.regular_price_eur > row.price_eur
        ):
            return row.regular_price_eur - row.price_eur
        return Decimal("0")

    if sort == "price_asc":
        current_rows.sort(
            key=lambda row: (
                row.price_eur,
                row.product_name_raw.casefold(),
                row.source_chain,
            )
        )
    elif sort == "price_desc":
        current_rows.sort(
            key=lambda row: (
                -row.price_eur,
                row.product_name_raw.casefold(),
                row.source_chain,
            )
        )
    elif sort == "newest":
        current_rows.sort(
            key=lambda row: (
                -row.collected_at.timestamp(),
                row.product_name_raw.casefold(),
                row.source_chain,
            )
        )
    elif sort == "discount_desc":
        current_rows.sort(
            key=lambda row: (
                -saving(row),
                -(row.discount_percent or Decimal("0")),
                row.price_eur,
                row.product_name_raw.casefold(),
            )
        )
    else:
        current_rows.sort(
            key=lambda row: (
                row.product_name_raw.casefold(),
                (row.brand_raw or "").casefold(),
                row.price_eur,
                row.source_chain,
                row.source_store_external_id or "",
                row.source_offer_id or "",
            )
        )

    available_count = len(current_rows)
    selected_rows = current_rows[:limit]

    link_map: dict[UUID, UUID] = {}
    if selected_rows:
        links = list(
            db.scalars(
                select(OfferProductLink).where(
                    OfferProductLink.offer_candidate_id.in_(
                        [row.id for row in selected_rows]
                    )
                )
            ).all()
        )
        link_map = {
            link.offer_candidate_id: link.canonical_product_id
            for link in links
        }

    if current_rows:
        feature_counts["canonical"] = len(
            list(
                db.scalars(
                    select(OfferProductLink).where(
                        OfferProductLink.offer_candidate_id.in_(
                            [row.id for row in current_rows]
                        )
                    )
                ).all()
            )
        )

    deals = [
        CurrentDealOut(
            offer_candidate_id=row.id,
            source_chain=row.source_chain,
            source_store_external_id=row.source_store_external_id,
            source_store_name=row.source_store_name,
            source_offer_id=row.source_offer_id,
            product_name_raw=row.product_name_raw,
            brand_raw=row.brand_raw,
            package_text_raw=row.package_text_raw,
            price_eur=row.price_eur,
            regular_price_eur=row.regular_price_eur,
            unit_price_eur=row.unit_price_eur,
            unit_label=row.unit_label,
            pricing_mode=row.pricing_mode,
            regular_unit_price_eur=row.regular_unit_price_eur,
            example_weight_g=row.example_weight_g,
            discount_percent=row.discount_percent,
            app_price_eur=row.app_price_eur,
            requires_app=row.requires_app,
            coupon_required=row.coupon_required,
            valid_from=row.valid_from,
            valid_until=row.valid_until,
            app_valid_from=row.app_valid_from,
            app_valid_until=row.app_valid_until,
            source_url=row.source_url,
            source_image_url=row.source_image_url,
            collected_at=row.collected_at,
            base_price_current=(
                row.valid_from is not None
                and row.valid_until is not None
                and row.valid_from <= effective_date <= row.valid_until
            ),
            app_price_current=(
                row.app_price_eur is not None
                and row.app_valid_from is not None
                and row.app_valid_until is not None
                and row.app_valid_from <= effective_date <= row.app_valid_until
            ),
            canonical_product_id=link_map.get(row.id),
            canonical_comparable=(row.id in link_map and not _is_unit_basis_offer(row)),
        )
        for row in selected_rows
    ]

    return CurrentDealsOut(
        as_of=effective_date,
        timezone="Europe/Berlin",
        query=q,
        retailer=retailer,
        app_only=app_only,
        coupon_only=coupon_only,
        discount_only=discount_only,
        image_only=image_only,
        available_count=available_count,
        count=len(deals),
        retailer_counts=retailer_counts,
        feature_counts=feature_counts,
        availability_counts=availability_counts,
        retailer_availability=retailer_availability,
        deals=deals,
    )


@app.post(
    "/api/v1/ui/basket/compare",
    response_model=BasketCompareOut,
)
def compare_basket(
    request: BasketCompareRequest,
    db: Session = Depends(get_db),
) -> BasketCompareOut:
    if not request.items:
        raise HTTPException(
            status_code=422,
            detail="Basket must contain at least one item",
        )

    quantities: dict[UUID, int] = {}
    for item in request.items:
        if item.quantity < 1 or item.quantity > 99:
            raise HTTPException(
                status_code=422,
                detail="Basket item quantity must be between 1 and 99",
            )
        new_quantity = quantities.get(item.canonical_product_id, 0) + item.quantity
        if new_quantity > 99:
            raise HTTPException(
                status_code=422,
                detail="Merged basket item quantity must not exceed 99",
            )
        quantities[item.canonical_product_id] = new_quantity

    effective_date = (
        request.as_of
        if request.as_of is not None
        else datetime.now(ZoneInfo("Europe/Berlin")).date()
    )

    products = list(
        db.scalars(
            select(CanonicalProduct).where(
                CanonicalProduct.id.in_(quantities.keys())
            )
        ).all()
    )
    product_map = {product.id: product for product in products}

    missing_products = sorted(
        set(quantities) - set(product_map),
        key=str,
    )
    if missing_products:
        raise HTTPException(
            status_code=404,
            detail={
                "message": "Canonical product not found",
                "canonical_product_ids": [
                    str(product_id)
                    for product_id in missing_products
                ],
            },
        )

    scope_offers: dict[
        tuple[str, str | None],
        dict[UUID, CanonicalCurrentOfferOut],
    ] = {}
    scope_names: dict[
        tuple[str, str | None],
        str | None,
    ] = {}

    for product_id in quantities:
        current = canonical_product_current_offers(
            canonical_product_id=product_id,
            as_of=effective_date,
            db=db,
        )

        per_scope: dict[
            tuple[str, str | None],
            CanonicalCurrentOfferOut,
        ] = {}

        for offer in current.offers:
            scope = (
                offer.source_chain,
                offer.source_store_external_id,
            )
            existing = per_scope.get(scope)
            if existing is None or (
                offer.price_eur,
                offer.source_offer_id or "",
                str(offer.offer_candidate_id),
            ) < (
                existing.price_eur,
                existing.source_offer_id or "",
                str(existing.offer_candidate_id),
            ):
                per_scope[scope] = offer

        for scope, offer in per_scope.items():
            scope_offers.setdefault(scope, {})[product_id] = offer
            if offer.source_store_name:
                scope_names[scope] = offer.source_store_name
            else:
                scope_names.setdefault(scope, None)

    requested_ids = set(quantities)
    summaries: list[BasketRetailerSummaryOut] = []

    for scope, offers_by_product in scope_offers.items():
        source_chain, source_store_external_id = scope
        covered_ids = set(offers_by_product)
        missing_ids = sorted(
            requested_ids - covered_ids,
            key=str,
        )

        lines: list[BasketRetailerLineOut] = []
        total = Decimal("0")

        for product_id in sorted(
            covered_ids,
            key=lambda value: product_map[value].display_name.casefold(),
        ):
            product = product_map[product_id]
            offer = offers_by_product[product_id]
            quantity = quantities[product_id]
            line_total = offer.price_eur * quantity
            total += line_total

            lines.append(
                BasketRetailerLineOut(
                    canonical_product_id=product_id,
                    display_name=product.display_name,
                    quantity=quantity,
                    unit_price_eur=offer.price_eur,
                    line_total_eur=line_total,
                    source_chain=source_chain,
                    source_store_external_id=source_store_external_id,
                    source_store_name=scope_names.get(scope),
                    source_offer_id=offer.source_offer_id,
                    valid_from=offer.valid_from,
                    valid_until=offer.valid_until,
                    source_url=offer.source_url,
                    source_image_url=offer.source_image_url,
                )
            )

        summaries.append(
            BasketRetailerSummaryOut(
                source_chain=source_chain,
                source_store_external_id=source_store_external_id,
                source_store_name=scope_names.get(scope),
                requested_product_count=len(requested_ids),
                covered_product_count=len(covered_ids),
                missing_product_ids=missing_ids,
                complete_basket=not missing_ids,
                total_eur=total,
                lines=lines,
            )
        )

    summaries.sort(
        key=lambda summary: (
            -summary.covered_product_count,
            summary.source_chain,
            summary.source_store_external_id or "",
        )
    )

    complete = [
        summary
        for summary in summaries
        if summary.complete_basket
    ]
    comparison_available = len(complete) >= 2

    best_total: Decimal | None = None
    best_scopes: list[BasketRetailerSummaryOut] = []

    if comparison_available:
        best_total = min(
            summary.total_eur
            for summary in complete
        )
        best_scopes = [
            summary
            for summary in complete
            if summary.total_eur == best_total
        ]

    return BasketCompareOut(
        as_of=effective_date,
        timezone="Europe/Berlin",
        requested_product_count=len(requested_ids),
        requested_unit_count=sum(quantities.values()),
        retailer_scope_count=len(summaries),
        complete_retailer_scope_count=len(complete),
        comparison_available=comparison_available,
        best_complete_total_eur=best_total,
        best_complete_scopes=best_scopes,
        retailer_scopes=summaries,
    )


@app.get(
    "/api/v1/canonical-products",
    response_model=list[CanonicalProductOut],
)
def canonical_products(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[CanonicalProduct]:
    return list(
        db.scalars(
            select(CanonicalProduct)
            .order_by(
                CanonicalProduct.brand_normalized.asc().nulls_last(),
                CanonicalProduct.normalized_name.asc(),
                CanonicalProduct.id.asc(),
            )
            .limit(limit)
        ).all()
    )


@app.get(
    "/api/v1/canonical-products/{canonical_product_id}",
    response_model=CanonicalProductOut,
)
def canonical_product_detail(
    canonical_product_id: UUID,
    db: Session = Depends(get_db),
) -> CanonicalProduct:
    product = db.get(CanonicalProduct, canonical_product_id)
    if product is None:
        raise HTTPException(
            status_code=404,
            detail=f"Canonical product {canonical_product_id} not found",
        )
    return product



@app.get(
    "/api/v1/canonical-products/{canonical_product_id}/current-offers",
    response_model=CanonicalCurrentOffersOut,
)
def canonical_product_current_offers(
    canonical_product_id: UUID,
    as_of: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> CanonicalCurrentOffersOut:
    product = db.get(CanonicalProduct, canonical_product_id)
    if product is None:
        raise HTTPException(
            status_code=404,
            detail=f"Canonical product {canonical_product_id} not found",
        )

    effective_date = (
        as_of
        if as_of is not None
        else datetime.now(ZoneInfo("Europe/Berlin")).date()
    )

    seed_rows = db.execute(
        select(
            OfferCandidateRecord.source_chain,
            OfferCandidateRecord.source_store_external_id,
            OfferCandidateRecord.source_offer_id,
        )
        .join(
            OfferProductLink,
            OfferProductLink.offer_candidate_id == OfferCandidateRecord.id,
        )
        .where(OfferProductLink.canonical_product_id == canonical_product_id)
    ).all()

    source_keys = {
        (source_chain, store_external_id, source_offer_id)
        for source_chain, store_external_id, source_offer_id in seed_rows
        if source_offer_id is not None
    }

    current_rows: list[OfferCandidateRecord] = []
    for source_chain, store_external_id, source_offer_id in sorted(
        source_keys,
        key=lambda item: (item[0], item[1] or "", item[2]),
    ):
        store_predicate = (
            OfferCandidateRecord.source_store_external_id.is_(None)
            if store_external_id is None
            else OfferCandidateRecord.source_store_external_id
            == store_external_id
        )

        row = db.scalar(
            select(OfferCandidateRecord)
            .where(
                OfferCandidateRecord.source_chain == source_chain,
                store_predicate,
                OfferCandidateRecord.source_offer_id == source_offer_id,
                _canonical_price_eligible_clause(),
                OfferCandidateRecord.valid_from.is_not(None),
                OfferCandidateRecord.valid_until.is_not(None),
                OfferCandidateRecord.valid_from <= effective_date,
                OfferCandidateRecord.valid_until >= effective_date,
            )
            .order_by(
                OfferCandidateRecord.collected_at.desc(),
                OfferCandidateRecord.id.asc(),
            )
            .limit(1)
        )
        if row is not None:
            current_rows.append(row)

    current_rows.sort(
        key=lambda row: (
            row.price_eur,
            row.source_chain,
            row.source_store_external_id or "",
            row.source_offer_id or "",
        )
    )

    return CanonicalCurrentOffersOut(
        canonical_product_id=product.id,
        display_name=product.display_name,
        as_of=effective_date,
        timezone="Europe/Berlin",
        offers=[
            CanonicalCurrentOfferOut(
                offer_candidate_id=row.id,
                snapshot_id=row.snapshot_id,
                source_chain=row.source_chain,
                source_store_external_id=row.source_store_external_id,
                source_store_name=row.source_store_name,
                source_offer_id=row.source_offer_id,
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
            for row in current_rows
        ],
    )



@app.get(
    "/api/v1/canonical-products/{canonical_product_id}/current-price-comparison",
    response_model=CanonicalCurrentPriceComparisonOut,
)
def canonical_product_current_price_comparison(
    canonical_product_id: UUID,
    as_of: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> CanonicalCurrentPriceComparisonOut:
    current = canonical_product_current_offers(
        canonical_product_id=canonical_product_id,
        as_of=as_of,
        db=db,
    )

    retailer_keys = {
        (
            offer.source_chain,
            offer.source_store_external_id,
        )
        for offer in current.offers
    }
    retailer_count = len(retailer_keys)
    current_offer_count = len(current.offers)

    if current_offer_count == 0:
        comparison_status = "no_current_offers"
        comparison_available = False
        lowest_price_eur = None
        price_spread_eur = None
        lowest_price_offers = []
    else:
        lowest_price_eur = min(offer.price_eur for offer in current.offers)
        lowest_price_offers = [
            offer
            for offer in current.offers
            if offer.price_eur == lowest_price_eur
        ]

        if retailer_count >= 2:
            comparison_status = "multi_store_comparison"
            comparison_available = True
            highest_price_eur = max(
                offer.price_eur for offer in current.offers
            )
            price_spread_eur = highest_price_eur - lowest_price_eur
        else:
            comparison_status = "single_current_offer"
            comparison_available = False
            price_spread_eur = None

    return CanonicalCurrentPriceComparisonOut(
        canonical_product_id=current.canonical_product_id,
        display_name=current.display_name,
        as_of=current.as_of,
        timezone=current.timezone,
        comparison_status=comparison_status,
        comparison_available=comparison_available,
        current_offer_count=current_offer_count,
        retailer_count=retailer_count,
        lowest_price_eur=lowest_price_eur,
        price_spread_eur=price_spread_eur,
        lowest_price_offers=lowest_price_offers,
        offers=current.offers,
    )


@app.get(
    "/api/v1/canonical-products/{canonical_product_id}/price-history",
    response_model=CanonicalPriceHistoryOut,
)
def canonical_product_price_history(
    canonical_product_id: UUID,
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
) -> CanonicalPriceHistoryOut:
    product = db.get(CanonicalProduct, canonical_product_id)
    if product is None:
        raise HTTPException(
            status_code=404,
            detail=f"Canonical product {canonical_product_id} not found",
        )

    seed_rows = db.execute(
        select(
            OfferCandidateRecord.source_chain,
            OfferCandidateRecord.source_store_external_id,
            OfferCandidateRecord.source_offer_id,
        )
        .join(
            OfferProductLink,
            OfferProductLink.offer_candidate_id == OfferCandidateRecord.id,
        )
        .where(OfferProductLink.canonical_product_id == canonical_product_id)
    ).all()

    source_keys = {
        (source_chain, store_external_id, source_offer_id)
        for source_chain, store_external_id, source_offer_id in seed_rows
        if source_offer_id is not None
    }

    observations: list[OfferCandidateRecord] = []
    if source_keys:
        predicates = []
        for source_chain, store_external_id, source_offer_id in sorted(
            source_keys,
            key=lambda item: (item[0], item[1] or "", item[2]),
        ):
            store_predicate = (
                OfferCandidateRecord.source_store_external_id.is_(None)
                if store_external_id is None
                else OfferCandidateRecord.source_store_external_id
                == store_external_id
            )
            predicates.append(
                and_(
                    OfferCandidateRecord.source_chain == source_chain,
                    store_predicate,
                    OfferCandidateRecord.source_offer_id == source_offer_id,
                    _canonical_price_eligible_clause(),
                )
            )

        observations = list(
            db.scalars(
                select(OfferCandidateRecord)
                .where(or_(*predicates))
                .order_by(
                    OfferCandidateRecord.collected_at.desc(),
                    OfferCandidateRecord.source_chain.asc(),
                    OfferCandidateRecord.id.asc(),
                )
                .limit(limit)
            ).all()
        )

    return CanonicalPriceHistoryOut(
        canonical_product_id=product.id,
        display_name=product.display_name,
        normalized_name=product.normalized_name,
        brand_display=product.brand_display,
        brand_normalized=product.brand_normalized,
        item_quantity_value=product.item_quantity_value,
        item_quantity_unit=product.item_quantity_unit,
        pack_count=product.pack_count,
        gtin14=product.gtin14,
        observations=[
            CanonicalPriceObservationOut(
                offer_candidate_id=row.id,
                snapshot_id=row.snapshot_id,
                source_chain=row.source_chain,
                source_store_external_id=row.source_store_external_id,
                source_store_name=row.source_store_name,
                source_offer_id=row.source_offer_id,
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
            for row in observations
        ],
    )


UI_REVIEW_PATH = Path(__file__).resolve().parent / "ui" / "review.html"


def _review_get_or_404(
    db: Session,
    item_id: UUID,
):
    try:
        return get_review_item(db, item_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail="Review item not found",
        ) from exc


def _review_conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=409, detail=str(exc))


@app.get(
    "/ui/review",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def review_ui() -> HTMLResponse:
    if not UI_REVIEW_PATH.exists():
        raise HTTPException(
            status_code=503,
            detail="Review UI bundle is not available",
        )
    return HTMLResponse(
        UI_REVIEW_PATH.read_text(encoding="utf-8")
    )


@app.get("/api/v1/review-items")
def review_items(
    status: str | None = Query(default=None, max_length=32),
    source_chain: str | None = Query(
        default="lidl",
        max_length=32,
    ),
    limit: int = Query(default=250, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    rows = list_review_items(
        db,
        status=status,
        source_chain=source_chain,
        limit=limit,
    )
    return {
        "count": len(rows),
        "items": [
            review_item_dict(db, row)
            for row in rows
        ],
    }


@app.get("/api/v1/review-items/summary")
def review_items_summary(
    source_chain: str | None = Query(
        default="lidl",
        max_length=32,
    ),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return review_summary(
        db,
        source_chain=source_chain,
    )


@app.get("/api/v1/review-items/{item_id}")
def review_item(
    item_id: UUID,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return review_item_dict(
        db,
        _review_get_or_404(db, item_id),
        include_revisions=True,
    )


@app.get(
    "/api/v1/review-items/{item_id}/page-preview",
    include_in_schema=True,
    responses={200: {"content": {"image/png": {}}}},
)
def review_item_page_preview(
    item_id: UUID,
    mode: str = Query(default="page", max_length=16),
    hint_index: int | None = Query(default=None, ge=0),
    db: Session = Depends(get_db),
) -> Response:
    item = _review_get_or_404(db, item_id)
    try:
        path, source_pdf_sha256 = resolve_review_preview(
            item,
            mode=mode,
            hint_index=hint_index,
        )
    except ReviewPreviewUnavailable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        path=path,
        media_type="image/png",
        headers={
            "Cache-Control": "private, max-age=86400, immutable",
            "X-Hermes-Source-PDF-SHA256": source_pdf_sha256,
        },
    )


@app.patch("/api/v1/review-items/{item_id}")
def review_item_save(
    item_id: UUID,
    request: ReviewDraftRequest,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    _review_get_or_404(db, item_id)
    try:
        row = save_review_draft(
            db,
            item_id=item_id,
            corrections=request.corrections,
            note=request.note,
            needs_followup=request.needs_followup,
        )
    except (ValueError, RuntimeError) as exc:
        raise _review_conflict(exc) from exc
    return review_item_dict(
        db,
        row,
        include_revisions=True,
    )


@app.post("/api/v1/review-items/{item_id}/approve")
def review_item_approve(
    item_id: UUID,
    request: ReviewDecisionRequest,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    _review_get_or_404(db, item_id)
    try:
        row = approve_review_item(
            db,
            item_id=item_id,
            note=request.note,
        )
    except (ValueError, RuntimeError) as exc:
        raise _review_conflict(exc) from exc
    return review_item_dict(
        db,
        row,
        include_revisions=True,
    )


@app.post("/api/v1/review-items/{item_id}/reject")
def review_item_reject(
    item_id: UUID,
    request: ReviewDecisionRequest,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    _review_get_or_404(db, item_id)
    try:
        row = reject_review_item(
            db,
            item_id=item_id,
            note=request.note,
        )
    except (ValueError, RuntimeError) as exc:
        raise _review_conflict(exc) from exc
    return review_item_dict(
        db,
        row,
        include_revisions=True,
    )


@app.post("/api/v1/review-items/{item_id}/reopen")
def review_item_reopen(
    item_id: UUID,
    request: ReviewDecisionRequest,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    _review_get_or_404(db, item_id)
    try:
        row = reopen_review_item(
            db,
            item_id=item_id,
            note=request.note,
        )
    except (ValueError, RuntimeError) as exc:
        raise _review_conflict(exc) from exc
    return review_item_dict(
        db,
        row,
        include_revisions=True,
    )


@app.post(
    "/api/v1/review-items/{item_id}/page-alert/hints/{hint_index}/create",
    include_in_schema=True,
)
def create_review_from_page_alert_hint_route(
    item_id: UUID,
    hint_index: int,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    _review_get_or_404(db, item_id)
    try:
        row = create_review_from_page_alert_hint(
            db,
            alert_item_id=item_id,
            hint_index=hint_index,
        )
    except (ValueError, RuntimeError) as exc:
        raise _review_conflict(exc) from exc
    return review_item_dict(
        db,
        row,
        include_revisions=True,
    )


@app.post(
    "/api/v1/review-items/{item_id}/approve-scope-only",
    include_in_schema=True,
)
def approve_scope_only_review_item_route(
    item_id: UUID,
    db: Session = Depends(get_db),
):
    from app.review_queue import (
        approve_scope_only_review_item,
        review_item_dict,
    )

    try:
        row = approve_scope_only_review_item(db, item_id=item_id)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return review_item_dict(db, row, include_revisions=True)
