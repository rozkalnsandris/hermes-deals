from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.current_deals_sql_loader import (
    _InactiveWinner,
    load_sql_ranked_state_rows,
    materialize_only,
)
from app.db import engine
from app.models import OfferCandidateRecord, SourceSnapshot


pytestmark = pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="requires the PostgreSQL 18 CI service",
)


def _snapshot(session: Session, collected_at: datetime) -> SourceSnapshot:
    row = SourceSnapshot(
        id=uuid4(),
        source_chain="lidl",
        source_url="https://postgres-runtime.test/source",
        collected_at=collected_at,
        content_bytes=1,
        strategy_hint="postgres_runtime_test",
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
    valid_from: date,
    valid_until: date,
    product_name: str | None = None,
    source_url: str | None = None,
    raw_payload: dict | None = None,
) -> OfferCandidateRecord:
    return OfferCandidateRecord(
        id=uuid4(),
        source_chain="lidl",
        source_store_external_id="postgres-runtime",
        source_store_name="PostgreSQL Runtime Test",
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
        source_url=source_url or "https://postgres-runtime.test/deal",
        source_image_url=None,
        snapshot_id=snapshot_id,
        collected_at=collected_at,
        parser_version="postgres-runtime-test",
        raw_payload=raw_payload or {},
    )


def test_sql_ranked_loader_executes_on_postgresql_18() -> None:
    assert engine.dialect.name == "postgresql"

    effective_date = date(2026, 8, 6)
    collected = datetime(2026, 8, 5, 8, tzinfo=timezone.utc)
    with Session(engine) as session:
        snapshot = _snapshot(session, collected)
        shared = {
            "snapshot_id": snapshot.id,
            "collected_at": collected,
            "valid_from": effective_date,
            "valid_until": date(2026, 8, 8),
            "product_name": "Shared PostgreSQL physical deal",
            "source_url": "https://postgres-runtime.test/shared",
        }
        ordinary = _offer(
            source_offer_id=f"ordinary-{uuid4()}",
            **shared,
        )
        rescue = _offer(
            source_offer_id=f"rescue-{uuid4()}",
            raw_payload={
                "price_basis": "completeness_rescue_review",
                "review_original_payload": {
                    "completeness_rescue": {
                        "candidate_key": "postgres-runtime-candidate"
                    }
                },
            },
            **shared,
        )
        upcoming = _offer(
            snapshot_id=snapshot.id,
            source_offer_id=f"upcoming-{uuid4()}",
            collected_at=collected,
            valid_from=date(2026, 8, 9),
            valid_until=date(2026, 8, 10),
        )
        expired = _offer(
            snapshot_id=snapshot.id,
            source_offer_id=f"expired-{uuid4()}",
            collected_at=collected,
            valid_from=date(2026, 7, 1),
            valid_until=date(2026, 7, 2),
        )
        ordinary_id = ordinary.id
        rescue_id = rescue.id
        session.add_all([ordinary, rescue, upcoming, expired])
        session.commit()

        with materialize_only("current"):
            rows = load_sql_ranked_state_rows(session, effective_date)

    current = [row for state, row in rows if state == "current"]
    upcoming_rows = [row for state, row in rows if state == "upcoming"]
    expired_rows = [row for state, row in rows if state == "expired"]

    assert rescue_id in {row.id for row in current}
    assert ordinary_id not in {row.id for row in current}
    assert any(isinstance(row, _InactiveWinner) for row in upcoming_rows)
    assert any(isinstance(row, _InactiveWinner) for row in expired_rows)
