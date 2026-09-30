"""Read HTML observations without fetching, repairing or writing evidence."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import OfferCandidateRecord, SourceSnapshot
from app.netto_html_collector import STRATEGY, replay, validate_source
from app.offer_store import _payload_from_offer, _validate_exact_snapshot_rows
from app.source_config import SourceConfig


def verified_html_rows(db: Session, snapshot: SourceSnapshot) -> list[OfferCandidateRecord]:
    if (not snapshot.success or snapshot.source_chain != "netto"
            or snapshot.strategy_hint != STRATEGY or snapshot.scope != "family_primary_netto"):
        raise ValueError("Netto HTML snapshot strategy/scope mismatch")
    source = SourceConfig(
        chain="netto", enabled=True, priority=1, url=snapshot.source_url,
        scope="family_primary_netto", notes="", keywords=(),
        store_external_id="5659",
        store_name="Netto Marken-Discount — Dortmund, Rauschenbuschstr. 1",
    )
    validate_source(source)
    offers, _ = replay(snapshot, source)
    rows = list(db.scalars(select(OfferCandidateRecord).where(
        OfferCandidateRecord.snapshot_id == snapshot.id,
    )).all())
    _validate_exact_snapshot_rows(rows, {
        str(offer.source_offer_id): _payload_from_offer(offer) for offer in offers
    })
    return rows
