from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.models import OfferCandidateRecord


_ACTIVE_STATES = frozenset({"current", "upcoming"})


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
    """Count-only row for expired/unknown winners.

    The public handler only materializes rows for the current/upcoming views.
    Expired and unknown winners are still returned to the existing counting
    loop, but their large ORM payloads never leave PostgreSQL.
    """

    source_chain: str


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
    """Mirror completeness-rescue read policy without loading raw JSON.

    PostgreSQL/SQLite evaluates the exact rescue marker and returns only a
    boolean. Python then applies the same physical-deal signature and newness
    rules as ``dedupe_completeness_rescue_publications``.
    """

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
    classified = select(
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
        _state_expression(effective_date).label("state"),
        _rescue_expression().label("is_completeness_rescue"),
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

    return select(ranked).where(ranked.c.winner_rank == 1)


def load_sql_ranked_state_rows(
    db: Session,
    effective_date: date,
) -> list[tuple[str, Any]]:
    """Return stable state winners with active-only ORM materialization.

    The expensive identity ranking is executed by the database over narrow
    columns. Full ``OfferCandidateRecord`` objects (including ``raw_payload``)
    are fetched only for current/upcoming winners. Expired/unknown winners are
    represented by count-only rows because the public endpoint cannot request
    those states as a view.
    """

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
    visible = _suppress_physical_rescue_duplicates(winners)

    active_ids = [
        winner.id for winner in visible if winner.state in _ACTIVE_STATES
    ]
    active_by_id: dict[UUID, OfferCandidateRecord] = {}
    if active_ids:
        active_rows = db.scalars(
            select(OfferCandidateRecord).where(
                OfferCandidateRecord.id.in_(active_ids)
            )
        ).all()
        active_by_id = {row.id: row for row in active_rows}

    state_rows: list[tuple[str, Any]] = []
    for winner in visible:
        if winner.state in _ACTIVE_STATES:
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
    return state_rows
