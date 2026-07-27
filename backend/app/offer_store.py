from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models import OfferCandidateRecord, SourceSnapshot
from app.schemas import OfferCandidate


_OFFER_UNIQUE_CONSTRAINT = "uq_offer_candidates_snapshot_offer"
_OFFER_UNIQUE_COLUMNS = ["snapshot_id", "source_offer_id"]
_DECIMAL_FIELDS = {
    "price_eur",
    "regular_price_eur",
    "unit_price_eur",
    "app_price_eur",
}


def insert_offer_candidate_rows_do_nothing(
    db: Session,
    rows: list[dict[str, Any]],
) -> int:
    if not rows:
        return 0

    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        stmt = (
            postgresql_insert(OfferCandidateRecord)
            .values(rows)
            .on_conflict_do_nothing(constraint=_OFFER_UNIQUE_CONSTRAINT)
            .returning(OfferCandidateRecord.id)
        )
    elif dialect == "sqlite":
        stmt = (
            sqlite_insert(OfferCandidateRecord)
            .values(rows)
            .on_conflict_do_nothing(index_elements=_OFFER_UNIQUE_COLUMNS)
            .returning(OfferCandidateRecord.id)
        )
    else:
        raise RuntimeError(f"Unsupported DB dialect for offer persistence: {dialect}")

    result = db.execute(stmt)
    return len(result.scalars().all())


def _payload_from_offer(offer: OfferCandidate) -> dict[str, Any]:
    payload = offer.model_dump(mode="python")
    payload["source_chain"] = offer.source_chain.value
    payload["source_url"] = str(offer.source_url)
    payload["source_image_url"] = (
        str(offer.source_image_url) if offer.source_image_url else None
    )
    return payload


def _row_matches_payload(
    row: OfferCandidateRecord,
    payload: dict[str, Any],
) -> bool:
    for key, right in payload.items():
        left = getattr(row, key)
        if key in _DECIMAL_FIELDS:
            if left is None or right is None:
                if left is not right:
                    return False
            elif Decimal(str(left)) != Decimal(str(right)):
                return False
        elif key == "collected_at":
            left_iso = left.isoformat() if left is not None else None
            right_iso = right.isoformat() if right is not None else None
            if left_iso != right_iso:
                if (
                    left is None
                    or right is None
                    or left.replace(tzinfo=None) != right.replace(tzinfo=None)
                ):
                    return False
        elif left != right:
            return False
    return True


def _validate_exact_snapshot_rows(
    rows: list[OfferCandidateRecord],
    expected_by_id: dict[str, dict[str, Any]],
) -> None:
    existing_by_id = {str(row.source_offer_id): row for row in rows}
    if len(existing_by_id) != len(rows) or set(existing_by_id) != set(expected_by_id):
        raise ValueError(
            "Existing offer rows for the immutable snapshot do not exactly "
            "match the incoming source_offer_id set"
        )

    for source_offer_id, payload in expected_by_id.items():
        if not _row_matches_payload(existing_by_id[source_offer_id], payload):
            raise ValueError(
                "Existing offer row differs from incoming immutable snapshot "
                f"payload: {source_offer_id}"
            )


def save_offer_candidates(db: Session, offers: list[OfferCandidate]) -> int:
    if not offers:
        return 0

    snapshot_ids = {offer.snapshot_id for offer in offers}
    if len(snapshot_ids) != 1:
        raise ValueError("A save batch must belong to exactly one source snapshot")
    snapshot_id = next(iter(snapshot_ids))

    expected_by_id: dict[str, dict[str, Any]] = {}
    rows_to_insert: list[dict[str, Any]] = []

    for offer in offers:
        source_offer_id = offer.source_offer_id
        if (
            not isinstance(source_offer_id, str)
            or not source_offer_id.strip()
            or source_offer_id != source_offer_id.strip()
        ):
            raise ValueError(
                "Persisted offer candidates require a non-empty canonical source_offer_id"
            )
        if source_offer_id in expected_by_id:
            raise ValueError(
                f"Duplicate source_offer_id in persistence batch: {source_offer_id}"
            )

        payload = _payload_from_offer(offer)
        expected_by_id[source_offer_id] = payload
        rows_to_insert.append({"id": uuid4(), **payload})

    try:
        existing = list(
            db.scalars(
                select(OfferCandidateRecord)
                .where(OfferCandidateRecord.snapshot_id == snapshot_id)
                .order_by(OfferCandidateRecord.source_offer_id.asc())
            ).all()
        )
        if existing:
            _validate_exact_snapshot_rows(existing, expected_by_id)
            return 0

        rows_written = insert_offer_candidate_rows_do_nothing(db, rows_to_insert)

        persisted = list(
            db.scalars(
                select(OfferCandidateRecord)
                .where(OfferCandidateRecord.snapshot_id == snapshot_id)
                .order_by(OfferCandidateRecord.source_offer_id.asc())
            ).all()
        )
        _validate_exact_snapshot_rows(persisted, expected_by_id)

        db.commit()
        return rows_written
    except Exception:
        db.rollback()
        raise


def latest_successful_snapshot(
    db: Session,
    source_chain: str,
) -> SourceSnapshot | None:
    return db.scalar(
        select(SourceSnapshot)
        .where(
            SourceSnapshot.source_chain == source_chain,
            SourceSnapshot.success.is_(True),
        )
        .order_by(SourceSnapshot.collected_at.desc())
        .limit(1)
    )
