"""PDF retention metadata only. No file I/O, network, deletion or implicit commit."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models import PdfAcquisition

RETENTION = timedelta(days=30)


def _sha(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("PDF SHA256 must be 64 lowercase hexadecimal characters")
    return value


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("acquisition, recording and evaluation times must include a timezone")
    return value.astimezone(timezone.utc)


def _stored_utc(value: datetime) -> datetime:
    # SQLite discards timezone information; all writes through this API use UTC.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else _utc(value)


def register_pdf_acquisition(
    db: Session, *, pdf_sha256: str, evidence_ref: str,
    acquired_at: datetime | None, recorded_at: datetime,
) -> bool:
    """Append one caller-verified observation; return False for an exact replay.

    evidence_ref identifies immutable acquisition evidence, not merely a URL or
    file mtime. None preserves an unresolved legacy age. No existing observation
    is updated, even when a later call supplies a date for that same reference.
    The caller owns commit/rollback and acquisition-evidence verification.
    """
    _sha(pdf_sha256)
    if (not isinstance(evidence_ref, str) or not evidence_ref.strip()
            or evidence_ref != evidence_ref.strip() or len(evidence_ref) > 255):
        raise ValueError("evidence_ref must contain 1 to 255 characters without outer whitespace")
    recorded_at = _utc(recorded_at)
    if acquired_at is not None:
        acquired_at = _utc(acquired_at)
        if acquired_at > recorded_at:
            raise ValueError("acquisition cannot follow recording")
        # Reject unrepresentable expiry rather than failing later in a reader.
        try:
            acquired_at + RETENTION
        except OverflowError as error:
            raise ValueError("acquisition expiry is outside the datetime range") from error

    dialect = db.get_bind().dialect.name
    if dialect not in {"postgresql", "sqlite"}:
        raise ValueError("PDF acquisition registry requires PostgreSQL or SQLite")
    insert = pg_insert if dialect == "postgresql" else sqlite_insert
    statement = insert(PdfAcquisition).values(
        pdf_sha256=pdf_sha256, evidence_ref=evidence_ref,
        acquired_at=acquired_at, recorded_at=recorded_at,
    ).on_conflict_do_nothing(index_elements=["pdf_sha256", "evidence_ref"]).returning(PdfAcquisition.pdf_sha256)
    inserted_sha = db.execute(statement).scalar_one_or_none()
    existing = db.execute(select(PdfAcquisition.acquired_at).where(
        PdfAcquisition.pdf_sha256 == pdf_sha256,
        PdfAcquisition.evidence_ref == evidence_ref,
    )).one()[0]
    existing = _stored_utc(existing) if existing is not None else None
    if existing != acquired_at:
        raise ValueError("immutable PDF acquisition conflicts with existing evidence")
    return inserted_sha is not None


@dataclass(frozen=True)
class PdfRetention:
    pdf_sha256: str
    state: str
    first_acquired_at: datetime | None = None
    expires_at: datetime | None = None


def pdf_retention(db: Session, pdf_sha256: str, *, as_of: datetime) -> PdfRetention:
    """Compute the earliest deadline; never claim bytes exist or were deleted.

    Any unknown-age observation prevents a later download from blessing a fresh
    30-day window. Earlier verified observations can shorten, never extend, a
    deadline. 'raw_expired' describes the deadline, not a deletion receipt.
    """
    _sha(pdf_sha256)
    as_of = _utc(as_of)
    count, dated, first = db.execute(select(
        func.count(), func.count(PdfAcquisition.acquired_at),
        func.min(PdfAcquisition.acquired_at),
    ).where(PdfAcquisition.pdf_sha256 == pdf_sha256)).one()
    if count == 0:
        return PdfRetention(pdf_sha256, "unregistered")
    if first is None:
        return PdfRetention(pdf_sha256, "acquisition_unknown")
    first = _stored_utc(first)
    expires = first + RETENTION
    if count != dated:
        # A dated observation can prove expiry even if an older age is unknown.
        # Before then, the unknown observation still prevents permission to serve.
        state = "raw_expired" if as_of >= expires else "acquisition_unknown"
        return PdfRetention(pdf_sha256, state, expires_at=expires)
    state = ("not_yet_acquired" if as_of < first else
             "raw_expired" if as_of >= expires else "within_retention")
    return PdfRetention(pdf_sha256, state, first, expires)
