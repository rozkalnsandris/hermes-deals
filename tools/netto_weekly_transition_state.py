from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from netto_shadow_promotion import EvidenceBinding
from netto_shadow_weekly import WeeklyAction, WeeklyInput, decide_weekly_action, verify_weekly_input

SCHEMA_VERSION = 1
STRATEGY = "netto_weekly_transition_artifact_state_v1"
SELECTOR_STRATEGY = "netto_heldout_verified_source_selector_v1"
SAFE_ACTIONS = {WeeklyAction.RUN_SHADOW.value, WeeklyAction.SAFE_EMPTY_NO_PDF.value, WeeklyAction.WRITE_PLAN_READY.value}
MAX_RECORDS = 16


class WeeklyTransitionStateError(ValueError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise WeeklyTransitionStateError(f"input must be a regular file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WeeklyTransitionStateError(f"invalid JSON input: {path}") from exc
    if not isinstance(value, dict):
        raise WeeklyTransitionStateError(f"JSON input must contain an object: {path}")
    return value


def write_create_only(path: Path, value: Any) -> str:
    if path.exists() or path.is_symlink():
        raise WeeklyTransitionStateError(f"output already exists: {path}")
    data = canonical_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def normalize_selector(payload: Mapping[str, Any]) -> tuple[EvidenceBinding, str, str]:
    if payload.get("strategy") != SELECTOR_STRATEGY:
        raise WeeklyTransitionStateError("selector strategy mismatch")
    if payload.get("review_only") is not True or payload.get("promotion_ready") is not False:
        raise WeeklyTransitionStateError("selector safety state mismatch")
    selection = payload.get("selection")
    if not isinstance(selection, Mapping) or selection.get("fallback_to_older_campaign_allowed") is not False:
        raise WeeklyTransitionStateError("selector fallback policy mismatch")
    raw = payload.get("binding")
    if not isinstance(raw, Mapping):
        raise WeeklyTransitionStateError("selector binding is missing")
    binding = EvidenceBinding.from_mapping(raw)
    binding.validate()
    if binding.store_external_id != "5659" or binding.scope != "family_primary_netto":
        raise WeeklyTransitionStateError("selector store/scope mismatch")
    identity = binding.identity_sha256()
    if payload.get("evidence_identity_sha256") != identity:
        raise WeeklyTransitionStateError("selector evidence identity mismatch")
    campaign = str(payload.get("campaign_key") or "").strip()
    if not campaign:
        raise WeeklyTransitionStateError("selector campaign key is missing")
    if payload.get("campaign_window") != {"start": binding.valid_from.isoformat(), "end": binding.valid_until.isoformat()}:
        raise WeeklyTransitionStateError("selector campaign window mismatch")
    return binding, campaign, identity


def validate_previous(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    if payload.get("schema_version") != SCHEMA_VERSION or payload.get("strategy") != STRATEGY:
        raise WeeklyTransitionStateError("previous state schema/strategy mismatch")
    if payload.get("store_external_id") != "5659" or payload.get("scope") != "family_primary_netto":
        raise WeeklyTransitionStateError("previous state store/scope mismatch")
    if payload.get("production_write_authorized") is not False:
        raise WeeklyTransitionStateError("previous state contains production authorization")
    raw_records = payload.get("scheduled_transitions")
    if not isinstance(raw_records, list) or len(raw_records) > MAX_RECORDS:
        raise WeeklyTransitionStateError("previous transition history is invalid")
    seen: set[tuple[str, str]] = set()
    records: list[dict[str, Any]] = []
    for raw in raw_records:
        if not isinstance(raw, Mapping):
            raise WeeklyTransitionStateError("transition record must be an object")
        record = dict(raw)
        campaign = str(record.get("campaign_key") or "")
        identity = str(record.get("evidence_identity") or "")
        if not campaign or not re.fullmatch(r"[0-9a-f]{64}", identity):
            raise WeeklyTransitionStateError("transition identity is invalid")
        if (campaign, identity) in seen:
            raise WeeklyTransitionStateError("duplicate transition identity")
        seen.add((campaign, identity))
        if record.get("trigger_event") != "schedule" or record.get("production_write_authorized") is not False:
            raise WeeklyTransitionStateError("persisted transition must be unattended and non-writing")
        if str(record.get("action") or "") not in SAFE_ACTIONS:
            raise WeeklyTransitionStateError("persisted transition action is not safe")
        start = date.fromisoformat(str(record.get("valid_from") or ""))
        end = date.fromisoformat(str(record.get("valid_until") or ""))
        if start > end:
            raise WeeklyTransitionStateError("transition validity is invalid")
        datetime.fromisoformat(str(record.get("recorded_at") or "").replace("Z", "+00:00"))
        records.append(record)
    return records


def chain_length(records: list[Mapping[str, Any]]) -> int:
    ordered = sorted(records, key=lambda row: (str(row["valid_from"]), str(row["campaign_key"])))
    best = current = 0
    previous_end: date | None = None
    for row in ordered:
        start = date.fromisoformat(str(row["valid_from"]))
        end = date.fromisoformat(str(row["valid_until"]))
        current = current + 1 if previous_end is not None and (start - previous_end).days in {1, 2} else 1
        best = max(best, current)
        previous_end = end
    return best


def binding_mapping(binding: EvidenceBinding) -> dict[str, Any]:
    return {
        "manifest_path": binding.manifest_path,
        "manifest_sha256": binding.manifest_sha256,
        "html_path": binding.html_path,
        "html_sha256": binding.html_sha256,
        "evidence_status": binding.evidence_status.value,
        "pdf_path": binding.pdf_path,
        "pdf_sha256": binding.pdf_sha256,
        "parser_identity": binding.parser_identity,
        "store_external_id": binding.store_external_id,
        "scope": binding.scope,
        "valid_from": binding.valid_from.isoformat(),
        "valid_until": binding.valid_until.isoformat(),
        "no_pdf_reason": binding.no_pdf_reason,
    }


def build_state(
    selector: Mapping[str, Any],
    *,
    today: date,
    observed_at: datetime,
    trigger_event: str,
    previous: Mapping[str, Any] | None,
    previous_state_sha256: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if trigger_event not in {"schedule", "workflow_dispatch"}:
        raise WeeklyTransitionStateError("unsupported trigger event")
    if observed_at.tzinfo is None:
        raise WeeklyTransitionStateError("observed_at must be timezone-aware")
    binding, campaign, identity = normalize_selector(selector)
    records = validate_previous(previous) if previous is not None else []
    latest = records[-1] if records else None
    raw_input = {
        "today": today.isoformat(),
        "binding": binding_mapping(binding),
        "campaign_key": campaign,
        "previous_campaign_key": latest["campaign_key"] if latest else None,
        "previous_evidence_identity": latest["evidence_identity"] if latest else None,
        "shadow_passed": None,
        "retry_count": 0,
        "last_success_valid_until": latest["valid_until"] if latest else None,
    }
    verified, verification_reason = verify_weekly_input(WeeklyInput.from_mapping(raw_input))
    decision = decide_weekly_action(verified)
    duplicate = any(row["campaign_key"] == campaign and row["evidence_identity"] == identity for row in records)
    recorded = trigger_event == "schedule" and decision.action.value in SAFE_ACTIONS and not duplicate
    if recorded:
        records.append(
            {
                "campaign_key": campaign,
                "evidence_identity": identity,
                "valid_from": verified.binding.valid_from.isoformat(),
                "valid_until": verified.binding.valid_until.isoformat(),
                "evidence_status": verified.binding.evidence_status.value,
                "action": decision.action.value,
                "recorded_at": observed_at.astimezone(timezone.utc).isoformat(),
                "trigger_event": "schedule",
                "production_write_authorized": False,
            }
        )
        records = records[-MAX_RECORDS:]
    consecutive = chain_length(records)
    state = {
        "schema_version": SCHEMA_VERSION,
        "strategy": STRATEGY,
        "store_external_id": "5659",
        "scope": "family_primary_netto",
        "generated_at": observed_at.astimezone(timezone.utc).isoformat(),
        "today": today.isoformat(),
        "trigger_event": trigger_event,
        "previous_state_sha256": previous_state_sha256,
        "current_campaign_key": campaign,
        "current_evidence_identity": identity,
        "current_evidence_status": verified.binding.evidence_status.value,
        "current_validity": {"start": verified.binding.valid_from.isoformat(), "end": verified.binding.valid_until.isoformat()},
        "current_decision": {
            "action": decision.action.value,
            "severity": decision.severity,
            "reason": decision.reason,
            "alert_key": decision.alert_key,
            "daily_specials_mode": decision.daily_specials_mode,
            "verification_reason": verification_reason,
            "production_write_authorized": False,
        },
        "transition_recorded": recorded,
        "scheduled_transitions": records,
        "consecutive_unattended_transition_count": consecutive,
        "issue_28_two_real_transitions_ready": consecutive >= 2,
        "production_write_authorized": False,
        "database_write_performed": False,
        "review_write_performed": False,
        "deployment_performed": False,
        "automatic_approval_enabled": False,
        "automatic_publish_enabled": False,
    }
    receipt = {
        "schema_version": 1,
        "strategy": "netto_weekly_transition_artifact_receipt_v1",
        "state_sha256": hashlib.sha256(canonical_bytes(state)).hexdigest(),
        "previous_state_sha256": previous_state_sha256,
        "current_campaign_key": campaign,
        "current_evidence_identity": identity,
        "transition_recorded": recorded,
        "current_action": decision.action.value,
        "current_severity": decision.severity,
        "consecutive_unattended_transition_count": consecutive,
        "issue_28_two_real_transitions_ready": consecutive >= 2,
        "production_write_authorized": False,
    }
    return state, receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Persist Netto weekly transition evidence in an immutable artifact state")
    parser.add_argument("--selector", type=Path, required=True)
    parser.add_argument("--previous-state", type=Path)
    parser.add_argument("--today", type=date.fromisoformat, required=True)
    parser.add_argument("--observed-at", type=datetime.fromisoformat, required=True)
    parser.add_argument("--trigger-event", choices=("schedule", "workflow_dispatch"), required=True)
    parser.add_argument("--state-output", type=Path, required=True)
    parser.add_argument("--receipt-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        previous = load_json(args.previous_state) if args.previous_state else None
        previous_sha = sha_file(args.previous_state) if args.previous_state else None
        state, receipt = build_state(
            load_json(args.selector), today=args.today, observed_at=args.observed_at,
            trigger_event=args.trigger_event, previous=previous, previous_state_sha256=previous_sha,
        )
        state_sha = write_create_only(args.state_output, state)
        if state_sha != receipt["state_sha256"]:
            raise WeeklyTransitionStateError("state file SHA differs from receipt")
        write_create_only(args.receipt_output, receipt)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR|{exc}", file=sys.stderr)
        return 2
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
