from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import OfferCandidateRecord, SourceSnapshot


_TIMEZONE = ZoneInfo("Europe/Berlin")
_RETAILER_NAMES = {
    "lidl": "LIDL",
    "netto": "Netto",
    "aldi_nord": "ALDI Nord",
    "edeka": "EDEKA",
}


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _local_label(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _aware(value).astimezone(_TIMEZONE).strftime("%d.%m.%Y %H:%M") + " (Berlīne)"


def _current_scope_snapshots(db: Session, retailer: str) -> list[SourceSnapshot]:
    query = select(SourceSnapshot).where(SourceSnapshot.source_chain == retailer)
    if retailer == "netto":
        query = query.where(SourceSnapshot.scope == "family_primary_netto")
    elif retailer == "aldi_nord":
        query = query.where(SourceSnapshot.scope == "national_offers")
    elif retailer == "edeka":
        query = query.where(SourceSnapshot.scope == "family_primary_edeka")
    elif retailer == "lidl":
        query = query.where(
            SourceSnapshot.strategy_hint == "lidl_public_flyer_json_canonical",
            or_(
                SourceSnapshot.scope == "current_week_flyer",
                SourceSnapshot.scope.like("physical_store_flyer:%"),
            ),
        )
    else:
        return []
    return list(db.scalars(query.order_by(SourceSnapshot.collected_at.desc()).limit(20)).all())


def _max_known_valid_until(db: Session, retailer: str) -> date | None:
    base_end, app_end = db.execute(
        select(
            func.max(OfferCandidateRecord.valid_until),
            func.max(OfferCandidateRecord.app_valid_until),
        ).where(OfferCandidateRecord.source_chain == retailer)
    ).one()
    values = [value for value in (base_end, app_end) if value is not None]
    return max(values) if values else None


def _explicit_verified_empty(snapshot: SourceSnapshot | None, day: date) -> bool:
    if snapshot is None or snapshot.success is not True:
        return False
    try:
        offer_count = int((snapshot.keyword_hits or {}).get("offer_count"))
    except (TypeError, ValueError):
        return False
    return (
        offer_count == 0
        and _aware(snapshot.collected_at).astimezone(_TIMEZONE).date() == day
    )


def _status(
    state: str,
    title: str,
    message: str,
    *,
    retailer: str | None,
    reason: str,
    last_checked_at: datetime | None = None,
) -> dict[str, Any]:
    return {
        "state": state,
        "title": title,
        "message": message,
        "reason": reason,
        "retailer": retailer,
        "retailer_name": _RETAILER_NAMES.get(retailer or "", retailer or ""),
        "scope": "current_deals",
        "scope_label": "Dienas piedāvājumi",
        "scope_note": (
            "Īso periodu pierādījumi tiek vērtēti atsevišķi; "
            "to statuss netiek attiecināts uz visu veikalu."
        ),
        "last_checked_at": last_checked_at,
        "last_checked_label": _local_label(last_checked_at),
    }


def build_current_deals_status(
    db: Session,
    current: Any,
    day: date,
    *,
    retailer: str = "",
    query: str = "",
    today: date | None = None,
) -> dict[str, Any] | None:
    """Explain an empty current-deals result without inferring source truth from count==0."""

    if current.count:
        return None

    selected_retailer = retailer if retailer in _RETAILER_NAMES else ""
    underlying_current = (
        current.retailer_availability[selected_retailer]["current"]
        if selected_retailer
        else current.availability_counts["current"]
    )
    if current.available_count > 0 or underlying_current > 0:
        return _status(
            "filtered_empty",
            "Filtrs neatdeva rezultātus",
            "Avota dati ir pieejami, bet šai meklēšanai, veikala atlasei vai lapai nekas neatbilst.",
            retailer=selected_retailer or None,
            reason="current_rows_exist_but_selected_projection_is_empty",
        )

    if not selected_retailer:
        return _status(
            "verification_pending",
            "Atlasē nav rezultātu",
            "Izvēlies konkrētu veikalu, lai redzētu tā dienas piedāvājumu pārbaudes statusu.",
            retailer=None,
            reason="retailer_not_selected_for_source_status",
        )

    snapshots = _current_scope_snapshots(db, selected_retailer)
    latest_attempt = snapshots[0] if snapshots else None
    successful = [snapshot for snapshot in snapshots if snapshot.success is True]
    latest_success = successful[0] if successful else None

    if (
        latest_attempt is not None
        and latest_attempt.success is not True
        and (
            latest_success is None
            or _aware(latest_attempt.collected_at) > _aware(latest_success.collected_at)
        )
    ):
        return _status(
            "source_unavailable",
            "Avots pašlaik nav pieejams",
            "Pēdējais šī veikala dienas piedāvājumu pārbaudes mēģinājums neizdevās. Tas nenozīmē, ka akciju nav.",
            retailer=selected_retailer,
            reason="latest_current_source_attempt_failed",
            last_checked_at=latest_attempt.collected_at,
        )

    if _explicit_verified_empty(latest_success, day):
        return _status(
            "no_offers",
            "Pārbaudē piedāvājumi netika atrasti",
            "Šīs dienas current-deals avots tika sekmīgi pārbaudīts un eksplicīti norādīja 0 piedāvājumu.",
            retailer=selected_retailer,
            reason="successful_current_snapshot_explicit_zero_offer_count",
            last_checked_at=latest_success.collected_at,
        )

    effective_today = today or datetime.now(_TIMEZONE).date()
    if day > effective_today:
        return _status(
            "not_published_yet",
            "Šai dienai dati vēl nav pārbaudīti",
            "Izvēlētā diena ir nākotnē, un nav pārbaudītu dienas piedāvājumu datu, kas to aptvertu.",
            retailer=selected_retailer,
            reason="future_day_not_covered_by_verified_current_evidence",
            last_checked_at=latest_success.collected_at if latest_success else None,
        )

    latest_valid_until = _max_known_valid_until(db, selected_retailer)
    if latest_valid_until is not None and latest_valid_until < day:
        return _status(
            "stale_data",
            "Pieejamie dati ir novecojuši",
            f"Pēdējais zināmais piedāvājumu derīguma logs beidzas {latest_valid_until:%d.%m.%Y}, pirms izvēlētās dienas.",
            retailer=selected_retailer,
            reason="latest_known_offer_window_precedes_selected_day",
            last_checked_at=latest_success.collected_at if latest_success else None,
        )

    return _status(
        "verification_pending",
        "Pārbaude vēl nav pabeigta",
        "Nav pietiekamu current-deals pierādījumu, lai apgalvotu, ka šim veikalam piedāvājumu nav.",
        retailer=selected_retailer,
        reason="no_verified_empty_or_failure_state_for_selected_day",
        last_checked_at=latest_success.collected_at if latest_success else None,
    )
