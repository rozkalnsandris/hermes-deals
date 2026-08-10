from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
from typing import Any, Sequence
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.aldi_nord_daily_special import (
    AldiNordDailySpecialError,
    cached_aldi_nord_daily_specials,
)
from app.models import SourceSnapshot
from app.netto_daily_special_api import (
    _cached_snapshot_offers,
    _snapshot_manifest_window,
    _verify_file,
)


_TIMEZONE = "Europe/Berlin"
_STATE_VALUES = {
    "offers",
    "no_offers",
    "not_published_yet",
    "source_unavailable",
    "stale_data",
    "not_supported",
}
_RETAILERS = (
    ("netto", "Netto", "netto"),
    ("aldi_nord", "ALDI Nord", "aldi_nord"),
    ("lidl", "Lidl", "lidl"),
    ("edeka", "EDEKA", "edeka"),
)


@dataclass(frozen=True)
class RetailerEvidence:
    state: str
    reason: str
    last_verified_at: datetime | None = None
    last_verified_campaign: str | None = None
    last_verified_evidence_sha256: str | None = None
    last_verified_valid_from: date | None = None
    last_verified_valid_until: date | None = None

    def __post_init__(self) -> None:
        if self.state not in _STATE_VALUES:
            raise ValueError(f"unsupported retailer state: {self.state}")


def _snapshot_query(db: Session, source_chain: str, scope: str) -> list[SourceSnapshot]:
    return list(
        db.scalars(
            select(SourceSnapshot)
            .where(
                SourceSnapshot.source_chain == source_chain,
                SourceSnapshot.scope == scope,
                SourceSnapshot.success.is_(True),
            )
            .order_by(SourceSnapshot.collected_at.desc())
        ).all()
    )


def _netto_campaign(snapshot: SourceSnapshot) -> str | None:
    try:
        manifest_path = _verify_file(
            snapshot.snapshot_path,
            snapshot.sha256,
            "Netto manifest",
        )
        if manifest_path is None:
            return None
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (HTTPException, OSError, UnicodeError, json.JSONDecodeError, RuntimeError):
        return None
    if not isinstance(payload, dict):
        return None
    for key in ("campaign_key", "prospect_slug", "publication_slug"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _netto_evidence(
    db: Session,
    week_start: date,
    week_end: date,
    today: date,
) -> RetailerEvidence:
    snapshots = _snapshot_query(db, "netto", "family_primary_netto")
    if not snapshots:
        return RetailerEvidence(
            state="not_published_yet" if week_start > today else "source_unavailable",
            reason="netto_no_successful_snapshot",
        )

    verified: list[tuple[SourceSnapshot, date, date]] = []
    unreadable = False
    for snapshot in snapshots:
        try:
            valid_from, valid_until = _snapshot_manifest_window(snapshot)
        except HTTPException:
            unreadable = True
            continue
        verified.append((snapshot, valid_from, valid_until))

    if not verified:
        return RetailerEvidence(
            state="not_published_yet" if week_start > today and not unreadable else "source_unavailable",
            reason="netto_snapshot_manifest_unavailable",
            last_verified_at=snapshots[0].collected_at,
            last_verified_evidence_sha256=snapshots[0].sha256,
        )

    relevant = [row for row in verified if row[1] <= week_end and row[2] >= week_start]
    if relevant:
        snapshot, valid_from, valid_until = max(relevant, key=lambda row: row[0].collected_at)
        try:
            offers = _cached_snapshot_offers(
                str(snapshot.id),
                snapshot.snapshot_path or "",
                snapshot.sha256 or "",
                snapshot.source_url,
                snapshot.final_url or snapshot.source_url,
                snapshot.collected_at.isoformat(),
            )
        except Exception:
            return RetailerEvidence(
                state="source_unavailable",
                reason="netto_relevant_snapshot_parse_unavailable",
                last_verified_at=snapshot.collected_at,
                last_verified_campaign=_netto_campaign(snapshot),
                last_verified_evidence_sha256=snapshot.sha256,
                last_verified_valid_from=valid_from,
                last_verified_valid_until=valid_until,
            )
        relevant_offer_count = sum(
            1
            for offer in offers
            if offer.valid_from is not None
            and offer.valid_until is not None
            and offer.valid_from <= week_end
            and offer.valid_until >= week_start
            and offer.raw_payload.get("is_daily_special") is True
            and offer.raw_payload.get("special_confidence") == "high"
        )
        if relevant_offer_count:
            return RetailerEvidence(
                state="source_unavailable",
                reason="netto_verified_offers_missing_from_merged_weekly_days",
                last_verified_at=snapshot.collected_at,
                last_verified_campaign=_netto_campaign(snapshot),
                last_verified_evidence_sha256=snapshot.sha256,
                last_verified_valid_from=valid_from,
                last_verified_valid_until=valid_until,
            )
        return RetailerEvidence(
            state="no_offers",
            reason="netto_relevant_snapshot_verified_empty",
            last_verified_at=snapshot.collected_at,
            last_verified_campaign=_netto_campaign(snapshot),
            last_verified_evidence_sha256=snapshot.sha256,
            last_verified_valid_from=valid_from,
            last_verified_valid_until=valid_until,
        )

    snapshot, valid_from, valid_until = max(verified, key=lambda row: row[2])
    if week_start > today:
        state = "not_published_yet"
        reason = "netto_requested_week_not_yet_in_verified_evidence"
    elif valid_until < week_start:
        state = "stale_data"
        reason = "netto_latest_verified_window_precedes_requested_week"
    else:
        state = "source_unavailable"
        reason = "netto_requested_week_not_covered_by_verified_evidence"
    return RetailerEvidence(
        state=state,
        reason=reason,
        last_verified_at=snapshot.collected_at,
        last_verified_campaign=_netto_campaign(snapshot),
        last_verified_evidence_sha256=snapshot.sha256,
        last_verified_valid_from=valid_from,
        last_verified_valid_until=valid_until,
    )


def _aldi_evidence(
    db: Session,
    week_start: date,
    week_end: date,
    today: date,
) -> RetailerEvidence:
    snapshots = _snapshot_query(db, "aldi_nord", "national_offers")
    if not snapshots:
        return RetailerEvidence(
            state="not_published_yet" if week_start > today else "source_unavailable",
            reason="aldi_no_successful_snapshot",
        )

    latest = snapshots[0]
    try:
        offers = cached_aldi_nord_daily_specials(
            str(latest.id),
            latest.snapshot_path or "",
            latest.sha256 or "",
            latest.source_url,
            latest.final_url or latest.source_url,
            latest.collected_at.isoformat(),
        )
    except (AldiNordDailySpecialError, OSError, ValueError):
        return RetailerEvidence(
            state="source_unavailable",
            reason="aldi_latest_snapshot_parse_unavailable",
            last_verified_at=latest.collected_at,
            last_verified_evidence_sha256=latest.sha256,
        )

    relevant_offers = [
        offer
        for offer in offers
        if offer.valid_from is not None
        and offer.valid_until is not None
        and offer.valid_from <= week_end
        and offer.valid_until >= week_start
        and offer.raw_payload.get("is_daily_special") is True
        and offer.raw_payload.get("special_confidence") == "high"
    ]
    dates = sorted(
        {
            offer.valid_from
            for offer in offers
            if offer.valid_from is not None and offer.valid_until is not None
        }
    )
    valid_from = dates[0] if dates else None
    valid_until = dates[-1] if dates else None
    if relevant_offers:
        state, reason = "source_unavailable", "aldi_verified_offers_missing_from_merged_weekly_days"
    elif week_start > today:
        state, reason = "not_published_yet", "aldi_requested_week_not_yet_in_verified_evidence"
    elif valid_until is not None and valid_until < week_start:
        state, reason = "stale_data", "aldi_latest_verified_daily_window_precedes_requested_week"
    elif not dates and week_start <= latest.collected_at.date() <= week_end + timedelta(days=1):
        state, reason = "no_offers", "aldi_snapshot_verified_without_explicit_daily_categories"
    else:
        state, reason = "source_unavailable", "aldi_requested_week_not_covered_by_verified_evidence"
    return RetailerEvidence(
        state=state,
        reason=reason,
        last_verified_at=latest.collected_at,
        last_verified_evidence_sha256=latest.sha256,
        last_verified_valid_from=valid_from,
        last_verified_valid_until=valid_until,
    )


def _deal_summary(days: Sequence[Any], source_chain: str) -> tuple[int, list[date], datetime | None, date | None, date | None, str | None]:
    active_dates: list[date] = []
    collected: list[datetime] = []
    valid_froms: list[date] = []
    valid_untils: list[date] = []
    evidence: list[str] = []
    count = 0
    for day in days:
        matched = [deal for deal in day.deals if deal.source_chain == source_chain]
        if not matched:
            continue
        active_dates.append(day.date)
        count += len(matched)
        for deal in matched:
            collected.append(deal.collected_at)
            if deal.valid_from is not None:
                valid_froms.append(deal.valid_from)
            if deal.valid_until is not None:
                valid_untils.append(deal.valid_until)
            if getattr(deal, "source_snapshot_sha256", None):
                evidence.append(deal.source_snapshot_sha256)
    return (
        count,
        active_dates,
        max(collected) if collected else None,
        min(valid_froms) if valid_froms else None,
        max(valid_untils) if valid_untils else None,
        sorted(set(evidence))[-1] if evidence else None,
    )


def build_weekly_retailer_states(
    db: Session,
    days: Sequence[Any],
    week_start: date,
    week_end: date,
    *,
    today: date | None = None,
) -> list[dict[str, Any]]:
    effective_today = today or datetime.now(ZoneInfo(_TIMEZONE)).date()
    result: list[dict[str, Any]] = []
    for retailer_key, display_name, source_chain in _RETAILERS:
        count, active_dates, collected_at, valid_from, valid_until, evidence_sha = _deal_summary(days, source_chain)
        if count:
            evidence = RetailerEvidence(
                state="offers",
                reason="offers_present_in_merged_weekly_days",
                last_verified_at=collected_at,
                last_verified_evidence_sha256=evidence_sha,
                last_verified_valid_from=valid_from,
                last_verified_valid_until=valid_until,
            )
        elif retailer_key == "netto":
            evidence = _netto_evidence(db, week_start, week_end, effective_today)
        elif retailer_key == "aldi_nord":
            evidence = _aldi_evidence(db, week_start, week_end, effective_today)
        else:
            evidence = RetailerEvidence(
                state="not_supported",
                reason=f"{retailer_key}_dedicated_special_period_evidence_not_verified",
            )
        result.append(
            {
                "retailer_key": retailer_key,
                "display_name": display_name,
                "source_chain": source_chain,
                "state": evidence.state,
                "reason": evidence.reason,
                "deal_count": count,
                "active_dates": active_dates,
                "last_verified_at": evidence.last_verified_at,
                "last_verified_campaign": evidence.last_verified_campaign,
                "last_verified_evidence_sha256": evidence.last_verified_evidence_sha256,
                "last_verified_valid_from": evidence.last_verified_valid_from,
                "last_verified_valid_until": evidence.last_verified_valid_until,
            }
        )
    return result
