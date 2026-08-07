from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import Session

from app.current_deals_sql_loader import (
    load_sql_ranked_state_rows,
    materialize_only,
)
from app.models import Base, OfferCandidateRecord, SourceSnapshot


def test_requested_view_loader_defers_raw_payload_with_raiseload() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    snapshot_id = uuid4()
    offer_id = uuid4()

    with Session(engine) as session:
        session.add(
            SourceSnapshot(
                id=snapshot_id,
                source_chain="lidl",
                source_url="https://defer.test/snapshot",
                collected_at=datetime(2026, 8, 6, 8, tzinfo=timezone.utc),
                content_bytes=1,
                strategy_hint="raw_payload_defer_test",
                success=True,
            )
        )
        session.add(
            OfferCandidateRecord(
                id=offer_id,
                source_chain="lidl",
                source_store_external_id="defer-store",
                source_store_name="Defer Store",
                source_offer_id="defer-offer",
                product_name_raw="Defer product",
                brand_raw="Brand",
                description_raw="Searchable description",
                package_text_raw="1 Packung",
                price_eur=Decimal("1.99"),
                regular_price_eur=Decimal("2.49"),
                pricing_mode="fixed_package",
                discount_percent=20,
                requires_app=False,
                coupon_required=False,
                valid_from=date(2026, 8, 6),
                valid_until=date(2026, 8, 8),
                source_url="https://defer.test/deal",
                snapshot_id=snapshot_id,
                collected_at=datetime(2026, 8, 6, 8, tzinfo=timezone.utc),
                parser_version="defer-test",
                raw_payload={"large": "x" * 4096},
            )
        )
        session.commit()
        session.expunge_all()

        with materialize_only("current"):
            state_rows = load_sql_ranked_state_rows(session, date(2026, 8, 6))

        current_rows = [row for state, row in state_rows if state == "current"]
        assert len(current_rows) == 1
        row = current_rows[0]
        assert row.id == offer_id
        assert row.product_name_raw == "Defer product"
        assert "raw_payload" in inspect(row).unloaded
        with pytest.raises(InvalidRequestError):
            _ = row.raw_payload
