from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.edeka_store_offers import (
    MANIFEST_CONTENT_TYPE,
    MANIFEST_STRATEGY,
    _read_manifest_bytes,
    _read_raw_html,
    _validate_manifest_source,
    _validate_source,
)
from app.models import SourceSnapshot
from app.settings import get_settings
from app.source_config import SourceConfig, load_sources


_LOCAL_TZ = ZoneInfo("Europe/Berlin")
_DEFAULT_MAX_SUCCESS_AGE_HOURS = 192.0
_DEFAULT_FAILURE_GRACE_HOURS = 30.0
_MONDAY_REFRESH_GRACE_END = time(8, 0)


@dataclass(frozen=True)
class EdekaHealthResult:
    status: str
    critical: bool
    reason: str
    checked_at: str
    latest_attempt_id: str | None
    latest_attempt_collected_at: str | None
    latest_attempt_success: bool | None
    latest_attempt_strategy: str | None
    latest_success_id: str | None
    latest_success_collected_at: str | None
    latest_success_age_hours: float | None
    manifest_sha256: str | None
    campaign_valid_from: str | None
    campaign_valid_until: str | None
    offer_count: int | None

    @property
    def exit_code(self) -> int:
        return 2 if self.critical else 0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["exit_code"] = self.exit_code
        return payload


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("EDEKA monitor requires timezone-aware timestamps")
    return value.astimezone(timezone.utc)


def _hours_between(later: datetime, earlier: datetime) -> float:
    seconds = (_aware_utc(later) - _aware_utc(earlier)).total_seconds()
    return round(max(seconds, 0.0) / 3600.0, 2)


def _edeka_source() -> SourceConfig:
    settings = get_settings()
    matches = [
        source
        for source in load_sources(settings.sources_config)
        if source.enabled and source.chain == "edeka"
    ]
    if len(matches) != 1:
        raise ValueError(
            "Expected exactly one enabled EDEKA source, "
            f"found={len(matches)}"
        )
    source = matches[0]
    _validate_source(source)
    return source


def _latest_attempt(
    db: Session,
    source: SourceConfig,
) -> SourceSnapshot | None:
    return db.scalar(
        select(SourceSnapshot)
        .where(
            SourceSnapshot.source_chain == source.chain,
            SourceSnapshot.scope == source.scope,
        )
        .order_by(SourceSnapshot.collected_at.desc())
        .limit(1)
    )


def _latest_success_manifest(
    db: Session,
    source: SourceConfig,
) -> SourceSnapshot | None:
    return db.scalar(
        select(SourceSnapshot)
        .where(
            SourceSnapshot.source_chain == source.chain,
            SourceSnapshot.scope == source.scope,
            SourceSnapshot.content_type == MANIFEST_CONTENT_TYPE,
            SourceSnapshot.strategy_hint == MANIFEST_STRATEGY,
            SourceSnapshot.success.is_(True),
        )
        .order_by(SourceSnapshot.collected_at.desc())
        .limit(1)
    )


def _iso(snapshot: SourceSnapshot | None, field: str) -> str | None:
    if snapshot is None:
        return None
    value = getattr(snapshot, field, None)
    if value is None:
        return None
    if isinstance(value, datetime):
        return _aware_utc(value).isoformat()
    return str(value)


def _result(
    *,
    status: str,
    critical: bool,
    reason: str,
    now: datetime,
    attempt: SourceSnapshot | None,
    success: SourceSnapshot | None,
    age_hours: float | None = None,
    manifest: dict[str, object] | None = None,
) -> EdekaHealthResult:
    offer_count = manifest.get("offer_count") if manifest is not None else None
    return EdekaHealthResult(
        status=status,
        critical=critical,
        reason=reason,
        checked_at=_aware_utc(now).isoformat(),
        latest_attempt_id=_iso(attempt, "id"),
        latest_attempt_collected_at=_iso(attempt, "collected_at"),
        latest_attempt_success=(
            bool(attempt.success) if attempt is not None else None
        ),
        latest_attempt_strategy=_iso(attempt, "strategy_hint"),
        latest_success_id=_iso(success, "id"),
        latest_success_collected_at=_iso(success, "collected_at"),
        latest_success_age_hours=age_hours,
        manifest_sha256=_iso(success, "sha256"),
        campaign_valid_from=(
            str(manifest.get("valid_from")) if manifest is not None else None
        ),
        campaign_valid_until=(
            str(manifest.get("valid_until")) if manifest is not None else None
        ),
        offer_count=(offer_count if isinstance(offer_count, int) else None),
    )


def _verified_manifest(
    snapshot: SourceSnapshot,
    source: SourceConfig,
) -> dict[str, object]:
    if not snapshot.snapshot_path or not snapshot.sha256:
        raise ValueError("EDEKA manifest snapshot binding is incomplete")
    if snapshot.content_type != MANIFEST_CONTENT_TYPE:
        raise ValueError("EDEKA successful snapshot content type is not a manifest")
    if snapshot.strategy_hint != MANIFEST_STRATEGY:
        raise ValueError("EDEKA successful snapshot strategy mismatch")

    manifest = _read_manifest_bytes(Path(snapshot.snapshot_path), snapshot.sha256)
    _validate_manifest_source(manifest, source)
    raw = _read_raw_html(manifest)

    if manifest.get("snapshot_id") != str(snapshot.id):
        raise ValueError("EDEKA manifest snapshot_id mismatch")
    if manifest.get("collected_at") != _aware_utc(snapshot.collected_at).isoformat():
        raise ValueError("EDEKA manifest collected_at mismatch")
    if manifest.get("raw_content_bytes") != len(raw):
        raise ValueError("EDEKA manifest raw_content_bytes mismatch")
    if snapshot.content_bytes != len(raw):
        raise ValueError("EDEKA SourceSnapshot content_bytes mismatch")

    offer_count = manifest.get("offer_count")
    if not isinstance(offer_count, int) or offer_count <= 0:
        raise ValueError("EDEKA manifest offer_count is not positive")

    valid_from = manifest.get("valid_from")
    valid_until = manifest.get("valid_until")
    if not isinstance(valid_from, str) or not isinstance(valid_until, str):
        raise ValueError("EDEKA manifest campaign window is missing")
    if date.fromisoformat(valid_until) < date.fromisoformat(valid_from):
        raise ValueError("EDEKA manifest campaign window is inverted")
    return manifest


def evaluate_edeka_health(
    db: Session,
    source: SourceConfig,
    *,
    now: datetime | None = None,
    max_success_age_hours: float = _DEFAULT_MAX_SUCCESS_AGE_HOURS,
    failure_grace_hours: float = _DEFAULT_FAILURE_GRACE_HOURS,
) -> EdekaHealthResult:
    _validate_source(source)
    checked_at = _aware_utc(now or datetime.now(timezone.utc))
    if max_success_age_hours <= 0:
        raise ValueError("max_success_age_hours must be positive")
    if failure_grace_hours < 0:
        raise ValueError("failure_grace_hours must be non-negative")

    attempt = _latest_attempt(db, source)
    success = _latest_success_manifest(db, source)
    if success is None:
        return _result(
            status="stale",
            critical=True,
            reason="no_successful_immutable_manifest",
            now=checked_at,
            attempt=attempt,
            success=None,
        )

    age_hours = _hours_between(checked_at, success.collected_at)
    try:
        manifest = _verified_manifest(success, source)
    except Exception as exc:
        return _result(
            status="stale",
            critical=True,
            reason=f"manifest_verification_failed:{type(exc).__name__}:{exc}",
            now=checked_at,
            attempt=attempt,
            success=success,
            age_hours=age_hours,
        )

    if age_hours > max_success_age_hours:
        return _result(
            status="stale",
            critical=True,
            reason=(
                "successful_manifest_too_old:"
                f"age_hours={age_hours}:limit={max_success_age_hours}"
            ),
            now=checked_at,
            attempt=attempt,
            success=success,
            age_hours=age_hours,
            manifest=manifest,
        )

    if (
        attempt is not None
        and attempt.id != success.id
        and _aware_utc(attempt.collected_at) > _aware_utc(success.collected_at)
    ):
        if attempt.success:
            return _result(
                status="stale",
                critical=True,
                reason="newer_non_manifest_snapshot_is_not_authoritative",
                now=checked_at,
                attempt=attempt,
                success=success,
                age_hours=age_hours,
                manifest=manifest,
            )

        failure_age = _hours_between(checked_at, attempt.collected_at)
        if failure_age > failure_grace_hours:
            return _result(
                status="failed",
                critical=True,
                reason=(
                    "latest_collection_failed_beyond_retry_grace:"
                    f"age_hours={failure_age}:grace={failure_grace_hours}:"
                    f"error={attempt.error or 'unknown'}"
                ),
                now=checked_at,
                attempt=attempt,
                success=success,
                age_hours=age_hours,
                manifest=manifest,
            )
        return _result(
            status="warning",
            critical=False,
            reason=(
                "latest_collection_failed_within_retry_grace:"
                f"age_hours={failure_age}:grace={failure_grace_hours}:"
                f"error={attempt.error or 'unknown'}"
            ),
            now=checked_at,
            attempt=attempt,
            success=success,
            age_hours=age_hours,
            manifest=manifest,
        )

    local_now = checked_at.astimezone(_LOCAL_TZ)
    today = local_now.date()
    valid_from = date.fromisoformat(str(manifest["valid_from"]))
    valid_until = date.fromisoformat(str(manifest["valid_until"]))

    if today.weekday() == 6:
        if valid_from > today or valid_until < today - timedelta(days=1):
            return _result(
                status="stale",
                critical=True,
                reason="campaign_does_not_cover_expected_sunday_gap",
                now=checked_at,
                attempt=attempt,
                success=success,
                age_hours=age_hours,
                manifest=manifest,
            )
    elif not valid_from <= today <= valid_until:
        if (
            today.weekday() == 0
            and local_now.time() < _MONDAY_REFRESH_GRACE_END
            and valid_until >= today - timedelta(days=2)
        ):
            return _result(
                status="warning",
                critical=False,
                reason="monday_refresh_grace",
                now=checked_at,
                attempt=attempt,
                success=success,
                age_hours=age_hours,
                manifest=manifest,
            )
        return _result(
            status="stale",
            critical=True,
            reason=(
                "campaign_not_current:"
                f"today={today}:window={valid_from}..{valid_until}"
            ),
            now=checked_at,
            attempt=attempt,
            success=success,
            age_hours=age_hours,
            manifest=manifest,
        )

    return _result(
        status="healthy",
        critical=False,
        reason="immutable_manifest_current_and_verified",
        now=checked_at,
        attempt=attempt,
        success=success,
        age_hours=age_hours,
        manifest=manifest,
    )


def write_status(path: Path, result: EdekaHealthResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (
        json.dumps(
            result.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify EDEKA Patzer immutable source freshness"
    )
    parser.add_argument(
        "--max-success-age-hours",
        type=float,
        default=_DEFAULT_MAX_SUCCESS_AGE_HOURS,
    )
    parser.add_argument(
        "--failure-grace-hours",
        type=float,
        default=_DEFAULT_FAILURE_GRACE_HOURS,
    )
    parser.add_argument("--status-file", type=Path)
    args = parser.parse_args()

    try:
        source = _edeka_source()
        with SessionLocal() as db:
            result = evaluate_edeka_health(
                db,
                source,
                max_success_age_hours=args.max_success_age_hours,
                failure_grace_hours=args.failure_grace_hours,
            )
    except Exception as exc:
        payload = {
            "status": "stale",
            "critical": True,
            "reason": f"monitor_execution_failed:{type(exc).__name__}:{exc}",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "exit_code": 2,
        }
        print(json.dumps(payload, sort_keys=True), flush=True)
        return 2

    if args.status_file is not None:
        write_status(args.status_file, result)
    print(json.dumps(result.to_dict(), sort_keys=True), flush=True)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
