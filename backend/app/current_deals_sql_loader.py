from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from time import perf_counter
from typing import Any, Iterator
from uuid import UUID

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session, defer

from app.models import OfferCandidateRecord


_ACTIVE_STATES = frozenset({"current", "upcoming"})
_MATERIALIZE_STATE: ContextVar[str | None] = ContextVar(
    "hermes_current_deals_materialize_state",
    default=None,
)
_RANK_SUBSTAGE_TIMINGS: ContextVar[dict[str, float] | None] = ContextVar(
    "hermes_current_deals_rank_substage_timings",
    default=None,
)


@dataclass(frozen=True)
class _WinnerMeta:
    id: UUID
    state: str
    source_chain: str
    source_store_external_id: str | None
    source_offer_id: str
    collected_at: datetime
    product_name_raw: str
    price_eur: Decimal
    valid_from: date | None
    valid_until: date | None
    source_url: str
    is_completeness_rescue: bool


@dataclass(frozen=True)
class _InactiveWinner:
    """Count-only row for a winner not needed by the requested view."""

    source_chain: str


@contextmanager
def materialize_only(state: str) -> Iterator[None]:
    """Materialize ORM rows only for one public availability view."""

    if state not in _ACTIVE_STATES:
        raise ValueError(f"unsupported materialization state: {state}")
    token = _MATERIALIZE_STATE.set(state)
    try:
        yield
    finally:
        _MATERIALIZE_STATE.reset(token)


@contextmanager
def capture_rank_substage_timings() -> Iterator[dict[str, float]]:
    """Capture request-local timing for the SQL rank loader internals."""

    timings: dict[str, float] = {}
    token = _RANK_SUBSTAGE_TIMINGS.set(timings)
    try:
        yield timings
    finally:
        _RANK_SUBSTAGE_TIMINGS.reset(token)


def _record_rank_substage(name: str, started: float) -> None:
    timings = _RANK_SUBSTAGE_TIMINGS.get()
    if timings is not None:
        timings[name] = (perf_counter() - started) * 1000


def _state_expression(effective_date: date):
    base_complete = and_(
        OfferCandidateRecord.valid_from.is_not(None),
        OfferCandidateRecord.valid_until.is_not(None),
    )
    app_complete = and_(
        OfferCandidateRecord.app_price_eur.is_not(None),
        OfferCandidateRecord.app_valid_from.is_not(None),
        OfferCandidateRecord.app_valid_until.is_not(None),
    )

    current = or_(
        and_(
            base_complete,
            OfferCandidateRecord.valid_from <= effective_date,
            OfferCandidateRecord.valid_until >= effective_date,
        ),
        and_(
            app_complete,
            OfferCandidateRecord.app_valid_from <= effective_date,
            OfferCandidateRecord.app_valid_until >= effective_date,
        ),
    )
    upcoming = or_(
        and_(
            base_complete,
            OfferCandidateRecord.valid_from > effective_date,
        ),
        and_(
            app_complete,
            OfferCandidateRecord.app_valid_from > effective_date,
        ),
    )
    has_window = or_(base_complete, app_complete)
    expired = and_(
        has_window,
        or_(
            ~base_complete,
            OfferCandidateRecord.valid_until < effective_date,
        ),
        or_(
            ~app_complete,
            OfferCandidateRecord.app_valid_until < effective_date,
        ),
    )

    return case(
        (current, "current"),
        (upcoming, "upcoming"),
        (expired, "expired"),
        else_="unknown",
    )


def _rescue_expression():
    raw = OfferCandidateRecord.raw_payload
    price_basis = raw["price_basis"].as_string()
    candidate_key = raw["review_original_payload"]["completeness_rescue"][
        "candidate_key"
    ].as_string()
    return and_(
        price_basis == "completeness_rescue_review",
        candidate_key.is_not(None),
        candidate_key != "",
    )


def _normalized_name(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def _signature(meta: _WinnerMeta) -> tuple[object, ...]:
    return (
        meta.state,
        meta.source_chain,
        meta.source_store_external_id,
        _normalized_name(meta.product_name_raw),
        meta.price_eur,
        meta.valid_from,
        meta.valid_until,
        meta.source_url,
    )


def _newness(meta: _WinnerMeta) -> tuple[datetime, str]:
    return (meta.collected_at, str(meta.id))


def _suppress_physical_rescue_duplicates(
    winners: list[_WinnerMeta],
) -> list[_WinnerMeta]:
    """Mirror completeness-rescue policy using winner-only metadata."""

    groups: dict[tuple[object, ...], list[int]] = {}
    for index, winner in enumerate(winners):
        groups.setdefault(_signature(winner), []).append(index)

    suppressed: set[int] = set()
    for indexes in groups.values():
        rescue_indexes = [
            index
            for index in indexes
            if winners[index].is_completeness_rescue
        ]
        non_rescue_indexes = [
            index
            for index in indexes
            if not winners[index].is_completeness_rescue
        ]
        if not rescue_indexes or not non_rescue_indexes:
            continue

        rescue_winner = max(
            rescue_indexes,
            key=lambda index: _newness(winners[index]),
        )
        suppressed.update(
            index for index in indexes if index != rescue_winner
        )

    return [
        winner
        for index, winner in enumerate(winners)
        if index not in suppressed
    ]


def _winner_metadata_query(effective_date: date):
    # Keep the window-function input narrow. Product text, source URLs and the
    # JSON rescue marker are joined only after one winner per stable identity
    # and availability state has been selected.
    classified = select(
        OfferCandidateRecord.id.label("id"),
        OfferCandidateRecord.source_chain.label("source_chain"),
        OfferCandidateRecord.source_store_external_id.label(
            "source_store_external_id"
        ),
        OfferCandidateRecord.source_offer_id.label("source_offer_id"),
        OfferCandidateRecord.collected_at.label("collected_at"),
        _state_expression(effective_date).label("state"),
    ).where(OfferCandidateRecord.source_offer_id.is_not(None)).cte(
        "classified_current_deals"
    )

    ranked = select(
        classified,
        func.row_number()
        .over(
            partition_by=(
                classified.c.state,
                classified.c.source_chain,
                classified.c.source_store_external_id,
                classified.c.source_offer_id,
            ),
            order_by=(
                classified.c.collected_at.desc(),
                classified.c.id.desc(),
            ),
        )
        .label("winner_rank"),
    ).cte("ranked_current_deals")

    winners = select(
        ranked.c.id,
        ranked.c.state,
    ).where(ranked.c.winner_rank == 1).cte("current_deal_winner_ids")

    return (
        select(
            winners.c.state.label("state"),
            OfferCandidateRecord.id.label("id"),
            OfferCandidateRecord.source_chain.label("source_chain"),
            OfferCandidateRecord.source_store_external_id.label(
                "source_store_external_id"
            ),
            OfferCandidateRecord.source_offer_id.label("source_offer_id"),
            OfferCandidateRecord.collected_at.label("collected_at"),
            OfferCandidateRecord.product_name_raw.label("product_name_raw"),
            OfferCandidateRecord.price_eur.label("price_eur"),
            OfferCandidateRecord.valid_from.label("valid_from"),
            OfferCandidateRecord.valid_until.label("valid_until"),
            OfferCandidateRecord.source_url.label("source_url"),
            _rescue_expression().label("is_completeness_rescue"),
        )
        .join(
            OfferCandidateRecord,
            OfferCandidateRecord.id == winners.c.id,
        )
    )


def load_sql_ranked_state_rows(
    db: Session,
    effective_date: date,
) -> list[tuple[str, Any]]:
    """Return SQL-ranked winners with requested-view ORM materialization.

    Ranking runs over identity/date columns. Winner-only metadata is then used
    for the narrow completeness-rescue policy. In production, the route sets a
    context-local requested state, so full public-path ORM columns are loaded
    only for the current *or* upcoming view being rendered. ``raw_payload`` is
    intentionally deferred with raiseload because rescue classification is
    already captured in winner metadata and the public route does not consume
    the raw source document.
    """

    winner_started = perf_counter()
    result = db.execute(_winner_metadata_query(effective_date)).all()
    winners = [
        _WinnerMeta(
            id=row.id,
            state=str(row.state),
            source_chain=str(row.source_chain),
            source_store_external_id=row.source_store_external_id,
            source_offer_id=str(row.source_offer_id),
            collected_at=row.collected_at,
            product_name_raw=str(row.product_name_raw),
            price_eur=row.price_eur,
            valid_from=row.valid_from,
            valid_until=row.valid_until,
            source_url=str(row.source_url),
            is_completeness_rescue=bool(row.is_completeness_rescue),
        )
        for row in result
    ]
    _record_rank_substage("winner", winner_started)

    rescue_started = perf_counter()
    visible = _suppress_physical_rescue_duplicates(winners)
    _record_rank_substage("rescue", rescue_started)

    materialize_started = perf_counter()
    requested_state = _MATERIALIZE_STATE.get()
    materialized_states = (
        frozenset({requested_state})
        if requested_state in _ACTIVE_STATES
        else _ACTIVE_STATES
    )
    active_ids = [
        winner.id
        for winner in visible
        if winner.state in materialized_states
    ]
    active_by_id: dict[UUID, OfferCandidateRecord] = {}
    if active_ids:
        active_rows = db.scalars(
            select(OfferCandidateRecord)
            .options(
                defer(OfferCandidateRecord.raw_payload, raiseload=True)
            )
            .where(OfferCandidateRecord.id.in_(active_ids))
        ).all()
        active_by_id = {row.id: row for row in active_rows}

    state_rows: list[tuple[str, Any]] = []
    for winner in visible:
        row = active_by_id.get(winner.id)
        if row is not None:
            state_rows.append((winner.state, row))
        else:
            state_rows.append(
                (
                    winner.state,
                    _InactiveWinner(source_chain=winner.source_chain),
                )
            )
    _record_rank_substage("materialize", materialize_started)
    return state_rows
