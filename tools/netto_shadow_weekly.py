from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from enum import StrEnum
from hashlib import sha256
from typing import Any, Iterable, Mapping

from netto_shadow_promotion import (
    EvidenceBinding,
    EvidenceStatus,
    _mapping,
    _optional_text,
    _parse_date,
    _require_sha,
    verify_binding_files,
)


MAX_RETRIES = 3


class WeeklyAction(StrEnum):
    WAIT_FOR_WINDOW = "wait_for_window"
    UNCHANGED_NOOP = "unchanged_noop"
    SAFE_EMPTY_NO_PDF = "safe_empty_no_pdf"
    RETRY_FAIL_CLOSED = "retry_fail_closed"
    ALERT_RETRY_EXHAUSTED = "alert_retry_exhausted"
    ALERT_STALE_WEEK = "alert_stale_week"
    RUN_SHADOW = "run_shadow"
    WRITE_PLAN_READY = "write_plan_ready"


@dataclass(frozen=True)
class WeeklyDecision:
    action: WeeklyAction
    severity: str
    reason: str
    alert_key: str | None
    retry_after_seconds: int | None
    production_write_authorized: bool
    daily_specials_mode: str


@dataclass(frozen=True)
class WeeklyInput:
    today: date
    binding: EvidenceBinding
    campaign_key: str
    previous_campaign_key: str | None
    previous_evidence_identity: str | None
    shadow_passed: bool | None
    retry_count: int
    last_success_valid_until: date | None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "WeeklyInput":
        return cls(
            today=_parse_date(raw.get("today"), "today"),
            binding=EvidenceBinding.from_mapping(_mapping(raw.get("binding"), "binding")),
            campaign_key=str(raw.get("campaign_key") or ""),
            previous_campaign_key=_optional_text(raw.get("previous_campaign_key")),
            previous_evidence_identity=_optional_text(raw.get("previous_evidence_identity")),
            shadow_passed=_optional_bool(raw.get("shadow_passed")),
            retry_count=int(raw.get("retry_count") or 0),
            last_success_valid_until=(
                _parse_date(raw.get("last_success_valid_until"), "last_success_valid_until")
                if raw.get("last_success_valid_until") is not None
                else None
            ),
        )

    def validate(self) -> None:
        self.binding.validate()
        if not self.campaign_key:
            raise ValueError("campaign_key is required")
        if self.retry_count < 0:
            raise ValueError("retry_count cannot be negative")
        if self.previous_evidence_identity:
            _require_sha(self.previous_evidence_identity, "previous_evidence_identity")


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raise ValueError("shadow_passed must be true, false or null")


def verify_weekly_input(value: WeeklyInput | Mapping[str, Any]) -> tuple[WeeklyInput, str]:
    item = value if isinstance(value, WeeklyInput) else WeeklyInput.from_mapping(value)
    item.validate()
    verification = verify_binding_files(item.binding)
    normalized = replace(item.binding, evidence_status=verification.status)
    verified_item = replace(item, binding=normalized)
    verified_item.validate()
    return verified_item, verification.reason


def decide_weekly_action(value: WeeklyInput | Mapping[str, Any]) -> WeeklyDecision:
    item = value if isinstance(value, WeeklyInput) else WeeklyInput.from_mapping(value)
    item.validate()
    binding = item.binding

    if item.last_success_valid_until and item.today > item.last_success_valid_until + timedelta(days=1):
        return WeeklyDecision(
            action=WeeklyAction.ALERT_STALE_WEEK,
            severity="error",
            reason="No verified campaign covers the current date; weekly refresh is stale.",
            alert_key=f"netto-stale-week-{item.today.isoformat()}",
            retry_after_seconds=None,
            production_write_authorized=False,
            daily_specials_mode="fail_closed",
        )

    if item.today < binding.valid_from:
        return WeeklyDecision(
            action=WeeklyAction.WAIT_FOR_WINDOW,
            severity="info",
            reason="Target campaign has not started; Sunday transition must not write early.",
            alert_key=None,
            retry_after_seconds=3600,
            production_write_authorized=False,
            daily_specials_mode="existing_verified_window_only",
        )

    if binding.evidence_status in {EvidenceStatus.MISSING, EvidenceStatus.CORRUPT}:
        if item.retry_count >= MAX_RETRIES:
            return WeeklyDecision(
                action=WeeklyAction.ALERT_RETRY_EXHAUSTED,
                severity="error",
                reason=f"{binding.evidence_status.value} evidence remained unresolved after bounded retries.",
                alert_key=f"netto-evidence-{binding.evidence_status.value}-{item.campaign_key}",
                retry_after_seconds=None,
                production_write_authorized=False,
                daily_specials_mode="fail_closed",
            )
        return WeeklyDecision(
            action=WeeklyAction.RETRY_FAIL_CLOSED,
            severity="warning",
            reason=f"{binding.evidence_status.value} evidence is not safe for parsing or writes.",
            alert_key=None,
            retry_after_seconds=15 * 60 * (item.retry_count + 1),
            production_write_authorized=False,
            daily_specials_mode="fail_closed",
        )

    unchanged = (
        item.previous_campaign_key == item.campaign_key
        and item.previous_evidence_identity == binding.identity_sha256()
    )
    if unchanged:
        return WeeklyDecision(
            action=WeeklyAction.UNCHANGED_NOOP,
            severity="info",
            reason="Campaign key and complete immutable evidence identity are unchanged.",
            alert_key=None,
            retry_after_seconds=None,
            production_write_authorized=False,
            daily_specials_mode=(
                "safe_empty_verified_no_pdf"
                if binding.evidence_status is EvidenceStatus.VERIFIED_NO_PDF
                else "bound_pdf"
            ),
        )

    if binding.evidence_status is EvidenceStatus.VERIFIED_NO_PDF:
        return WeeklyDecision(
            action=WeeklyAction.SAFE_EMPTY_NO_PDF,
            severity="info",
            reason="Campaign explicitly proves that no prospect PDF is available.",
            alert_key=None,
            retry_after_seconds=None,
            production_write_authorized=False,
            daily_specials_mode="safe_empty_verified_no_pdf",
        )

    if item.shadow_passed is None:
        return WeeklyDecision(
            action=WeeklyAction.RUN_SHADOW,
            severity="info",
            reason="Bound PDF evidence is ready for shadow validation.",
            alert_key=None,
            retry_after_seconds=None,
            production_write_authorized=False,
            daily_specials_mode="bound_pdf_shadow_pending",
        )

    if item.shadow_passed is False:
        if item.retry_count >= MAX_RETRIES:
            return WeeklyDecision(
                action=WeeklyAction.ALERT_RETRY_EXHAUSTED,
                severity="error",
                reason="Shadow validation failed after bounded retries.",
                alert_key=f"netto-shadow-failed-{item.campaign_key}",
                retry_after_seconds=None,
                production_write_authorized=False,
                daily_specials_mode="fail_closed",
            )
        return WeeklyDecision(
            action=WeeklyAction.RETRY_FAIL_CLOSED,
            severity="warning",
            reason="Shadow validation failed; no production write plan is allowed yet.",
            alert_key=None,
            retry_after_seconds=15 * 60 * (item.retry_count + 1),
            production_write_authorized=False,
            daily_specials_mode="fail_closed",
        )

    return WeeklyDecision(
        action=WeeklyAction.WRITE_PLAN_READY,
        severity="info",
        reason="Shadow validation passed; exact create-only plan may be reviewed separately.",
        alert_key=None,
        retry_after_seconds=None,
        production_write_authorized=False,
        daily_specials_mode="bound_pdf_shadow_passed",
    )


def build_write_plan(
    *,
    binding: EvidenceBinding,
    campaign_key: str,
    shadow_report_sha256: str,
    candidate_count: int,
    existing_snapshot_ids: Iterable[str],
) -> dict[str, Any]:
    binding.validate()
    if binding.evidence_status is not EvidenceStatus.PDF_BOUND:
        raise ValueError("write plans require bound PDF evidence")
    _require_sha(shadow_report_sha256, "shadow_report_sha256")
    if candidate_count < 0:
        raise ValueError("candidate_count cannot be negative")
    snapshot_identity = sha256(
        f"{campaign_key}|{binding.identity_sha256()}".encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": 1,
        "strategy": "netto_exact_create_only_write_plan_v1",
        "campaign_key": campaign_key,
        "snapshot_identity": snapshot_identity,
        "store_external_id": binding.store_external_id,
        "scope": binding.scope,
        "valid_from": binding.valid_from.isoformat(),
        "valid_until": binding.valid_until.isoformat(),
        "evidence_identity": binding.identity_sha256(),
        "manifest_path": binding.manifest_path,
        "manifest_sha256": binding.manifest_sha256,
        "html_path": binding.html_path,
        "html_sha256": binding.html_sha256,
        "pdf_path": binding.pdf_path,
        "pdf_sha256": binding.pdf_sha256,
        "parser_identity": binding.parser_identity,
        "shadow_report_sha256": shadow_report_sha256,
        "candidate_count": candidate_count,
        "existing_snapshot_ids": sorted(set(existing_snapshot_ids)),
        "mutation_policy": "insert_new_snapshot_and_candidates_only",
        "immutable_snapshot_replacement_allowed": False,
        "automatic_approval_enabled": False,
        "automatic_publish_enabled": False,
        "apply_authorized": False,
        "rollback": {
            "scope": "only_rows_created_by_snapshot_identity",
            "snapshot_identity": snapshot_identity,
            "preexisting_rows_must_remain_unchanged": True,
            "requires_separate_authorization": True,
        },
    }
