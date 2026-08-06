from __future__ import annotations

from datetime import date
import json
import logging
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.aldi_nord_daily_special import (
    AldiNordDailySpecialError,
    cached_aldi_nord_daily_specials,
)
import app.netto_daily_special_api as daily_api
import app.weekly_special_api as weekly_api


_LOG = logging.getLogger(__name__)


def _empty_week(week_start: date) -> dict[date, list[weekly_api.WeeklyDealOut]]:
    return {day: [] for day in weekly_api._week_dates(week_start)}


def _record_offer(
    offers_by_key: dict[tuple[str, str, date], Any],
    offer: Any,
    valid_on: date,
) -> None:
    key = (
        offer.source_chain.value,
        offer.source_offer_id or "",
        valid_on,
    )
    existing = offers_by_key.get(key)
    if existing is None or offer.collected_at > existing.collected_at:
        offers_by_key[key] = offer


def _netto_offers_for_day(db: Session, valid_on: date) -> tuple[Any, ...]:
    try:
        snapshot = daily_api._latest_snapshot(db, valid_on)
    except HTTPException as exc:
        _LOG.warning(
            "weekly Netto evidence unavailable for %s: %s",
            valid_on.isoformat(),
            exc.detail,
        )
        return ()

    if snapshot is None:
        return ()

    try:
        return daily_api._cached_snapshot_offers(
            str(snapshot.id),
            snapshot.snapshot_path or "",
            snapshot.sha256 or "",
            snapshot.source_url,
            snapshot.final_url or "",
            snapshot.collected_at.isoformat(),
        )
    except RuntimeError as exc:
        if str(exc) != "Netto prospect PDF path is missing":
            _LOG.warning(
                "weekly Netto evidence failed for %s: %s",
                valid_on.isoformat(),
                exc,
            )
        return ()
    except (OSError, ValueError, json.JSONDecodeError, ImportError) as exc:
        _LOG.warning(
            "weekly Netto evidence failed for %s: %s",
            valid_on.isoformat(),
            exc,
        )
        return ()


def _aldi_offers(db: Session) -> tuple[Any, ...]:
    try:
        snapshot = daily_api._latest_aldi_nord_snapshot(db)
    except HTTPException as exc:
        _LOG.warning("weekly ALDI evidence unavailable: %s", exc.detail)
        return ()

    if snapshot is None:
        return ()

    try:
        return cached_aldi_nord_daily_specials(
            str(snapshot.id),
            snapshot.snapshot_path or "",
            snapshot.sha256 or "",
            snapshot.source_url,
            snapshot.final_url or "",
            snapshot.collected_at.isoformat(),
        )
    except AldiNordDailySpecialError as exc:
        _LOG.warning("weekly ALDI evidence failed: %s", exc)
        return ()
    except (OSError, ValueError, json.JSONDecodeError, ImportError) as exc:
        _LOG.warning("weekly ALDI evidence failed: %s", exc)
        return ()


def isolated_explicit_daily_specials(
    db: Session,
    week_start: date,
    week_end: date,
) -> dict[date, list[weekly_api.WeeklyDealOut]]:
    """Load immutable specials without allowing one source to fail the week.

    A failed source remains fail-closed: it contributes no rows. Valid ordinary
    offers and valid evidence from other retailers remain available.
    """

    result = _empty_week(week_start)
    offers_by_key: dict[tuple[str, str, date], Any] = {}

    for valid_on in weekly_api._week_dates(week_start):
        for offer in _netto_offers_for_day(db, valid_on):
            raw = offer.raw_payload
            if (
                raw.get("is_daily_special") is not True
                or raw.get("special_confidence") != "high"
                or raw.get("special_valid_on") != valid_on.isoformat()
            ):
                continue
            _record_offer(offers_by_key, offer, valid_on)

    for offer in _aldi_offers(db):
        raw = offer.raw_payload
        if (
            raw.get("is_daily_special") is not True
            or raw.get("special_confidence") != "high"
        ):
            continue
        try:
            valid_on = date.fromisoformat(
                str(raw.get("special_valid_on") or "")
            )
        except ValueError:
            continue
        if week_start <= valid_on <= week_end:
            _record_offer(offers_by_key, offer, valid_on)

    for (_, _, valid_on), offer in offers_by_key.items():
        result[valid_on].append(
            weekly_api.WeeklyDealOut.model_validate(
                daily_api._to_output(offer, valid_on).model_dump()
            )
        )

    return result


def install() -> None:
    if getattr(weekly_api, "_source_isolation_patch_installed", False):
        return
    weekly_api._explicit_daily_specials = isolated_explicit_daily_specials
    weekly_api._source_isolation_patch_installed = True


install()
