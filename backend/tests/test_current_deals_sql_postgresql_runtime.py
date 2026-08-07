from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from time import perf_counter
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.current_deals_sql_loader import (
    _InactiveWinner,
    _winner_metadata_query,
    load_sql_ranked_state_rows,
    materialize_only,
)
from app.db import engine
from app.models import OfferCandidateRecord, SourceSnapshot


# Keep this integration contract out of the normal SQLite full-suite job.
pytestmark = pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="requires the PostgreSQL 18 CI service",
)

_SCALE_SOURCE_CHAIN = "postgres-scale"
_SCALE_STORE_ID = "postgres-scale"
_SCALE_HISTORY_DEPTH = 8
_SCALE_IDENTITIES_PER_STATE = 900
_SCALE_STATES = ("current", "upcoming", "expired")
_SCALE_QUERY_BUDGET_SECONDS = 0.95


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


def _scale_window(state: str, effective_date: date) -> tuple[date, date]:
    if state == "current":
        return effective_date - timedelta(days=1), effective_date + timedelta(days=2)
    if state == "upcoming":
        return effective_date + timedelta(days=3), effective_date + timedelta(days=5)
    if state == "expired":
        return effective_date - timedelta(days=10), effective_date - timedelta(days=8)
    raise AssertionError(f"unexpected state: {state}")


def _plan_nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _plan_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _plan_nodes(child)


def _load_explain_plan(session: Session, effective_date: date) -> dict:
    statement = _winner_metadata_query(effective_date)
    compiled = statement.compile(
        dialect=engine.dialect,
        compile_kwargs={"literal_binds": True},
    )
    payload = session.execute(
        text(
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "
            + str(compiled)
        )
    ).scalar_one()
    if isinstance(payload, str):
        payload = json.loads(payload)
    assert isinstance(payload, list) and len(payload) == 1
    assert isinstance(payload[0], dict)
    return payload[0]


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


def test_sql_ranked_loader_scales_without_postgresql_temp_spill() -> None:
    assert engine.dialect.name == "postgresql"

    effective_date = date(2026, 8, 6)
    base_collected = datetime(2026, 8, 1, 6, tzinfo=timezone.utc)
    snapshot_rows = []
    snapshot_ids = []
    for history_index in range(_SCALE_HISTORY_DEPTH):
        snapshot_id = uuid5(
            NAMESPACE_URL,
            f"hermes-deals-postgres-scale-snapshot-{history_index}",
        )
        snapshot_ids.append(snapshot_id)
        snapshot_rows.append(
            {
                "id": snapshot_id,
                "source_chain": _SCALE_SOURCE_CHAIN,
                "source_url": (
                    "https://postgres-scale.test/source/"
                    f"{history_index}"
                ),
                "collected_at": base_collected + timedelta(hours=history_index),
                "content_bytes": 1,
                "keyword_hits": {},
                "json_ld_blocks": 0,
                "strategy_hint": "postgres_scale_test",
                "success": True,
            }
        )

    offer_rows = []
    for state in _SCALE_STATES:
        valid_from, valid_until = _scale_window(state, effective_date)
        for identity_index in range(_SCALE_IDENTITIES_PER_STATE):
            source_offer_id = f"scale-{state}-{identity_index:04d}"
            for history_index, snapshot_id in enumerate(snapshot_ids):
                collected_at = base_collected + timedelta(hours=history_index)
                offer_rows.append(
                    {
                        "id": uuid5(
                            NAMESPACE_URL,
                            "hermes-deals-postgres-scale-offer-"
                            f"{state}-{identity_index}-{history_index}",
                        ),
                        "source_chain": _SCALE_SOURCE_CHAIN,
                        "source_store_external_id": _SCALE_STORE_ID,
                        "source_store_name": "PostgreSQL Scale Test",
                        "source_offer_id": source_offer_id,
                        "product_name_raw": (
                            f"Scale {state} product {identity_index:04d}"
                        ),
                        "brand_raw": "Scale Brand",
                        "description_raw": None,
                        "package_text_raw": "1 Packung",
                        "price_eur": Decimal(
                            f"{1 + (identity_index % 9)}.99"
                        ),
                        "regular_price_eur": Decimal(
                            f"{2 + (identity_index % 9)}.49"
                        ),
                        "unit_price_eur": None,
                        "unit_label": None,
                        "pricing_mode": "fixed_package",
                        "regular_unit_price_eur": None,
                        "example_weight_g": None,
                        "discount_percent": 10,
                        "app_price_eur": None,
                        "requires_app": False,
                        "coupon_required": False,
                        "valid_from": valid_from,
                        "valid_until": valid_until,
                        "app_valid_from": None,
                        "app_valid_until": None,
                        "source_url": (
                            "https://postgres-scale.test/deal/"
                            f"{state}/{identity_index:04d}"
                        ),
                        "source_image_url": None,
                        "snapshot_id": snapshot_id,
                        "collected_at": collected_at,
                        "parser_version": "postgres-scale-v1",
                        "raw_payload": {},
                    }
                )

    with Session(engine) as session:
        with materialize_only("current"):
            baseline_rows = load_sql_ranked_state_rows(session, effective_date)
        baseline_counts = Counter(state for state, _ in baseline_rows)

        session.execute(SourceSnapshot.__table__.insert(), snapshot_rows)
        session.execute(OfferCandidateRecord.__table__.insert(), offer_rows)
        session.commit()
        session.execute(text("ANALYZE offer_candidates"))
        session.commit()

        plan = _load_explain_plan(session, effective_date)
        plan_nodes = list(_plan_nodes(plan.get("Plan", {})))
        assert plan_nodes

        with materialize_only("current"):
            started = perf_counter()
            rows = load_sql_ranked_state_rows(session, effective_date)
            elapsed_seconds = perf_counter() - started

    counts = Counter(state for state, _ in rows)
    for state in _SCALE_STATES:
        assert counts[state] - baseline_counts[state] == _SCALE_IDENTITIES_PER_STATE

    synthetic_current = [
        row
        for state, row in rows
        if state == "current"
        and isinstance(row, OfferCandidateRecord)
        and row.source_chain == _SCALE_SOURCE_CHAIN
    ]
    assert len(synthetic_current) == _SCALE_IDENTITIES_PER_STATE
    assert len({row.source_offer_id for row in synthetic_current}) == (
        _SCALE_IDENTITIES_PER_STATE
    )

    synthetic_inactive = [
        row
        for state, row in rows
        if state in {"upcoming", "expired"}
        and isinstance(row, _InactiveWinner)
        and row.source_chain == _SCALE_SOURCE_CHAIN
    ]
    assert len(synthetic_inactive) == 2 * _SCALE_IDENTITIES_PER_STATE

    explain_execution_ms = float(plan["Execution Time"])
    assert explain_execution_ms < _SCALE_QUERY_BUDGET_SECONDS * 1000
    assert elapsed_seconds < _SCALE_QUERY_BUDGET_SECONDS

    temp_read_blocks = sum(
        int(node.get("Temp Read Blocks", 0) or 0)
        for node in plan_nodes
    )
    temp_written_blocks = sum(
        int(node.get("Temp Written Blocks", 0) or 0)
        for node in plan_nodes
    )
    assert temp_read_blocks == 0
    assert temp_written_blocks == 0
    assert all(node.get("Sort Space Type") != "Disk" for node in plan_nodes)
    assert all(
        "external" not in str(node.get("Sort Method", "")).casefold()
        for node in plan_nodes
    )
    assert all(int(node.get("Hash Batches", 1) or 1) == 1 for node in plan_nodes)

    total_offer_rows = len(offer_rows) + sum(baseline_counts.values())
    node_actual_rows = [
        int(node.get("Actual Rows", 0) or 0)
        * int(node.get("Actual Loops", 1) or 1)
        for node in plan_nodes
    ]
    max_node_actual_rows = max(node_actual_rows, default=0)
    assert max_node_actual_rows <= total_offer_rows * 2

    summary = {
        "synthetic_offer_rows": len(offer_rows),
        "stable_identities": len(_SCALE_STATES) * _SCALE_IDENTITIES_PER_STATE,
        "history_depth": _SCALE_HISTORY_DEPTH,
        "explain_execution_ms": round(explain_execution_ms, 3),
        "loader_elapsed_ms": round(elapsed_seconds * 1000, 3),
        "temp_read_blocks": temp_read_blocks,
        "temp_written_blocks": temp_written_blocks,
        "max_node_actual_rows_x_loops": max_node_actual_rows,
    }
    print("POSTGRES_CURRENT_DEALS_SCALE=" + json.dumps(summary, sort_keys=True))
