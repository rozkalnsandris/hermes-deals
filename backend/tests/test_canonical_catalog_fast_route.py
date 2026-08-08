from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

from fastapi import Response
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.canonical_catalog_fast_route import (
    installed_fast_canonical_catalog,
    installed_fast_canonical_ui_overview,
    load_current_offers_by_product,
)
from app.canonical_catalog_route_installer import (
    installed_fast_canonical_catalog as installed_catalog_route,
    installed_fast_canonical_ui_overview as installed_overview_route,
)
from app.main import app
from app.models import (
    Base,
    CanonicalProduct,
    OfferCandidateRecord,
    OfferProductLink,
)


AS_OF = date(2026, 8, 6)


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return engine, Session(engine, expire_on_commit=False)


def _product(
    db: Session,
    *,
    name: str,
    brand: str | None = None,
) -> CanonicalProduct:
    row = CanonicalProduct(
        id=uuid4(),
        display_name=name,
        normalized_name=name.casefold(),
        brand_display=brand,
        brand_normalized=brand.casefold() if brand else None,
    )
    db.add(row)
    db.flush()
    return row


def _offer(
    db: Session,
    *,
    source_offer_id: str,
    price: str,
    collected_at: datetime,
    source_chain: str = "lidl",
    store_id: str | None = None,
    valid_from: date = date(2026, 8, 4),
    valid_until: date = date(2026, 8, 8),
    pricing_mode: str | None = "fixed_package",
    image_url: str | None = None,
) -> OfferCandidateRecord:
    row = OfferCandidateRecord(
        id=uuid4(),
        source_chain=source_chain,
        source_store_external_id=store_id,
        source_offer_id=source_offer_id,
        product_name_raw=f"Offer {source_offer_id}",
        price_eur=Decimal(price),
        pricing_mode=pricing_mode,
        valid_from=valid_from,
        valid_until=valid_until,
        source_url=f"https://example.test/{source_offer_id}",
        source_image_url=image_url,
        snapshot_id=uuid4(),
        collected_at=collected_at,
        parser_version="test-v1",
        raw_payload={},
    )
    db.add(row)
    db.flush()
    return row


def _link(
    db: Session,
    product: CanonicalProduct,
    offer: OfferCandidateRecord,
) -> None:
    db.add(
        OfferProductLink(
            id=uuid4(),
            offer_candidate_id=offer.id,
            canonical_product_id=product.id,
            source_match_candidate_id=None,
            link_method="test",
        )
    )
    db.flush()


def _select_count(engine, call):
    statements: list[str] = []

    def before_cursor_execute(
        _conn,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        payload = call()
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)
    return payload, len(statements)


def test_fast_routes_replace_legacy_catalog_and_overview_registrations() -> None:
    catalog_routes = [
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/catalog"
    ]
    overview_routes = [
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/ui/overview"
    ]

    assert len(catalog_routes) == 1
    assert catalog_routes[0].endpoint is installed_catalog_route
    assert len(overview_routes) == 1
    assert overview_routes[0].endpoint is installed_overview_route


def test_batch_loader_keeps_latest_eligible_current_row_per_stable_identity() -> None:
    engine, db = _session()
    try:
        product = _product(db, name="Milk")
        linked_old = _offer(
            db,
            source_offer_id="stable-1",
            price="2.49",
            collected_at=datetime(2026, 8, 4, 8, tzinfo=timezone.utc),
            store_id=None,
            image_url="https://example.test/old.jpg",
        )
        _link(db, product, linked_old)

        _offer(
            db,
            source_offer_id="stable-1",
            price="1.99",
            collected_at=datetime(2026, 8, 5, 8, tzinfo=timezone.utc),
            store_id=None,
            image_url="https://example.test/new.jpg",
        )
        _offer(
            db,
            source_offer_id="stable-1",
            price="0.99",
            collected_at=datetime(2026, 8, 6, 8, tzinfo=timezone.utc),
            store_id=None,
            pricing_mode="unit_price_only",
        )
        _offer(
            db,
            source_offer_id="stable-1",
            price="0.79",
            collected_at=datetime(2026, 8, 7, 8, tzinfo=timezone.utc),
            store_id=None,
            valid_from=date(2026, 8, 10),
            valid_until=date(2026, 8, 15),
        )
        db.commit()

        rows = load_current_offers_by_product(
            db,
            [product.id],
            as_of=AS_OF,
        )[product.id]

        assert len(rows) == 1
        assert rows[0].price_eur == Decimal("1.99")
        assert rows[0].source_image_url == "https://example.test/new.jpg"
    finally:
        db.close()
        engine.dispose()


def test_catalog_query_count_is_bounded_as_product_count_grows() -> None:
    def build(product_count: int):
        engine, db = _session()
        for index in range(product_count):
            product = _product(db, name=f"Product {index:03d}")
            seed = _offer(
                db,
                source_offer_id=f"offer-{index:03d}",
                price=f"{1 + index / 100:.2f}",
                collected_at=datetime(
                    2026,
                    8,
                    5,
                    8,
                    index % 60,
                    tzinfo=timezone.utc,
                ),
                source_chain="lidl" if index % 2 == 0 else "netto",
                store_id=None if index % 3 else "store-1",
            )
            _link(db, product, seed)
        db.commit()
        return engine, db

    small_engine, small_db = build(1)
    large_engine, large_db = build(30)
    try:
        _, small_count = _select_count(
            small_engine,
            lambda: installed_fast_canonical_catalog(
                response=Response(),
                as_of=AS_OF,
                q=None,
                retailer=None,
                current_only=False,
                comparison_only=False,
                sort="name",
                limit=100,
                db=small_db,
            ),
        )
        large_payload, large_count = _select_count(
            large_engine,
            lambda: installed_fast_canonical_catalog(
                response=Response(),
                as_of=AS_OF,
                q=None,
                retailer=None,
                current_only=False,
                comparison_only=False,
                sort="name",
                limit=100,
                db=large_db,
            ),
        )

        assert small_count == 2
        assert large_count == small_count
        assert large_payload.count == 30
    finally:
        small_db.close()
        large_db.close()
        small_engine.dispose()
        large_engine.dispose()


def test_catalog_preserves_retailer_comparison_and_primary_image_semantics() -> None:
    engine, db = _session()
    try:
        product = _product(db, name="Coffee", brand="Brand")
        lidl = _offer(
            db,
            source_offer_id="coffee-lidl",
            price="3.99",
            collected_at=datetime(2026, 8, 5, 8, tzinfo=timezone.utc),
            source_chain="lidl",
            image_url="https://example.test/lidl.jpg",
        )
        netto = _offer(
            db,
            source_offer_id="coffee-netto",
            price="4.49",
            collected_at=datetime(2026, 8, 5, 9, tzinfo=timezone.utc),
            source_chain="netto",
            store_id="5659",
            image_url="https://example.test/netto.jpg",
        )
        _link(db, product, lidl)
        _link(db, product, netto)
        db.commit()

        payload = installed_fast_canonical_catalog(
            response=Response(),
            as_of=AS_OF,
            q="coffee",
            retailer=None,
            current_only=True,
            comparison_only=True,
            sort="price_asc",
            limit=100,
            db=db,
        )

        assert payload.count == 1
        row = payload.products[0]
        assert row.id == product.id
        assert row.comparison_status == "multi_store_comparison"
        assert row.comparison_available is True
        assert row.current_offer_count == 2
        assert row.retailer_count == 2
        assert row.lowest_price_eur == Decimal("3.99")
        assert row.primary_image_url == "https://example.test/lidl.jpg"
        assert [offer.price_eur for offer in row.current_offers] == [
            Decimal("3.99"),
            Decimal("4.49"),
        ]
    finally:
        db.close()
        engine.dispose()


def test_overview_is_not_capped_at_500_products() -> None:
    engine, db = _session()
    try:
        for index in range(505):
            _product(db, name=f"Product {index:03d}")
        db.commit()

        payload, select_count = _select_count(
            engine,
            lambda: installed_fast_canonical_ui_overview(
                response=Response(),
                as_of=AS_OF,
                db=db,
            ),
        )

        assert select_count == 2
        assert payload.total_products == 505
        assert payload.products_with_current_offers == 0
        assert payload.products_without_current_offers == 505
        assert payload.current_offer_count == 0
        assert payload.retailer_count == 0
    finally:
        db.close()
        engine.dispose()


def test_overview_counts_store_scopes_and_retailer_products_like_catalog() -> None:
    engine, db = _session()
    try:
        first = _product(db, name="First")
        second = _product(db, name="Second")

        first_lidl = _offer(
            db,
            source_offer_id="first-lidl",
            price="1.99",
            collected_at=datetime(2026, 8, 5, 8, tzinfo=timezone.utc),
            source_chain="lidl",
        )
        first_netto = _offer(
            db,
            source_offer_id="first-netto",
            price="2.49",
            collected_at=datetime(2026, 8, 5, 9, tzinfo=timezone.utc),
            source_chain="netto",
            store_id="5659",
        )
        second_lidl = _offer(
            db,
            source_offer_id="second-lidl",
            price="0.99",
            collected_at=datetime(2026, 8, 5, 10, tzinfo=timezone.utc),
            source_chain="lidl",
        )
        _link(db, first, first_lidl)
        _link(db, first, first_netto)
        _link(db, second, second_lidl)
        db.commit()

        payload = installed_fast_canonical_ui_overview(
            response=Response(),
            as_of=AS_OF,
            db=db,
        )
        retailers = {
            row.source_chain: row
            for row in payload.retailers
        }

        assert payload.total_products == 2
        assert payload.products_with_current_offers == 2
        assert payload.comparison_ready_products == 1
        assert payload.current_offer_count == 3
        assert retailers["lidl"].current_offer_count == 2
        assert retailers["lidl"].current_product_count == 2
        assert retailers["lidl"].lowest_price_eur == Decimal("0.99")
        assert retailers["netto"].current_offer_count == 1
        assert retailers["netto"].current_product_count == 1
        assert retailers["netto"].lowest_price_eur == Decimal("2.49")
    finally:
        db.close()
        engine.dispose()
