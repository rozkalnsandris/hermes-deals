#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Mapping
from urllib.parse import urlparse


MODE = "ALDI_NEW_BASELINE_TWO_CYCLE_SHADOW_GATE_V01"
ISSUE_NUMBER = 682
GATE_C_MODE = "ALDI_NEW_BASELINE_GATE_C_REPLAY_V01"
GATE_C_READY_DECISIONS = {
    "READY_FOR_TWO_CONSECUTIVE_WEEKLY_SHADOW_CYCLES",
    "NO_OP",
}
READY_DECISION = "READY_FOR_PRODUCTION_CANARY_PLAN"
NO_OP_DECISION = "NO_OP"
WAIT_DECISION = "WAIT_FOR_REQUIRED_SHADOW_EVIDENCE"
BLOCKED_DECISION = "BLOCKED"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{3,159}$")
ISO_WEEK_RE = re.compile(r"^(\d{4})-W(\d{2})$")
ALDI_HOSTS = {"aldi-nord.de", "www.aldi-nord.de", "prospekt.aldi-nord.de"}
REQUIRED_OBSERVABILITY = {
    "not_published_yet": "WAIT",
    "source_unavailable": "WAIT",
    "stale": "BLOCKED",
    "evidence_mismatch": "BLOCKED",
    "parser_failed": "BLOCKED",
    "review_pending": "WAIT",
}


class TwoCycleGateError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise TwoCycleGateError(message)


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


def canonical_sha256(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    require(isinstance(value, Mapping), f"{label} must be an object")
    return value


def _nonempty(value: Any, label: str) -> str:
    text = str(value or "").strip()
    require(bool(text), f"{label} must be non-empty")
    return text


def _sha256(value: Any, label: str) -> str:
    text = str(value or "")
    require(bool(SHA256_RE.fullmatch(text)), f"{label} must be lowercase SHA256")
    return text


def _strict_int(value: Any, label: str, *, minimum: int = 0) -> int:
    require(not isinstance(value, bool), f"{label} must be an integer")
    require(isinstance(value, int), f"{label} must be an integer")
    require(value >= minimum, f"{label} must be >= {minimum}")
    return value


def _iso_date(value: Any, label: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise TwoCycleGateError(f"{label} must be ISO date") from exc


def _utc_timestamp(value: Any, label: str) -> str:
    text = _nonempty(value, label)
    require(text.endswith("Z"), f"{label} must be UTC and end with Z")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise TwoCycleGateError(f"{label} must be RFC3339 UTC") from exc
    require(parsed.tzinfo == timezone.utc, f"{label} must be UTC")
    return parsed.isoformat().replace("+00:00", "Z")


def _official_source_url(value: Any, label: str) -> str:
    text = _nonempty(value, label)
    parsed = urlparse(text)
    require(
        parsed.scheme == "https" and parsed.hostname in ALDI_HOSTS,
        f"{label} must use an allowlisted official ALDI Nord HTTPS host",
    )
    require(
        not parsed.username and not parsed.password and not parsed.fragment,
        f"{label} contains forbidden identity or fragment",
    )
    return text


def _iso_week_start(value: Any, label: str) -> date:
    text = _nonempty(value, label)
    match = ISO_WEEK_RE.fullmatch(text)
    require(bool(match), f"{label} must use YYYY-Www")
    year = int(match.group(1))
    week = int(match.group(2))
    try:
        return date.fromisocalendar(year, week, 1)
    except ValueError as exc:
        raise TwoCycleGateError(f"{label} is not a valid ISO week") from exc


def safety_contract() -> dict[str, bool]:
    return {
        "contract_only": True,
        "network_acquisition_authorized": False,
        "parser_execution_authorized": False,
        "source_or_corpus_write_authorized": False,
        "candidate_creation_authorized": False,
        "review_write_authorized": False,
        "automatic_approval_authorized": False,
        "automatic_publication_authorized": False,
        "production_database_write_authorized": False,
        "production_deployment_authorized": False,
        "scheduler_or_retry_authorized": False,
        "production_canary_authorized": False,
        "production_canary_plan_preparation_authorized": False,
        "historical_corpus_reconstruction_authorized": False,
        "historical_completion_claimed": False,
        "newer_evidence_substitution_authorized": False,
        "weekly_shadow_cycle_execution_authorized": False,
    }


def validate_gate_c_binding(payload: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(payload.get("gate_c"), "gate_c")
    require(raw.get("schema_version") == 1, "Gate C schema mismatch")
    require(raw.get("mode") == GATE_C_MODE, "Gate C mode mismatch")
    require(raw.get("issue_number") == ISSUE_NUMBER, "Gate C issue binding mismatch")
    require(
        raw.get("decision") in GATE_C_READY_DECISIONS,
        "Gate C is not ready for weekly shadow cycles",
    )
    require(
        raw.get("deterministic_replay_verified") is True,
        "Gate C deterministic replay proof missing",
    )
    require(
        raw.get("duplicate_free_verified") is True,
        "Gate C duplicate-free proof missing",
    )
    require(
        raw.get("idempotency_verified") is True,
        "Gate C idempotency proof missing",
    )
    require(
        raw.get("second_replay_no_mutation_verified") is True,
        "Gate C no-mutation proof missing",
    )
    require(
        raw.get("historical_issue_56_completion_claimed") is False,
        "historical issue #56 completion must remain false",
    )
    require(
        raw.get("production_eligible") is False,
        "Gate C production eligibility must remain false",
    )
    require(
        raw.get("promotion_ready") is False,
        "Gate C promotion readiness must remain false",
    )
    require(
        raw.get("weekly_shadow_cycles_complete") is False,
        "Gate C must not pre-claim weekly shadow completion",
    )

    identity = _mapping(raw.get("identity"), "gate_c.identity")
    gate_b = _mapping(identity.get("gate_b"), "gate_c.identity.gate_b")
    baseline_id = _nonempty(gate_b.get("baseline_id"), "gate_c baseline_id")
    require(bool(ID_RE.fullmatch(baseline_id)), "Gate C baseline_id has invalid format")
    require(
        "a30" not in baseline_id
        and "a31" not in baseline_id
        and "49+41" not in baseline_id,
        "Gate C baseline_id must not reuse legacy A3.0/A3.1 identity",
    )

    return {
        "mode": GATE_C_MODE,
        "decision": raw["decision"],
        "replay_identity_sha256": _sha256(
            raw.get("replay_identity_sha256"),
            "gate_c.replay_identity_sha256",
        ),
        "baseline_id": baseline_id,
        "baseline_fingerprint": _sha256(
            gate_b.get("baseline_fingerprint"),
            "gate_c baseline_fingerprint",
        ),
        "historical_issue_56_completion_claimed": False,
        "production_eligible": False,
        "weekly_shadow_cycles_complete": False,
    }


def validate_cycle(raw_value: Any, *, index: int) -> dict[str, Any]:
    raw = _mapping(raw_value, f"cycle row {index}")
    cycle_id = _nonempty(raw.get("cycle_id"), f"cycle row {index} cycle_id")
    require(cycle_id == f"cycle-{index:02d}", "cycles must be ordered cycle-01 then cycle-02")
    require(raw.get("evidence_class") == "real_weekly_shadow", f"{cycle_id} evidence_class mismatch")
    require(raw.get("execution_origin") == "rpi5_shadow", f"{cycle_id} execution_origin mismatch")

    iso_week = _nonempty(raw.get("iso_week"), f"{cycle_id}.iso_week")
    week_start = _iso_week_start(iso_week, f"{cycle_id}.iso_week")
    valid_from = _iso_date(raw.get("valid_from"), f"{cycle_id}.valid_from")
    valid_to = _iso_date(raw.get("valid_to"), f"{cycle_id}.valid_to")
    require(valid_to >= valid_from, f"{cycle_id} validity window is reversed")
    require((valid_to - valid_from).days <= 7, f"{cycle_id} validity window exceeds 8 days inclusive")
    require(
        valid_from.isocalendar()[:2] == week_start.isocalendar()[:2],
        f"{cycle_id}.valid_from must fall in declared ISO week",
    )

    state = _nonempty(raw.get("source_state"), f"{cycle_id}.source_state")
    require(state == "available", f"{cycle_id} source_state must be available for a passing cycle")

    campaign_id = _nonempty(raw.get("campaign_id"), f"{cycle_id}.campaign_id")
    require(bool(ID_RE.fullmatch(campaign_id)), f"{cycle_id} campaign_id has invalid format")
    require(
        "a30" not in campaign_id and "a31" not in campaign_id and "49+41" not in campaign_id,
        f"{cycle_id} campaign_id must not reuse legacy identity",
    )

    candidate_count = _strict_int(raw.get("candidate_count"), f"{cycle_id}.candidate_count")
    card_count = _strict_int(raw.get("card_count"), f"{cycle_id}.card_count", minimum=1)
    review_routed_count = _strict_int(
        raw.get("review_routed_count"),
        f"{cycle_id}.review_routed_count",
    )
    excluded_count = _strict_int(raw.get("excluded_count"), f"{cycle_id}.excluded_count")
    review_pending_count = _strict_int(
        raw.get("review_pending_count"),
        f"{cycle_id}.review_pending_count",
    )
    require(review_pending_count == 0, f"{cycle_id} still has review-pending evidence")
    require(raw.get("unexplained_card_count") == 0, f"{cycle_id} has unexplained cards")
    require(raw.get("replay_new_candidate_count") == 0, f"{cycle_id} replay created new candidates")
    require(raw.get("replay_duplicate_candidate_count") == 0, f"{cycle_id} replay created duplicates")
    require(raw.get("immutable_payload_drift_count") == 0, f"{cycle_id} immutable payload drift detected")

    before = _sha256(
        raw.get("shadow_state_sha256_before_replay"),
        f"{cycle_id}.shadow_state_sha256_before_replay",
    )
    after = _sha256(
        raw.get("shadow_state_sha256_after_replay"),
        f"{cycle_id}.shadow_state_sha256_after_replay",
    )
    require(before == after, f"{cycle_id} shadow state changed during exact replay")

    production_db_write_count = _strict_int(
        raw.get("production_database_write_count"),
        f"{cycle_id}.production_database_write_count",
    )
    review_write_count = _strict_int(
        raw.get("review_write_count"),
        f"{cycle_id}.review_write_count",
    )
    publication_write_count = _strict_int(
        raw.get("publication_write_count"),
        f"{cycle_id}.publication_write_count",
    )
    source_mutation_count = _strict_int(
        raw.get("source_mutation_count"),
        f"{cycle_id}.source_mutation_count",
    )
    require(
        production_db_write_count
        + review_write_count
        + publication_write_count
        + source_mutation_count
        == 0,
        f"{cycle_id} crossed a forbidden write boundary",
    )
    require(raw.get("immutable_evidence") is True, f"{cycle_id} immutable evidence missing")
    require(raw.get("production_published") is False, f"{cycle_id} must remain unpublished")
    require(raw.get("production_eligible") is False, f"{cycle_id} must not claim production eligibility")

    normalized = {
        "cycle_id": cycle_id,
        "evidence_class": "real_weekly_shadow",
        "execution_origin": "rpi5_shadow",
        "run_id": _strict_int(raw.get("run_id"), f"{cycle_id}.run_id", minimum=1),
        "observed_at_utc": _utc_timestamp(raw.get("observed_at_utc"), f"{cycle_id}.observed_at_utc"),
        "iso_week": iso_week,
        "campaign_id": campaign_id,
        "valid_from": valid_from.isoformat(),
        "valid_to": valid_to.isoformat(),
        "source_state": "available",
        "source_url": _official_source_url(raw.get("source_url"), f"{cycle_id}.source_url"),
        "source_sha256": _sha256(raw.get("source_sha256"), f"{cycle_id}.source_sha256"),
        "page_manifest_sha256": _sha256(
            raw.get("page_manifest_sha256"),
            f"{cycle_id}.page_manifest_sha256",
        ),
        "parser_identity_sha256": _sha256(
            raw.get("parser_identity_sha256"),
            f"{cycle_id}.parser_identity_sha256",
        ),
        "parity_contract_sha256": _sha256(
            raw.get("parity_contract_sha256"),
            f"{cycle_id}.parity_contract_sha256",
        ),
        "candidate_projection_sha256": _sha256(
            raw.get("candidate_projection_sha256"),
            f"{cycle_id}.candidate_projection_sha256",
        ),
        "card_ledger_sha256": _sha256(
            raw.get("card_ledger_sha256"),
            f"{cycle_id}.card_ledger_sha256",
        ),
        "semantic_output_sha256": _sha256(
            raw.get("semantic_output_sha256"),
            f"{cycle_id}.semantic_output_sha256",
        ),
        "evidence_artifact_sha256": _sha256(
            raw.get("evidence_artifact_sha256"),
            f"{cycle_id}.evidence_artifact_sha256",
        ),
        "candidate_count": candidate_count,
        "card_count": card_count,
        "review_routed_count": review_routed_count,
        "excluded_count": excluded_count,
        "review_pending_count": 0,
        "unexplained_card_count": 0,
        "replay_new_candidate_count": 0,
        "replay_duplicate_candidate_count": 0,
        "immutable_payload_drift_count": 0,
        "shadow_state_sha256_before_replay": before,
        "shadow_state_sha256_after_replay": after,
        "production_database_write_count": 0,
        "review_write_count": 0,
        "publication_write_count": 0,
        "source_mutation_count": 0,
        "immutable_evidence": True,
        "production_published": False,
        "production_eligible": False,
    }
    normalized["cycle_fingerprint"] = canonical_sha256(normalized)
    return normalized


def validate_cycles(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("cycles")
    require(isinstance(rows, list), "cycles must be a list")
    require(len(rows) == 2, "exactly two real weekly shadow cycles are required")
    cycles = [validate_cycle(row, index=index) for index, row in enumerate(rows, start=1)]
    first, second = cycles

    first_week = _iso_week_start(first["iso_week"], "cycle-01.iso_week")
    second_week = _iso_week_start(second["iso_week"], "cycle-02.iso_week")
    require(
        (second_week - first_week).days == 7,
        "weekly shadow cycles must be consecutive ISO weeks",
    )
    require(first["campaign_id"] != second["campaign_id"], "weekly campaigns must be distinct")
    require(first["run_id"] != second["run_id"], "weekly shadow run IDs must be distinct")
    require(first["source_sha256"] != second["source_sha256"], "weekly source identities must be distinct")
    require(
        first["page_manifest_sha256"] != second["page_manifest_sha256"],
        "weekly page manifests must be distinct",
    )
    require(
        first["evidence_artifact_sha256"] != second["evidence_artifact_sha256"],
        "weekly evidence artifacts must be distinct",
    )
    require(
        first["parser_identity_sha256"] == second["parser_identity_sha256"],
        "parser implementation changed; restart the two-cycle acceptance window",
    )
    require(
        first["parity_contract_sha256"] == second["parity_contract_sha256"],
        "parity contract changed; restart the two-cycle acceptance window",
    )
    return cycles


def validate_observability(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("observability_proofs")
    require(isinstance(rows, list), "observability_proofs must be a list")
    require(
        len(rows) == len(REQUIRED_OBSERVABILITY),
        "all required source/review failure states need observability proof",
    )
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw_value in enumerate(rows, start=1):
        raw = _mapping(raw_value, f"observability row {index}")
        state = _nonempty(raw.get("state"), f"observability row {index} state")
        require(state in REQUIRED_OBSERVABILITY, f"unsupported observability state: {state}")
        require(state not in seen, f"duplicate observability state: {state}")
        seen.add(state)
        expected_decision = REQUIRED_OBSERVABILITY[state]
        require(
            raw.get("observed_decision") == expected_decision,
            f"{state} must be observed as {expected_decision}",
        )
        normalized.append(
            {
                "state": state,
                "observed_decision": expected_decision,
                "evidence_sha256": _sha256(
                    raw.get("evidence_sha256"),
                    f"{state}.evidence_sha256",
                ),
            }
        )
    require(seen == set(REQUIRED_OBSERVABILITY), "observability state set mismatch")
    normalized.sort(key=lambda row: row["state"])
    return normalized


def build_ready_result(payload: Mapping[str, Any]) -> dict[str, Any]:
    require(payload.get("schema_version") == 1, "unexpected two-cycle gate schema")
    require(payload.get("mode") == MODE, "unexpected two-cycle gate mode")
    require(payload.get("issue_number") == ISSUE_NUMBER, "issue binding mismatch")

    gate_c = validate_gate_c_binding(payload)
    cycles = validate_cycles(payload)
    observability = validate_observability(payload)

    identity = {
        "gate_c": gate_c,
        "cycles": cycles,
        "observability_proofs": observability,
        "parser_identity_sha256": cycles[0]["parser_identity_sha256"],
        "parity_contract_sha256": cycles[0]["parity_contract_sha256"],
    }
    acceptance_fingerprint = canonical_sha256(identity)

    return {
        "schema_version": 1,
        "mode": MODE,
        "issue_number": ISSUE_NUMBER,
        "decision": READY_DECISION,
        "identity": identity,
        "acceptance_fingerprint": acceptance_fingerprint,
        "two_consecutive_weekly_shadow_cycles_verified": True,
        "distinct_weekly_campaigns_verified": True,
        "immutable_provenance_verified": True,
        "replay_noop_verified": True,
        "duplicate_free_verified": True,
        "immutable_payload_no_drift_verified": True,
        "failure_state_observability_verified": True,
        "historical_issue_56_completion_claimed": False,
        "production_eligible": False,
        "promotion_ready": False,
        "production_canary_plan_ready": True,
        "production_canary_authorized": False,
        "next_gate": {
            "name": "bounded_production_canary_plan",
            "requires_exact_acceptance_fingerprint": acceptance_fingerprint,
            "plan_preparation_requires_separate_owner_authorization": True,
            "canary_application_requires_separate_owner_authorization": True,
            "production_deploy_requires_separate_owner_authorization": True,
        },
        "safety": safety_contract(),
    }


def validate_prior_result(
    prior: Mapping[str, Any],
    *,
    expected_ready: Mapping[str, Any],
) -> None:
    require(prior.get("schema_version") == 1, "prior two-cycle schema mismatch")
    require(prior.get("mode") == MODE, "prior two-cycle mode mismatch")
    require(prior.get("issue_number") == ISSUE_NUMBER, "prior two-cycle issue mismatch")
    require(
        prior.get("decision") in {READY_DECISION, NO_OP_DECISION},
        "prior two-cycle result is not complete",
    )
    require(
        prior.get("acceptance_fingerprint") == expected_ready["acceptance_fingerprint"],
        "prior two-cycle acceptance identity differs",
    )
    require(
        prior.get("two_consecutive_weekly_shadow_cycles_verified") is True,
        "prior two-cycle verification missing",
    )
    require(
        prior.get("failure_state_observability_verified") is True,
        "prior observability verification missing",
    )
    require(
        prior.get("historical_issue_56_completion_claimed") is False,
        "unsafe prior historical completion claim",
    )
    require(prior.get("production_eligible") is False, "unsafe prior production eligibility")
    require(prior.get("promotion_ready") is False, "unsafe prior promotion readiness")
    require(
        prior.get("production_canary_authorized") is False,
        "unsafe prior canary authorization",
    )
    require(prior.get("safety") == safety_contract(), "prior two-cycle safety mismatch")

    normalized = dict(prior)
    normalized["decision"] = READY_DECISION
    require(normalized == expected_ready, "prior two-cycle result bytes differ")


def build_result(
    payload: Mapping[str, Any],
    *,
    prior: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    ready = build_ready_result(payload)
    if prior is None:
        return ready
    validate_prior_result(prior, expected_ready=ready)
    result = dict(ready)
    result["decision"] = NO_OP_DECISION
    return result


def load_json(path: Path, label: str) -> dict[str, Any]:
    require(path.is_file(), f"{label} is missing: {path}")
    require(not path.is_symlink(), f"symlinked {label} forbidden: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TwoCycleGateError(f"invalid {label} JSON: {exc}") from exc
    require(isinstance(value, dict), f"{label} must contain one JSON object")
    return value


def write_create_only(path: Path, value: Mapping[str, Any]) -> None:
    require(not path.exists(), f"output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--prior", type=Path)
    args = parser.parse_args()

    payload = load_json(args.input, "two-cycle input")
    prior = load_json(args.prior, "prior two-cycle result") if args.prior else None
    result = build_result(payload, prior=prior)

    if args.output is None:
        print(canonical_bytes(result).decode("utf-8"), end="")
    else:
        write_create_only(args.output, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
