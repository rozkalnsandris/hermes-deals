from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

from fastapi import Response
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.current_deals_route_installer import installed_fast_current_deals
from app.current_deals_sql_loader import (
    _InactiveWinner,
    load_sql_ranked_state_rows,
)
from app.models import Base, OfferCandidateRecord, SourceSnapshot


def _snapshot(session: Session, collected_at: datetime) -> SourceSnapshot:
    row = SourceSnapshot(
        id=uuid4(),
        source_chain="lidl",
        source_url="https://example.test/source",
        collected_at=collected_at,
        content_bytes=1,
        strategy_hint="test",
        success=True,
    )
    session.add(row)
    session.flush()
    return row


def _offer(
    *,
    snapshot_id,
    source_offer_id: str,
    collected_at: datetime,
    valid_from: date | None,
    valid_until: date | None,
    product_name: str | None = None,
    source_url: str | None = None,
    raw_payload: dict | None = None,
) -> OfferCandidateRecord:
    return OfferCandidateRecord(
        id=uuid4(),
        source_chain="lidl",
        source_store_external_id=None,
        source_store_name=None,
        source_offer_id=source_offer_id,
        product_name_raw=product_name or f"Product {source_offer_id}",
        brand_raw="Brand",
        description_raw=None,
        package_text_raw="1 Packung",
        price_eur=Decimal("1.99"),
        regular_price_eur=Decimal("2.49"),
        unit_price_eur=None,
        unit_label=None,
        pricing_mode="fixed_package",
        regular_unit_price_eur=None,
        example_weight_g=None,
        discount_percent=20,
        app_price_eur=None,
        requires_app=False,
        coupon_required=False,
        valid_from=valid_from,
        valid_until=valid_until,
        app_valid_from=None,
        app_valid_until=None,
        source_url=source_url or "https://example.test/deal",
        source_image_url=None,
        snapshot_id=snapshot_id,
        collected_at=collected_at,
        parser_version="test",
        raw_payload=raw_payload or {},
    )


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_sql_loader_materializes_only_current_and_upcoming_winners() -> None:
    session = _session()
    old_time = datetime(2026, 8, 1, 8, tzinfo=timezone.utc)
    new_time = datetime(2026, 8, 5, 8, tzinfo=timezone.utc)
    old_snapshot = _snapshot(session, old_time)
    new_snapshot = _snapshot(session, new_time)

    old_current = _offer(
        snapshot_id=old_snapshot.id,
        source_offer_id="stable-current",
        collected_at=old_time,
        valid_from=date(2026, 8, 6),
        valid_until=date(2026, 8, 8),
    )
    new_current = _offer(
        snapshot_id=new_snapshot.id,
        source_offer_id="stable-current",
        collected_at=new_time,
        valid_from=date(2026, 8, 6),
        valid_until=date(2026, 8, 8),
    )
    upcoming = _offer(
        snapshot_id=new_snapshot.id,
        source_offer_id="upcoming",
        collected_at=new_time,
        valid_from=date(2026, 8, 9),
        valid_until=date(2026, 8, 10),
    )
    expired = [
        _offer(
            snapshot_id=new_snapshot.id,
            source_offer_id=f"expired-{index}",
            collected_at=new_time,
            valid_from=date(2026, 7, 1),
            valid_until=date(2026, 7, 2),
        )
        for index in range(40)
    ]
    session.add_all([old_current, new_current, upcoming, *expired])
    session.commit()

    rows = load_sql_ranked_state_rows(session, date(2026, 8, 6))
    counts = Counter(state for state, _row in rows)

    assert counts == {"current": 1, "upcoming": 1, "expired": 40}
    current_rows = [row for state, row in rows if state == "current"]
    upcoming_rows = [row for state, row in rows if state == "upcoming"]
    expired_rows = [row for state, row in rows if state == "expired"]

    assert current_rows == [new_current]
    assert upcoming_rows == [upcoming]
    assert all(isinstance(row, _InactiveWinner) for row in expired_rows)
    assert old_current not in current_rows


def test_sql_loader_preserves_completeness_rescue_preference() -> None:
    session = _session()
    collected = datetime(2026, 8, 5, 8, tzinfo=timezone.utc)
    snapshot = _snapshot(session, collected)
    shared = {
        "snapshot_id": snapshot.id,
        "collected_at": collected,
        "valid_from": date(2026, 8, 6),
        "valid_until": date(2026, 8, 8),
        "product_name": "Shared physical deal",
        "source_url": "https://example.test/shared",
    }
    ordinary = _offer(
        source_offer_id="ordinary-source-id",
        **shared,
    )
    rescue = _offer(
        source_offer_id="review-rescue-id",
        raw_payload={
            "price_basis": "completeness_rescue_review",
            "review_original_payload": {
                "completeness_rescue": {"candidate_key": "candidate-1"}
            },
        },
        **shared,
    )
    session.add_all([ordinary, rescue])
    session.commit()

    rows = load_sql_ranked_state_rows(session, date(2026, 8, 6))
    current = [row for state, row in rows if state == "current"]

    assert current == [rescue]


def test_installed_route_reports_server_timing_and_engine() -> None:
    session = _session()
    collected = datetime(2026, 8, 5, 8, tzinfo=timezone.utc)
    snapshot = _snapshot(session, collected)
    session.add(
        _offer(
            snapshot_id=snapshot.id,
            source_offer_id="current",
            collected_at=collected,
            valid_from=date(2026, 8, 6),
            valid_until=date(2026, 8, 8),
        )
    )
    session.commit()
    response = Response()

    payload = installed_fast_current_deals(
        response=response,
        as_of=date(2026, 8, 6),
        q=None,
        retailer=None,
        view="current",
        app_only=False,
        coupon_only=False,
        discount_only=False,
        image_only=False,
        sort="name",
        offset=0,
        limit=12,
        db=session,
    )

    assert payload.available_count == 1
    assert response.headers["server-timing"].startswith(
        "current-deals-sql;dur="
    )
    assert response.headers["x-hermes-current-deals-engine"] == (
        "sql-ranked-active-only"
    )
    assert "stale-while-revalidate=45" in response.headers["cache-control"]
