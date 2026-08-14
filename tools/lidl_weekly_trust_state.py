from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping

SCHEMA_VERSION = 1
STRATEGY = "lidl_weekly_trust_state_v1"
RECEIPT_STRATEGY = "lidl_weekly_trust_receipt_v1"
CONTROLLER_VERSION = "lidl-weekly-shadow-controller-v1"
SEMANTIC_VIEW_VERSION = "lidl-weekly-semantic-view-v1"
MAX_RECORDS = 16
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


class LidlWeeklyTrustStateError(ValueError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise LidlWeeklyTrustStateError(f"input must be a regular file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise LidlWeeklyTrustStateError(f"input must be a regular file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LidlWeeklyTrustStateError(f"invalid JSON input: {path}") from exc
    if not isinstance(value, dict):
        raise LidlWeeklyTrustStateError(f"JSON input must contain an object: {path}")
    return value


def write_create_only(path: Path, value: Any) -> str:
    if path.exists() or path.is_symlink():
        raise LidlWeeklyTrustStateError(f"output already exists: {path}")
    data = canonical_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def _sha256(value: Any, label: str) -> str:
    text = str(value or "")
    if _SHA256_RE.fullmatch(text) is None:
        raise LidlWeeklyTrustStateError(f"{label} is not SHA256")
    return text


def _controller_fingerprint(one_shot: Mapping[str, Any]) -> str:
    if one_shot.get("result") != "READY":
        raise LidlWeeklyTrustStateError("completed cycle one-shot result must be READY")
    expected_safety = {
        "dry_run": True,
        "corpus_write": False,
        "db_write": False,
        "review_seed": False,
        "auto_approve": False,
        "auto_publish": False,
        "systemd_change": False,
    }
    for key, value in expected_safety.items():
        if one_shot.get(key) is not value:
            raise LidlWeeklyTrustStateError(f"one-shot safety mismatch: {key}")

    corpus_match = one_shot.get("corpus_match")
    review_profile = one_shot.get("review_profile")
    if not isinstance(corpus_match, Mapping):
        raise LidlWeeklyTrustStateError("one-shot corpus_match is missing")
    if not isinstance(review_profile, Mapping):
        raise LidlWeeklyTrustStateError("one-shot review_profile is missing")

    identity = {
        "target": str(one_shot.get("target") or ""),
        "flyer_key": str(corpus_match.get("flyer_key") or ""),
        "scan": str(corpus_match.get("scan") or ""),
        "source_pdf_sha256": _sha256(
            corpus_match.get("source_pdf_sha256"), "source_pdf_sha256"
        ),
        "stable_source_identity_sha256": _sha256(
            corpus_match.get("stable_source_identity_sha256"),
            "stable_source_identity_sha256",
        ),
        "parser_input_identity_sha256": _sha256(
            corpus_match.get("parser_input_identity_sha256"),
            "parser_input_identity_sha256",
        ),
        "parser_version": str(one_shot.get("parser_version") or ""),
        "parser_sha256": _sha256(one_shot.get("parser_sha256"), "parser_sha256"),
        "review_profile": dict(review_profile),
    }
    for key in ("target", "flyer_key", "scan", "parser_version"):
        if not identity[key]:
            raise LidlWeeklyTrustStateError(f"one-shot identity field is missing: {key}")
    return canonical_digest(identity)


def _validate_controller(
    controller: Mapping[str, Any],
    one_shot: Mapping[str, Any],
) -> str:
    if controller.get("schema_version") != 1:
        raise LidlWeeklyTrustStateError("controller schema mismatch")
    if controller.get("controller_version") != CONTROLLER_VERSION:
        raise LidlWeeklyTrustStateError("controller version mismatch")
    if controller.get("result") not in {"READY", "NO_OP"}:
        raise LidlWeeklyTrustStateError("controller is not a completed shadow decision")
    expected_safety = {
        "dry_run": True,
        "corpus_write_authorized": False,
        "database_write_authorized": False,
        "review_write_authorized": False,
        "production_publish_authorized": False,
        "systemd_change_authorized": False,
        "bounded_retry_authorized": False,
    }
    for key, value in expected_safety.items():
        if controller.get(key) is not value:
            raise LidlWeeklyTrustStateError(f"controller safety mismatch: {key}")

    fingerprint = _sha256(
        controller.get("execution_fingerprint"),
        "controller execution_fingerprint",
    )
    if fingerprint != _controller_fingerprint(one_shot):
        raise LidlWeeklyTrustStateError(
            "controller execution fingerprint does not match one-shot evidence"
        )
    if str(controller.get("target") or "") != str(one_shot.get("target") or ""):
        raise LidlWeeklyTrustStateError("controller/one-shot target mismatch")
    return fingerprint


def _parse_campaign(one_shot: Mapping[str, Any]) -> dict[str, Any]:
    source = one_shot.get("source")
    corpus_match = one_shot.get("corpus_match")
    if not isinstance(source, Mapping) or not isinstance(corpus_match, Mapping):
        raise LidlWeeklyTrustStateError("campaign evidence is missing")
    flyer_key = str(corpus_match.get("flyer_key") or "")
    if not flyer_key:
        raise LidlWeeklyTrustStateError("campaign flyer_key is missing")
    try:
        valid_from = date.fromisoformat(str(source.get("valid_from") or ""))
        valid_until = date.fromisoformat(str(source.get("valid_until") or ""))
    except ValueError as exc:
        raise LidlWeeklyTrustStateError("campaign validity is invalid") from exc
    if valid_from > valid_until:
        raise LidlWeeklyTrustStateError("campaign validity is reversed")
    if valid_from.isocalendar()[:2] != valid_until.isocalendar()[:2]:
        raise LidlWeeklyTrustStateError(
            "weekly campaign validity must stay within one ISO week"
        )
    iso = valid_from.isocalendar()
    week_start = valid_from - timedelta(days=valid_from.weekday())
    return {
        "flyer_key": flyer_key,
        "valid_from": valid_from.isoformat(),
        "valid_until": valid_until.isoformat(),
        "iso_week": f"{iso.year}-W{iso.week:02d}",
        "week_start": week_start.isoformat(),
        "source_pdf_sha256": _sha256(
            corpus_match.get("source_pdf_sha256"), "campaign source_pdf_sha256"
        ),
        "stable_source_identity_sha256": _sha256(
            corpus_match.get("stable_source_identity_sha256"),
            "campaign stable_source_identity_sha256",
        ),
        "parser_input_identity_sha256": _sha256(
            corpus_match.get("parser_input_identity_sha256"),
            "campaign parser_input_identity_sha256",
        ),
        "scan": str(corpus_match.get("scan") or ""),
    }


def _validate_semantic_dir(
    semantic_dir: Path,
    *,
    one_shot: Mapping[str, Any],
) -> dict[str, Any]:
    if semantic_dir.is_symlink() or not semantic_dir.is_dir():
        raise LidlWeeklyTrustStateError(
            f"semantic evidence must be a directory: {semantic_dir}"
        )
    coverage = load_json(semantic_dir / "coverage-report.json")
    binding = load_json(semantic_dir / "profile-binding.json")
    manifest_sha256 = sha_file(semantic_dir / "manifest.json")

    if coverage.get("view_version") != SEMANTIC_VIEW_VERSION:
        raise LidlWeeklyTrustStateError("semantic view version mismatch")
    if coverage.get("unexplained_count") != 0:
        raise LidlWeeklyTrustStateError("semantic view has unexplained rows")
    expected_safety = {
        "database_write": False,
        "review_seed": False,
        "auto_approve": False,
        "auto_publish": False,
        "production_deploy": False,
    }
    for key, value in expected_safety.items():
        if coverage.get(key) is not value:
            raise LidlWeeklyTrustStateError(f"semantic safety mismatch: {key}")

    corpus_match = one_shot["corpus_match"]
    expected = {
        "flyer_key": str(corpus_match.get("flyer_key") or ""),
        "scan": str(corpus_match.get("scan") or ""),
        "parser_version": str(one_shot.get("parser_version") or ""),
        "parser_sha256": _sha256(one_shot.get("parser_sha256"), "parser_sha256"),
        "source_pdf_sha256": _sha256(
            corpus_match.get("source_pdf_sha256"), "source_pdf_sha256"
        ),
    }
    for key, value in expected.items():
        if str(coverage.get(key) or "") != value:
            raise LidlWeeklyTrustStateError(f"semantic coverage mismatch: {key}")
        if str(binding.get(key) or "") != value:
            raise LidlWeeklyTrustStateError(f"semantic binding mismatch: {key}")
    if binding.get("schema_version") != 1:
        raise LidlWeeklyTrustStateError("semantic binding schema mismatch")
    if binding.get("view_version") != SEMANTIC_VIEW_VERSION:
        raise LidlWeeklyTrustStateError("semantic binding view version mismatch")
    for key in (
        "review_profile_sha256",
        "scan_summary_sha256",
        "scan_rows_sha256",
    ):
        coverage_sha = _sha256(coverage.get(key), f"semantic coverage {key}")
        if _sha256(binding.get(key), f"semantic binding {key}") != coverage_sha:
            raise LidlWeeklyTrustStateError(f"semantic binding mismatch: {key}")
    return {
        "manifest_sha256": manifest_sha256,
        "review_profile_sha256": str(binding["review_profile_sha256"]),
        "scan_summary_sha256": str(binding["scan_summary_sha256"]),
        "scan_rows_sha256": str(binding["scan_rows_sha256"]),
        "production_ready_count": int(coverage.get("production_ready_count") or 0),
        "review_required_count": int(coverage.get("review_required_count") or 0),
        "excluded_count": int(coverage.get("excluded_count") or 0),
        "unexplained_count": 0,
    }


def build_cycle_evidence(
    controller: Mapping[str, Any],
    one_shot: Mapping[str, Any],
    *,
    semantic_dir: Path,
) -> dict[str, Any]:
    execution_fingerprint = _validate_controller(controller, one_shot)
    campaign = _parse_campaign(one_shot)
    semantic = _validate_semantic_dir(semantic_dir, one_shot=one_shot)
    identity = {
        "campaign": campaign,
        "execution_fingerprint": execution_fingerprint,
        "semantic": semantic,
    }
    return {
        "schema_version": 1,
        "strategy": "lidl_weekly_shadow_cycle_evidence_v1",
        "controller_result": str(controller["result"]),
        "campaign": campaign,
        "execution_fingerprint": execution_fingerprint,
        "semantic": semantic,
        "cycle_identity_sha256": canonical_digest(identity),
        "production_write_authorized": False,
        "database_write_performed": False,
        "review_write_performed": False,
        "publication_performed": False,
        "deployment_performed": False,
        "systemd_change_performed": False,
    }


def validate_previous(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise LidlWeeklyTrustStateError("previous state schema mismatch")
    if payload.get("strategy") != STRATEGY:
        raise LidlWeeklyTrustStateError("previous state strategy mismatch")
    if payload.get("production_write_authorized") is not False:
        raise LidlWeeklyTrustStateError("previous state contains write authority")
    raw_records = payload.get("scheduled_cycles")
    if not isinstance(raw_records, list) or len(raw_records) > MAX_RECORDS:
        raise LidlWeeklyTrustStateError("previous scheduled cycle history is invalid")
    seen_weeks: set[str] = set()
    records: list[dict[str, Any]] = []
    for raw in raw_records:
        if not isinstance(raw, Mapping):
            raise LidlWeeklyTrustStateError("scheduled cycle must be an object")
        record = dict(raw)
        week = str(record.get("iso_week") or "")
        if not re.fullmatch(r"\d{4}-W\d{2}", week):
            raise LidlWeeklyTrustStateError("scheduled cycle ISO week is invalid")
        if week in seen_weeks:
            raise LidlWeeklyTrustStateError("duplicate scheduled ISO week")
        seen_weeks.add(week)
        _sha256(record.get("cycle_identity_sha256"), "scheduled cycle identity")
        if record.get("trigger_event") != "schedule":
            raise LidlWeeklyTrustStateError(
                "persisted cycle must come from schedule"
            )
        if record.get("production_write_authorized") is not False:
            raise LidlWeeklyTrustStateError(
                "persisted cycle contains write authority"
            )
        date.fromisoformat(str(record.get("week_start") or ""))
        datetime.fromisoformat(
            str(record.get("recorded_at") or "").replace("Z", "+00:00")
        )
        records.append(record)
    return records


def consecutive_chain_length(records: list[Mapping[str, Any]]) -> int:
    ordered = sorted(records, key=lambda row: str(row["week_start"]))
    best = current = 0
    previous_start: date | None = None
    for row in ordered:
        start = date.fromisoformat(str(row["week_start"]))
        current = (
            current + 1
            if previous_start is not None and (start - previous_start).days == 7
            else 1
        )
        best = max(best, current)
        previous_start = start
    return best


def build_state(
    cycle: Mapping[str, Any],
    *,
    observed_at: datetime,
    trigger_event: str,
    previous: Mapping[str, Any] | None,
    previous_state_sha256: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if trigger_event not in {"schedule", "workflow_dispatch"}:
        raise LidlWeeklyTrustStateError("unsupported trigger event")
    if observed_at.tzinfo is None:
        raise LidlWeeklyTrustStateError("observed_at must be timezone-aware")
    if cycle.get("strategy") != "lidl_weekly_shadow_cycle_evidence_v1":
        raise LidlWeeklyTrustStateError("cycle evidence strategy mismatch")
    if cycle.get("schema_version") != 1:
        raise LidlWeeklyTrustStateError("cycle evidence schema mismatch")
    for key in (
        "production_write_authorized",
        "database_write_performed",
        "review_write_performed",
        "publication_performed",
        "deployment_performed",
        "systemd_change_performed",
    ):
        if cycle.get(key) is not False:
            raise LidlWeeklyTrustStateError(f"cycle safety mismatch: {key}")
    cycle_identity = _sha256(
        cycle.get("cycle_identity_sha256"), "cycle identity"
    )
    campaign = cycle.get("campaign")
    if not isinstance(campaign, Mapping):
        raise LidlWeeklyTrustStateError("cycle campaign is missing")
    week = str(campaign.get("iso_week") or "")
    week_start = str(campaign.get("week_start") or "")
    date.fromisoformat(week_start)

    records = validate_previous(previous) if previous is not None else []
    same_week = next((row for row in records if row["iso_week"] == week), None)
    if same_week is not None and same_week["cycle_identity_sha256"] != cycle_identity:
        raise LidlWeeklyTrustStateError(
            "same ISO week has conflicting completed cycle identity"
        )
    duplicate = same_week is not None
    recorded = trigger_event == "schedule" and not duplicate
    if recorded:
        records.append(
            {
                "iso_week": week,
                "week_start": week_start,
                "flyer_key": str(campaign.get("flyer_key") or ""),
                "valid_from": str(campaign.get("valid_from") or ""),
                "valid_until": str(campaign.get("valid_until") or ""),
                "execution_fingerprint": str(
                    cycle.get("execution_fingerprint") or ""
                ),
                "semantic_manifest_sha256": str(
                    (cycle.get("semantic") or {}).get("manifest_sha256") or ""
                ),
                "cycle_identity_sha256": cycle_identity,
                "controller_result": str(cycle.get("controller_result") or ""),
                "recorded_at": observed_at.astimezone(timezone.utc).isoformat(),
                "trigger_event": "schedule",
                "production_write_authorized": False,
            }
        )
        records = records[-MAX_RECORDS:]

    consecutive = consecutive_chain_length(records)
    semantic_no_op = (
        str(cycle.get("controller_result") or "") == "NO_OP"
        and duplicate
    )
    observation = (
        "RECORDED_UNATTENDED_CYCLE"
        if recorded
        else "MANUAL_CANARY_NOT_COUNTED"
        if trigger_event == "workflow_dispatch"
        else "UNCHANGED_SEMANTIC_NO_OP"
        if semantic_no_op
        else "DUPLICATE_WEEK_NOT_COUNTED"
    )
    state = {
        "schema_version": SCHEMA_VERSION,
        "strategy": STRATEGY,
        "generated_at": observed_at.astimezone(timezone.utc).isoformat(),
        "trigger_event": trigger_event,
        "previous_state_sha256": previous_state_sha256,
        "current_iso_week": week,
        "current_cycle_identity_sha256": cycle_identity,
        "current_controller_result": str(cycle.get("controller_result") or ""),
        "observation": observation,
        "semantic_no_op": semantic_no_op,
        "transition_recorded": recorded,
        "scheduled_cycles": records,
        "consecutive_unattended_weekly_cycle_count": consecutive,
        "issue_24_two_consecutive_unattended_weekly_cycles_ready": consecutive >= 2,
        "production_write_authorized": False,
        "database_write_performed": False,
        "review_write_performed": False,
        "publication_performed": False,
        "deployment_performed": False,
        "systemd_change_performed": False,
    }
    receipt = {
        "schema_version": 1,
        "strategy": RECEIPT_STRATEGY,
        "state_sha256": canonical_digest(state),
        "previous_state_sha256": previous_state_sha256,
        "current_iso_week": week,
        "current_cycle_identity_sha256": cycle_identity,
        "observation": observation,
        "transition_recorded": recorded,
        "consecutive_unattended_weekly_cycle_count": consecutive,
        "issue_24_two_consecutive_unattended_weekly_cycles_ready": consecutive >= 2,
        "production_write_authorized": False,
    }
    return state, receipt


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build read-only Lidl weekly trust-state evidence from an existing "
            "Gate A controller decision plus exact semantic-view evidence."
        )
    )
    parser.add_argument("--controller-manifest", type=Path, required=True)
    parser.add_argument("--one-shot-status", type=Path, required=True)
    parser.add_argument("--semantic-dir", type=Path, required=True)
    parser.add_argument("--previous-state", type=Path)
    parser.add_argument(
        "--trigger-event",
        choices=("schedule", "workflow_dispatch"),
        required=True,
    )
    parser.add_argument("--observed-at", type=datetime.fromisoformat, required=True)
    parser.add_argument("--state-output", type=Path, required=True)
    parser.add_argument("--receipt-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        previous = load_json(args.previous_state) if args.previous_state else None
        previous_sha = sha_file(args.previous_state) if args.previous_state else None
        cycle = build_cycle_evidence(
            load_json(args.controller_manifest),
            load_json(args.one_shot_status),
            semantic_dir=args.semantic_dir,
        )
        state, receipt = build_state(
            cycle,
            observed_at=args.observed_at,
            trigger_event=args.trigger_event,
            previous=previous,
            previous_state_sha256=previous_sha,
        )
        state_sha = write_create_only(args.state_output, state)
        if state_sha != receipt["state_sha256"]:
            raise LidlWeeklyTrustStateError("state file SHA differs from receipt")
        write_create_only(args.receipt_output, receipt)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR|{exc}", file=sys.stderr)
        return 2
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
