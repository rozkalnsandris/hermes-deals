from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from statistics import median
from uuid import uuid4

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.current_deals_sql_loader import (
    _rescue_expression,
    _state_expression,
    _winner_metadata_query,
)
from app.db import engine
from app.models import OfferCandidateRecord, SourceSnapshot


pytestmark = pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="winner benchmark requires PostgreSQL DISTINCT ON",
)

_EFFECTIVE_DATE = date(2026, 8, 6)
_IDENTITY_COUNT = 1_500
_SNAPSHOT_COUNT = 8
_HISTORY_ROWS = _IDENTITY_COUNT * _SNAPSHOT_COUNT


def _window(identity_index: int) -> tuple[date, date]:
    state = identity_index % 4
    if state == 0:
        return _EFFECTIVE_DATE, date(2026, 8, 8)
    if state == 1:
        return date(2026, 8, 9), date(2026, 8, 10)
    return date(2026, 7, 1), date(2026, 7, 2)


def _seed_history() -> None:
    collected_base = datetime(2026, 7, 29, 6, tzinfo=timezone.utc)
    snapshot_ids = [uuid4() for _ in range(_SNAPSHOT_COUNT)]
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE source_snapshots CASCADE"))
        connection.execute(
            insert(SourceSnapshot),
            [
                {
                    "id": snapshot_id,
                    "source_chain": "lidl",
                    "source_url": f"https://winner-bench.test/snapshot/{index}",
                    "collected_at": collected_base + timedelta(hours=index),
                    "content_bytes": 1,
                    "strategy_hint": "postgres_winner_benchmark",
                    "success": True,
                }
                for index, snapshot_id in enumerate(snapshot_ids)
            ],
        )

        batch: list[dict[str, object]] = []
        for snapshot_index, snapshot_id in enumerate(snapshot_ids):
            collected_at = collected_base + timedelta(hours=snapshot_index)
            for identity_index in range(_IDENTITY_COUNT):
                valid_from, valid_until = _window(identity_index)
                batch.append(
                    {
                        "id": uuid4(),
                        "source_chain": ("lidl", "aldi_nord", "netto", "edeka")[
                            identity_index % 4
                        ],
                        "source_store_external_id": f"bench-store-{identity_index % 8}",
                        "source_store_name": "Winner Benchmark",
                        "source_offer_id": f"bench-offer-{identity_index:04d}",
                        "product_name_raw": f"Benchmark product {identity_index:04d}",
                        "brand_raw": "Benchmark Brand",
                        "package_text_raw": "1 Packung",
                        "price_eur": Decimal("1.99"),
                        "regular_price_eur": Decimal("2.49"),
                        "pricing_mode": "fixed_package",
                        "discount_percent": 20,
                        "requires_app": False,
                        "coupon_required": False,
                        "valid_from": valid_from,
                        "valid_until": valid_until,
                        "source_url": f"https://winner-bench.test/deal/{identity_index:04d}",
                        "snapshot_id": snapshot_id,
                        "collected_at": collected_at,
                        "parser_version": "winner-benchmark",
                        "raw_payload": {},
                    }
                )
                if len(batch) == 1_000:
                    connection.execute(insert(OfferCandidateRecord), batch)
                    batch.clear()
        if batch:
            connection.execute(insert(OfferCandidateRecord), batch)
        connection.execute(text("ANALYZE offer_candidates"))


def _metadata_select(winners):
    return select(
        winners.c.state.label("state"),
        OfferCandidateRecord.id.label("id"),
        OfferCandidateRecord.source_chain.label("source_chain"),
        OfferCandidateRecord.source_store_external_id.label("source_store_external_id"),
        OfferCandidateRecord.source_offer_id.label("source_offer_id"),
        OfferCandidateRecord.collected_at.label("collected_at"),
        OfferCandidateRecord.product_name_raw.label("product_name_raw"),
        OfferCandidateRecord.price_eur.label("price_eur"),
        OfferCandidateRecord.valid_from.label("valid_from"),
        OfferCandidateRecord.valid_until.label("valid_until"),
        OfferCandidateRecord.source_url.label("source_url"),
        _rescue_expression().label("is_completeness_rescue"),
    ).join(OfferCandidateRecord, OfferCandidateRecord.id == winners.c.id)


def _distinct_narrow_query():
    classified = select(
        OfferCandidateRecord.id.label("id"),
        OfferCandidateRecord.source_chain.label("source_chain"),
        OfferCandidateRecord.source_store_external_id.label("source_store_external_id"),
        OfferCandidateRecord.source_offer_id.label("source_offer_id"),
        OfferCandidateRecord.collected_at.label("collected_at"),
        _state_expression(_EFFECTIVE_DATE).label("state"),
    ).where(OfferCandidateRecord.source_offer_id.is_not(None)).cte("bench_classified_narrow")

    winners = (
        select(classified.c.id, classified.c.state)
        .distinct(
            classified.c.state,
            classified.c.source_chain,
            classified.c.source_store_external_id,
            classified.c.source_offer_id,
        )
        .order_by(
            classified.c.state,
            classified.c.source_chain,
            classified.c.source_store_external_id,
            classified.c.source_offer_id,
            classified.c.collected_at.desc(),
            classified.c.id.desc(),
        )
        .cte("bench_distinct_winner_ids")
    )
    return _metadata_select(winners)


def _distinct_wide_query():
    classified = select(
        OfferCandidateRecord.id.label("id"),
        OfferCandidateRecord.source_chain.label("source_chain"),
        OfferCandidateRecord.source_store_external_id.label("source_store_external_id"),
        OfferCandidateRecord.source_offer_id.label("source_offer_id"),
        OfferCandidateRecord.collected_at.label("collected_at"),
        _state_expression(_EFFECTIVE_DATE).label("state"),
        OfferCandidateRecord.product_name_raw.label("product_name_raw"),
        OfferCandidateRecord.price_eur.label("price_eur"),
        OfferCandidateRecord.valid_from.label("valid_from"),
        OfferCandidateRecord.valid_until.label("valid_until"),
        OfferCandidateRecord.source_url.label("source_url"),
        _rescue_expression().label("is_completeness_rescue"),
    ).where(OfferCandidateRecord.source_offer_id.is_not(None)).cte("bench_classified_wide")

    return (
        select(classified)
        .distinct(
            classified.c.state,
            classified.c.source_chain,
            classified.c.source_store_external_id,
            classified.c.source_offer_id,
        )
        .order_by(
            classified.c.state,
            classified.c.source_chain,
            classified.c.source_store_external_id,
            classified.c.source_offer_id,
            classified.c.collected_at.desc(),
            classified.c.id.desc(),
        )
    )


def _decode_explain(session: Session, query) -> dict[str, object]:
    compiled = query.compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    )
    raw = session.execute(
        text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + str(compiled))
    ).scalar_one()
    payload = json.loads(raw) if isinstance(raw, str) else raw
    return payload[0]


def _walk(node: dict[str, object]):
    yield node
    for child in node.get("Plans", []) or []:
        yield from _walk(child)


def _signature(rows) -> dict[tuple[object, ...], tuple[object, ...]]:
    return {
        (
            str(row.state),
            str(row.source_chain),
            row.source_store_external_id,
            str(row.source_offer_id),
        ): (
            row.id,
            row.collected_at,
            str(row.product_name_raw),
            row.price_eur,
            row.valid_from,
            row.valid_until,
            str(row.source_url),
            bool(row.is_completeness_rescue),
        )
        for row in rows
    }


def test_postgresql_winner_query_alternatives_have_identical_semantics() -> None:
    _seed_history()
    queries = {
        "window": _winner_metadata_query(_EFFECTIVE_DATE),
        "distinct_narrow": _distinct_narrow_query(),
        "distinct_wide": _distinct_wide_query(),
    }

    with Session(engine) as session:
        results = {name: session.execute(query).all() for name, query in queries.items()}
        baseline_signature = _signature(results["window"])
        assert len(baseline_signature) == _IDENTITY_COUNT
        assert _signature(results["distinct_narrow"]) == baseline_signature
        assert _signature(results["distinct_wide"]) == baseline_signature

        # Warm each plan once, then rotate order across repeated measurements.
        for query in queries.values():
            _decode_explain(session, query)

        samples = {name: [] for name in queries}
        names = list(queries)
        last_payloads: dict[str, dict[str, object]] = {}
        for round_index in range(7):
            order = names[round_index % len(names):] + names[: round_index % len(names)]
            for name in order:
                payload = _decode_explain(session, queries[name])
                samples[name].append(float(payload["Execution Time"]))
                last_payloads[name] = payload

    medians = {name: median(values) for name, values in samples.items()}
    node_paths = {}
    for name, payload in last_payloads.items():
        nodes = list(_walk(payload["Plan"]))
        node_paths[name] = ">".join(str(node.get("Node Type", "?")) for node in nodes)
        assert sum(int(node.get("Temp Read Blocks", 0) or 0) for node in nodes) == 0
        assert sum(int(node.get("Temp Written Blocks", 0) or 0) for node in nodes) == 0

    print(
        "WINNER_QUERY_BENCHMARK "
        f"history_rows={_HISTORY_ROWS} winner_rows={_IDENTITY_COUNT} "
        f"window_median_ms={medians['window']:.3f} "
        f"distinct_narrow_median_ms={medians['distinct_narrow']:.3f} "
        f"distinct_wide_median_ms={medians['distinct_wide']:.3f} "
        f"narrow_ratio={medians['distinct_narrow']/medians['window']:.3f} "
        f"wide_ratio={medians['distinct_wide']/medians['window']:.3f}"
    )
    for name in names:
        print(f"WINNER_QUERY_PLAN name={name} nodes={node_paths[name]}")
