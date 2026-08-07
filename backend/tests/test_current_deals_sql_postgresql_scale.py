from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from time import perf_counter
from uuid import uuid4

import pytest
from fastapi import Response
from sqlalchemy import insert, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app import current_deals_fast_route as fast_route
from app.current_deals_route_installer import installed_fast_current_deals
from app.current_deals_sql_loader import _winner_metadata_query
from app.db import engine
from app.models import OfferCandidateRecord, SourceSnapshot


pytestmark = pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="scale/EXPLAIN contract requires PostgreSQL",
)

_EFFECTIVE_DATE = date(2026, 8, 6)
_IDENTITY_COUNT = 1_500
_SNAPSHOT_COUNT = 8
_HISTORY_ROW_COUNT = _IDENTITY_COUNT * _SNAPSHOT_COUNT
_EXPECTED_CURRENT = _IDENTITY_COUNT // 4
_EXPECTED_UPCOMING = _IDENTITY_COUNT // 4
_EXPECTED_EXPIRED = _IDENTITY_COUNT - _EXPECTED_CURRENT - _EXPECTED_UPCOMING
_SQL_BUDGET_MS = 1_000.0
_HANDLER_BUDGET_MS = 1_000.0
_WARM_HANDLER_BUDGET_MS = 150.0


def _window(identity_index: int) -> tuple[date, date]:
    state = identity_index % 4
    if state == 0:
        return _EFFECTIVE_DATE, date(2026, 8, 8)
    if state == 1:
        return date(2026, 8, 9), date(2026, 8, 10)
    return date(2026, 7, 1), date(2026, 7, 2)


def _seed_scale_history() -> None:
    collected_base = datetime(2026, 7, 29, 6, tzinfo=timezone.utc)
    snapshot_ids = [uuid4() for _ in range(_SNAPSHOT_COUNT)]

    with engine.begin() as connection:
        # This runs only against the ephemeral PostgreSQL CI database.
        connection.execute(text("TRUNCATE TABLE source_snapshots CASCADE"))
        connection.execute(
            insert(SourceSnapshot),
            [
                {
                    "id": snapshot_id,
                    "source_chain": "lidl",
                    "source_url": (
                        "https://scale.test/snapshot/"
                        f"{snapshot_index}"
                    ),
                    "collected_at": collected_base
                    + timedelta(hours=snapshot_index),
                    "content_bytes": 1,
                    "strategy_hint": "postgres_scale_test",
                    "success": True,
                }
                for snapshot_index, snapshot_id in enumerate(snapshot_ids)
            ],
        )

        batch: list[dict[str, object]] = []
        for snapshot_index, snapshot_id in enumerate(snapshot_ids):
            collected_at = collected_base + timedelta(hours=snapshot_index)
            for identity_index in range(_IDENTITY_COUNT):
                valid_from, valid_until = _window(identity_index)
                chain = ("lidl", "aldi_nord", "netto", "edeka")[
                    identity_index % 4
                ]
                batch.append(
                    {
                        "id": uuid4(),
                        "source_chain": chain,
                        "source_store_external_id": (
                            f"scale-store-{identity_index % 8}"
                        ),
                        "source_store_name": "PostgreSQL Scale Test",
                        "source_offer_id": f"scale-offer-{identity_index:04d}",
                        "product_name_raw": (
                            f"Scale product {identity_index:04d}"
                        ),
                        "brand_raw": "Scale Brand",
                        "package_text_raw": "1 Packung",
                        "price_eur": Decimal("1.99"),
                        "regular_price_eur": Decimal("2.49"),
                        "pricing_mode": "fixed_package",
                        "discount_percent": 20,
                        "requires_app": False,
                        "coupon_required": False,
                        "valid_from": valid_from,
                        "valid_until": valid_until,
                        "source_url": (
                            "https://scale.test/deal/"
                            f"{identity_index:04d}"
                        ),
                        "snapshot_id": snapshot_id,
                        "collected_at": collected_at,
                        "parser_version": "scale-test",
                        "raw_payload": {},
                    }
                )
                if len(batch) == 1_000:
                    connection.execute(insert(OfferCandidateRecord), batch)
                    batch.clear()
        if batch:
            connection.execute(insert(OfferCandidateRecord), batch)

        # PostgreSQL recommends refreshing planner statistics after a
        # substantial data change before interpreting EXPLAIN ANALYZE.
        connection.execute(text("ANALYZE offer_candidates"))


def _walk_plan(node: dict[str, object]):
    yield node
    for child in node.get("Plans", []) or []:
        yield from _walk_plan(child)


def _explain_payload(session: Session) -> dict[str, object]:
    query = _winner_metadata_query(_EFFECTIVE_DATE)
    compiled = query.compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    )
    raw = session.execute(
        text(
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "
            + str(compiled)
        )
    ).scalar_one()
    decoded = json.loads(raw) if isinstance(raw, str) else raw
    assert isinstance(decoded, list) and decoded
    payload = decoded[0]
    assert isinstance(payload, dict)
    return payload


def _server_timing_ms(response: Response) -> float:
    header = response.headers["server-timing"]
    prefix = "current-deals-sql;dur="
    assert header.startswith(prefix)
    return float(header[len(prefix) :])


def test_current_deals_sql_scales_without_temp_disk_spill() -> None:
    _seed_scale_history()

    with Session(engine) as session:
        plan_payload = _explain_payload(session)

    plan = plan_payload["Plan"]
    assert isinstance(plan, dict)
    nodes = list(_walk_plan(plan))
    execution_ms = float(plan_payload["Execution Time"])
    planning_ms = float(plan_payload.get("Planning Time", 0.0))
    actual_rows = int(float(plan.get("Actual Rows", 0)))
    temp_read_blocks = sum(
        int(float(node.get("Temp Read Blocks", 0) or 0)) for node in nodes
    )
    temp_written_blocks = sum(
        int(float(node.get("Temp Written Blocks", 0) or 0)) for node in nodes
    )
    disk_sorts = [
        node
        for node in nodes
        if str(node.get("Sort Space Type", "")).casefold() == "disk"
        or "external" in str(node.get("Sort Method", "")).casefold()
    ]
    node_types = ">".join(str(node.get("Node Type", "?")) for node in nodes)

    assert actual_rows == _IDENTITY_COUNT
    assert execution_ms < _SQL_BUDGET_MS
    assert temp_read_blocks == 0
    assert temp_written_blocks == 0
    assert not disk_sorts

    fast_route._clear_current_deals_cache()
    with Session(engine) as session:
        cold_response = Response()
        started = perf_counter()
        cold_payload = installed_fast_current_deals(
            response=cold_response,
            as_of=_EFFECTIVE_DATE,
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
        cold_wall_ms = (perf_counter() - started) * 1_000
        cold_server_ms = _server_timing_ms(cold_response)

        warm_response = Response()
        started = perf_counter()
        warm_payload = installed_fast_current_deals(
            response=warm_response,
            as_of=_EFFECTIVE_DATE,
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
        warm_wall_ms = (perf_counter() - started) * 1_000
        warm_server_ms = _server_timing_ms(warm_response)

    # Print evidence before semantic/budget assertions so a failure still
    # leaves enough timing and planner evidence to diagnose the next change.
    print(
        "CURRENT_DEALS_SCALE "
        f"history_rows={_HISTORY_ROW_COUNT} "
        f"winner_rows={actual_rows} "
        f"planning_ms={planning_ms:.2f} "
        f"explain_execution_ms={execution_ms:.2f} "
        f"cold_server_ms={cold_server_ms:.2f} "
        f"cold_wall_ms={cold_wall_ms:.2f} "
        f"warm_server_ms={warm_server_ms:.2f} "
        f"warm_wall_ms={warm_wall_ms:.2f} "
        f"temp_read_blocks={temp_read_blocks} "
        f"temp_written_blocks={temp_written_blocks} "
        f"plan_nodes={node_types}"
    )

    assert cold_payload.available_count == _EXPECTED_CURRENT
    assert cold_payload.availability_counts.model_dump() == {
        "current": _EXPECTED_CURRENT,
        "upcoming": _EXPECTED_UPCOMING,
        "unknown": 0,
        "expired": _EXPECTED_EXPIRED,
    }
    assert len(cold_payload.deals) == 12
    assert warm_payload == cold_payload
    assert cold_server_ms < _HANDLER_BUDGET_MS
    assert cold_wall_ms < _HANDLER_BUDGET_MS
    assert warm_server_ms < _WARM_HANDLER_BUDGET_MS
    assert warm_wall_ms < _WARM_HANDLER_BUDGET_MS
