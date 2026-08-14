from __future__ import annotations

from datetime import date

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.netto_daily_special_api as daily_api
from app.models import SourceSnapshot


NETTO_MANIFEST_CONTENT_TYPE = (
    "application/vnd.hermes-deals.netto-store-prospect+json"
)


def _is_manifest_snapshot(snapshot: SourceSnapshot) -> bool:
    return (
        getattr(snapshot, "content_type", None)
        == NETTO_MANIFEST_CONTENT_TYPE
    )


def latest_manifest_snapshot(
    db: Session,
    effective_date: date,
) -> SourceSnapshot | None:
    snapshots = db.scalars(
        select(SourceSnapshot)
        .where(
            SourceSnapshot.source_chain == "netto",
            SourceSnapshot.scope == "family_primary_netto",
            SourceSnapshot.success.is_(True),
            SourceSnapshot.content_type == NETTO_MANIFEST_CONTENT_TYPE,
        )
        .order_by(SourceSnapshot.collected_at.desc())
    ).all()
    snapshots = [
        snapshot
        for snapshot in snapshots
        if _is_manifest_snapshot(snapshot)
    ]
    if not snapshots:
        raise HTTPException(
            status_code=503,
            detail="Immutable Netto snapshots are unavailable",
        )
    for snapshot in snapshots:
        valid_from, valid_until = daily_api._snapshot_manifest_window(snapshot)
        if valid_from <= effective_date <= valid_until:
            return snapshot
    return None


def install() -> None:
    if getattr(daily_api, "_legacy_snapshot_compat_patch_installed", False):
        return
    daily_api._NETTO_MANIFEST_CONTENT_TYPE = NETTO_MANIFEST_CONTENT_TYPE
    daily_api._latest_snapshot = latest_manifest_snapshot
    daily_api._legacy_snapshot_compat_patch_installed = True


install()
