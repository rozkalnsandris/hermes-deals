from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from statistics import median
from time import perf_counter
from uuid import UUID, uuid4

import pytest
from sqlalchemy import insert, inspect, select, text
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import Session, defer

from app.db import engine
from app.models import OfferCandidateRecord, SourceSnapshot


pytestmark = pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="materialization benchmark requires PostgreSQL",
)

_IDENTITY_COUNT = 750
_SNAPSHOT_COUNT = 8
_HISTORY_ROW_COUNT = _IDENTITY_COUNT * _SNAPSHOT_COUNT
_PAYLOAD_BYTES = 4_096
_ROUNDS = 9


def _seed_history() -> list[UUID]:
    collected_base = datetime(2026, 7, 29, 6, tzinfo=timezone.utc)
    snapshot_ids = [uuid4() for _ in range(_SNAPSHOT_COUNT)]
    latest_ids: list[UUID] = []
    payload_blob = "x" * _PAYLOAD_BYTES

    with engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE source_snapshots CASCADE"))
        connection.execute(
            insert(SourceSnapshot),
            [
                {
                    "id": snapshot_id,
                    "source_chain": "lidl",
                    "source_url": f"https://materialize.test/snapshot/{index}",
                    "collected_at": collected_base + timedelta(hours=index),
                    "content_bytes": 1,
                    "strategy_hint": "postgres_materialization_benchmark",
                    "success": True,
                }
                for index, snapshot_id in enumerate(snapshot_ids)
            ],
        )

        batch: list[dict[str, object]] = []
        for snapshot_index, snapshot_id in enumerate(snapshot_ids):
            collected_at = collected_base + timedelta(hours=snapshot_index)
            for identity_index in range(_IDENTITY_COUNT):
                row_id = uuid4()
                if snapshot_index == _SNAPSHOT_COUNT - 1:
                    latest_ids.append(row_id)
                batch.append(
                    {
                        "id": row_id,
                        "source_chain": ("lidl", "aldi_nord", "netto", "edeka")[
                            identity_index % 4
                        ],
                        "source_store_external_id": f"materialize-store-{identity_index % 8}",
                        "source_store_name": "Materialization Benchmark",
                        "source_offer_id": f"materialize-offer-{identity_index:04d}",
                        "product_name_raw": f"Materialization product {identity_index:04d}",
                        "brand_raw": "Benchmark Brand",
                        "description_raw": "Public searchable description",
                        "package_text_raw": "1 Packung",
                        "price_eur": Decimal("1.99"),
                        "regular_price_eur": Decimal("2.49"),
                        "pricing_mode": "fixed_package",
                        "discount_percent": 20,
                        "requires_app": False,
                        "coupon_required": False,
                        "valid_from": datetime(2026, 8, 6).date(),
                        "valid_until": datetime(2026, 8, 8).date(),
                        "source_url": f"https://materialize.test/deal/{identity_index:04d}",
                        "source_image_url": f"https://materialize.test/image/{identity_index:04d}.jpg",
                        "snapshot_id": snapshot_id,
                        "collected_at": collected_at,
                        "parser_version": "materialization-benchmark",
                        "raw_payload": {
                            "benchmark_blob": payload_blob,
                            "identity": identity_index,
                            "snapshot": snapshot_index,
                            "nested": {"source": "immutable-fixture"},
                        },
                    }
                )
                if len(batch) == 500:
                    connection.execute(insert(OfferCandidateRecord), batch)
                    batch.clear()
        if batch:
            connection.execute(insert(OfferCandidateRecord), batch)
        connection.execute(text("ANALYZE offer_candidates"))

    assert len(latest_ids) == _IDENTITY_COUNT
    return latest_ids


def _public_signature(row: OfferCandidateRecord) -> tuple[object, ...]:
    return (
        row.id,
        row.source_chain,
        row.source_store_external_id,
        row.source_store_name,
        row.source_offer_id,
        row.product_name_raw,
        row.brand_raw,
        row.description_raw,
        row.package_text_raw,
        row.price_eur,
        row.regular_price_eur,
        row.unit_price_eur,
        row.unit_label,
        row.pricing_mode,
        row.regular_unit_price_eur,
        row.example_weight_g,
        row.discount_percent,
        row.app_price_eur,
        row.requires_app,
        row.coupon_required,
        row.valid_from,
        row.valid_until,
        row.app_valid_from,
        row.app_valid_until,
        row.source_url,
        row.source_image_url,
        row.collected_at,
    )


def _load(
    session: Session,
    active_ids: list[UUID],
    *,
    defer_raw_payload: bool,
) -> tuple[list[OfferCandidateRecord], float]:
    session.expunge_all()
    statement = select(OfferCandidateRecord).where(
        OfferCandidateRecord.id.in_(active_ids)
    )
    if defer_raw_payload:
        statement = statement.options(
            defer(OfferCandidateRecord.raw_payload, raiseload=True)
        )
    started = perf_counter()
    rows = list(session.scalars(statement).all())
    elapsed_ms = (perf_counter() - started) * 1_000
    assert len(rows) == len(active_ids)
    return rows, elapsed_ms


def test_deferring_raw_payload_reduces_requested_view_materialization_cost() -> None:
    active_ids = _seed_history()

    samples = {"full": [], "deferred": []}
    with Session(engine) as session:
        # Warm both statement shapes before measuring.
        _load(session, active_ids, defer_raw_payload=False)
        _load(session, active_ids, defer_raw_payload=True)

        full_reference: dict[UUID, tuple[object, ...]] | None = None
        deferred_reference: dict[UUID, tuple[object, ...]] | None = None

        for round_index in range(_ROUNDS):
            order = (
                ("full", False),
                ("deferred", True),
            )
            if round_index % 2:
                order = tuple(reversed(order))

            for name, use_defer in order:
                rows, elapsed_ms = _load(
                    session,
                    active_ids,
                    defer_raw_payload=use_defer,
                )
                samples[name].append(elapsed_ms)
                signature = {row.id: _public_signature(row) for row in rows}
                if name == "full" and full_reference is None:
                    full_reference = signature
                if name == "deferred" and deferred_reference is None:
                    deferred_reference = signature

        assert full_reference is not None
        assert deferred_reference is not None
        assert deferred_reference == full_reference

        deferred_rows, _ = _load(
            session,
            active_ids[:1],
            defer_raw_payload=True,
        )
        deferred_row = deferred_rows[0]
        assert "raw_payload" in inspect(deferred_row).unloaded
        with pytest.raises(InvalidRequestError):
            _ = deferred_row.raw_payload

    full_median = median(samples["full"])
    deferred_median = median(samples["deferred"])
    ratio = deferred_median / full_median

    print(
        "MATERIALIZATION_BENCHMARK "
        f"history_rows={_HISTORY_ROW_COUNT} "
        f"active_rows={_IDENTITY_COUNT} "
        f"raw_payload_bytes={_PAYLOAD_BYTES} "
        f"rounds={_ROUNDS} "
        f"full_median_ms={full_median:.3f} "
        f"deferred_median_ms={deferred_median:.3f} "
        f"deferred_ratio={ratio:.3f}"
    )

    # This benchmark is intentionally conservative: only promote the runtime
    # change when omitting a column that the public path never consumes gives
    # a repeatable, material reduction in end-to-end ORM materialization.
    assert deferred_median < full_median
    assert ratio < 0.85
