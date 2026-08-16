#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import aldi_new_immutable_baseline_gate as gate_a_module
import aldi_new_baseline_page_card_parity as gate_b_module
import aldi_new_baseline_gate_c_replay as gate_c_module
import aldi_new_baseline_two_cycle_shadow_gate as two_cycle_module

MODE = "ALDI_NEW_BASELINE_WEEKLY_SHADOW_BRIDGE_V01"
REQUEST_MODE = "ALDI_NEW_BASELINE_WEEKLY_SHADOW_REQUEST_V01"
ISSUE_NUMBER = 682
OWNER_LOGIN = "rozkalnsandris"
OWNER_ID = 277435981
FIRST_WEEK_DECISION = "WEEKLY_SHADOW_EVIDENCE_ACCEPTED"
TWO_WEEK_READY_DECISION = two_cycle_module.READY_DECISION
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{3,159}$")
ISO_WEEK_RE = re.compile(r"^(\d{4})-W(\d{2})$")
FIXED_FILES = {
    "gate_a_input": "gate-a-input.json",
    "gate_b_input": "gate-b-input.json",
    "gate_c_input": "gate-c-input.json",
    "execution_evidence": "execution-evidence.json",
}
OPTIONAL_FILES = {
    "prior_cycle": "prior-cycle.json",
    "observability_proofs": "observability-proofs.json",
}


class BridgeError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise BridgeError(message)


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def canonical_sha256(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    require(isinstance(value, Mapping), f"{label} must be an object")
    return value


def _nonempty(value: Any, label: str) -> str:
    text = str(value or "").strip()
    require(bool(text), f"{label} must be non-empty")
    return text


def _sha(value: Any, label: str) -> str:
    text = str(value or "")
    require(bool(SHA256_RE.fullmatch(text)), f"{label} must be lowercase SHA256")
    return text


def _commit(value: Any, label: str) -> str:
    text = str(value or "")
    require(bool(COMMIT_RE.fullmatch(text)), f"{label} must be a 40-char commit SHA")
    return text


def _strict_int(value: Any, label: str, *, minimum: int = 0) -> int:
    require(not isinstance(value, bool) and isinstance(value, int), f"{label} must be an integer")
    require(value >= minimum, f"{label} must be >= {minimum}")
    return value


def _utc(value: Any, label: str) -> str:
    text = _nonempty(value, label)
    require(text.endswith("Z"), f"{label} must end with Z")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise BridgeError(f"{label} must be RFC3339 UTC") from exc
    require(parsed.tzinfo == timezone.utc, f"{label} must be UTC")
    return parsed.isoformat().replace("+00:00", "Z")


def _iso_week(value: Any, label: str) -> str:
    text = _nonempty(value, label)
    match = ISO_WEEK_RE.fullmatch(text)
    require(bool(match), f"{label} must use YYYY-Www")
    try:
        date.fromisocalendar(int(match.group(1)), int(match.group(2)), 1)
    except ValueError as exc:
        raise BridgeError(f"{label} is invalid") from exc
    return text


def load_json(path: Path, label: str) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"{label} is missing or unsafe: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BridgeError(f"invalid {label}: {exc}") from exc
    require(isinstance(value, dict), f"{label} must contain one JSON object")
    return value


def validate_descriptor(request_dir: Path, raw_value: Any, *, key: str, expected_name: str) -> tuple[Path, str]:
    raw = _mapping(raw_value, f"files.{key}")
    require(raw.get("path") == expected_name, f"files.{key}.path must be {expected_name}")
    expected_sha = _sha(raw.get("sha256"), f"files.{key}.sha256")
    path = request_dir / expected_name
    require(path.is_file() and not path.is_symlink(), f"{expected_name} is missing or unsafe")
    actual_sha = file_sha256(path)
    require(actual_sha == expected_sha, f"{expected_name} SHA256 mismatch")
    return path, actual_sha


def validate_request(
    request_dir: Path,
    *,
    request_sha256: str,
    expected_main_sha: str,
    authorization_comment_id: int,
    github_run_id: int,
) -> tuple[dict[str, Any], dict[str, tuple[Path, str]]]:
    request_sha256 = _sha(request_sha256, "request_sha256")
    expected_main_sha = _commit(expected_main_sha, "expected_main_sha")
    _strict_int(authorization_comment_id, "authorization_comment_id", minimum=1)
    _strict_int(github_run_id, "github_run_id", minimum=1)
    request_path = request_dir / "request.json"
    request = load_json(request_path, "request")
    require(file_sha256(request_path) == request_sha256, "request SHA256 mismatch")
    expected = {
        "schema_version": 1,
        "mode": REQUEST_MODE,
        "issue_number": ISSUE_NUMBER,
        "retailer": "ALDI Nord",
        "owner_login": OWNER_LOGIN,
        "owner_id": OWNER_ID,
        "automatic_schedule": False,
        "production_deploy_authorized": False,
        "production_canary_authorized": False,
        "production_database_write_authorized": False,
        "review_or_publication_write_authorized": False,
        "source_mutation_authorized": False,
    }
    for key, value in expected.items():
        require(request.get(key) == value, f"request {key} mismatch")
    require(
        _commit(request.get("authorized_main_sha"), "request.authorized_main_sha") == expected_main_sha,
        "request main SHA drift",
    )
    files_raw = _mapping(request.get("files"), "files")
    allowed_file_keys = set(FIXED_FILES) | set(OPTIONAL_FILES)
    require(set(files_raw) <= allowed_file_keys, "request contains unsupported file descriptors")
    resolved = {
        key: validate_descriptor(request_dir, files_raw.get(key), key=key, expected_name=name)
        for key, name in FIXED_FILES.items()
    }
    for key, name in OPTIONAL_FILES.items():
        if key in files_raw:
            resolved[key] = validate_descriptor(request_dir, files_raw[key], key=key, expected_name=name)
    require(
        ("prior_cycle" in resolved) == ("observability_proofs" in resolved),
        "prior_cycle and observability_proofs must be supplied together for cycle-02 acceptance",
    )
    return request, resolved


def expected_gate_b_binding(gate_a: Mapping[str, Any]) -> dict[str, Any]:
    identity = _mapping(gate_a.get("baseline_identity"), "Gate A baseline_identity")
    manifest = _mapping(gate_a.get("page_manifest"), "Gate A page_manifest")
    return {
        "gate_a_mode": gate_a.get("mode"),
        "gate_a_decision": gate_a.get("decision"),
        "baseline_id": identity.get("baseline_id"),
        "baseline_fingerprint": gate_a.get("baseline_fingerprint"),
        "page_manifest_sha256": manifest.get("manifest_sha256"),
        "page_count": manifest.get("page_count"),
        "historical_issue_56_completion_claimed": False,
    }


def expected_gate_c_binding(gate_b: Mapping[str, Any]) -> dict[str, Any]:
    baseline = _mapping(gate_b.get("baseline"), "Gate B baseline")
    projection = _mapping(gate_b.get("candidate_projection"), "Gate B candidate_projection")
    ledger = _mapping(gate_b.get("card_ledger"), "Gate B card_ledger")
    summary = _mapping(gate_b.get("summary"), "Gate B summary")
    return {
        "mode": gate_b.get("mode"),
        "decision": gate_b.get("decision"),
        "baseline_id": baseline.get("baseline_id"),
        "baseline_fingerprint": baseline.get("baseline_fingerprint"),
        "parity_fingerprint": gate_b.get("parity_fingerprint"),
        "candidate_projection_sha256": projection.get("projection_sha256"),
        "card_ledger_sha256": ledger.get("ledger_sha256"),
        "candidate_count": summary.get("candidate_count"),
        "card_count": summary.get("card_count"),
        "unexplained_card_count": 0,
        "historical_issue_56_completion_claimed": False,
        "production_eligible": False,
    }


def validate_execution_evidence(raw_value: Any, *, gate_a: Mapping[str, Any], gate_b: Mapping[str, Any], github_run_id: int) -> dict[str, Any]:
    raw = _mapping(raw_value, "execution_evidence")
    require(raw.get("schema_version") == 1, "execution evidence schema mismatch")
    require(raw.get("evidence_class") == "real_weekly_shadow", "execution evidence class mismatch")
    require(raw.get("execution_origin") == "rpi5_shadow", "execution origin mismatch")
    require(raw.get("source_state") == "available", "source_state must be available")
    require(raw.get("immutable_evidence") is True, "immutable evidence must be true")
    require(raw.get("production_published") is False, "production_published must be false")
    require(raw.get("production_eligible") is False, "production_eligible must be false")
    require(raw.get("review_pending_count") == 0, "review_pending_count must be zero")
    for field in (
        "replay_new_candidate_count",
        "replay_duplicate_candidate_count",
        "immutable_payload_drift_count",
        "production_database_write_count",
        "review_write_count",
        "publication_write_count",
        "source_mutation_count",
    ):
        require(raw.get(field) == 0, f"{field} must be zero")
    before = _sha(raw.get("shadow_state_sha256_before_replay"), "shadow state before")
    after = _sha(raw.get("shadow_state_sha256_after_replay"), "shadow state after")
    require(before == after, "shadow state changed during exact replay")

    identity = _mapping(gate_a.get("baseline_identity"), "Gate A baseline_identity")
    campaign = _mapping(identity.get("campaign"), "Gate A campaign")
    campaign_id = _nonempty(campaign.get("campaign_id"), "campaign_id")
    require(bool(ID_RE.fullmatch(campaign_id)), "campaign_id has invalid format")
    valid_from = str(campaign.get("valid_from") or "")
    valid_to = str(campaign.get("valid_until") or "")
    try:
        start, end = date.fromisoformat(valid_from), date.fromisoformat(valid_to)
    except ValueError as exc:
        raise BridgeError("Gate A campaign dates are invalid") from exc
    iso_week = _iso_week(raw.get("iso_week"), "execution_evidence.iso_week")
    iso = start.isocalendar()
    require(iso_week == f"{iso.year}-W{iso.week:02d}", "execution ISO week differs from Gate A campaign")
    require((end - start).days <= 7, "real weekly cycle validity exceeds 8 days inclusive")

    source_id = _nonempty(raw.get("primary_source_id"), "primary_source_id")
    sources = identity.get("sources")
    require(isinstance(sources, list), "Gate A sources must be a list")
    matches = [row for row in sources if isinstance(row, Mapping) and row.get("source_id") == source_id]
    require(len(matches) == 1, "primary_source_id must match exactly one Gate A source")
    source = matches[0]
    try:
        source_url = two_cycle_module._official_source_url(source.get("url"), "current cycle source_url")
    except Exception as exc:
        raise BridgeError(f"current cycle source URL blocked: {exc}") from exc
    summary = _mapping(gate_b.get("summary"), "Gate B summary")
    require(summary.get("unexplained_card_count") == 0, "Gate B contains unexplained cards")
    _strict_int(summary.get("card_count"), "Gate B card_count", minimum=1)
    return {
        "run_id": github_run_id,
        "observed_at_utc": _utc(raw.get("observed_at_utc"), "observed_at_utc"),
        "iso_week": iso_week,
        "campaign_id": campaign_id,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "source_url": source_url,
        "source_sha256": source.get("sha256"),
        "review_pending_count": 0,
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


def build_cycle(*, gate_a: Mapping[str, Any], gate_b: Mapping[str, Any], gate_c: Mapping[str, Any], execution: Mapping[str, Any], request_sha256: str, input_hashes: Mapping[str, str], authorization_comment_id: int) -> dict[str, Any]:
    a_identity = _mapping(gate_a.get("baseline_identity"), "Gate A baseline identity")
    parser_identity = _mapping(a_identity.get("parser_identity"), "Gate A parser identity")
    manifest = _mapping(gate_a.get("page_manifest"), "Gate A page manifest")
    projection = _mapping(gate_b.get("candidate_projection"), "Gate B projection")
    ledger = _mapping(gate_b.get("card_ledger"), "Gate B ledger")
    summary = _mapping(gate_b.get("summary"), "Gate B summary")
    c_identity = _mapping(gate_c.get("identity"), "Gate C identity")
    evidence_identity = {
        "bridge_mode": MODE,
        "request_sha256": request_sha256,
        "authorization_comment_id": authorization_comment_id,
        "input_hashes": dict(sorted(input_hashes.items())),
        "gate_a_fingerprint": gate_a.get("baseline_fingerprint"),
        "gate_b_fingerprint": gate_b.get("parity_fingerprint"),
        "gate_c_replay_identity_sha256": gate_c.get("replay_identity_sha256"),
    }
    return {
        "cycle_id": "cycle-current",
        "evidence_class": "real_weekly_shadow",
        "execution_origin": "rpi5_shadow",
        "run_id": execution["run_id"],
        "observed_at_utc": execution["observed_at_utc"],
        "iso_week": execution["iso_week"],
        "campaign_id": execution["campaign_id"],
        "valid_from": execution["valid_from"],
        "valid_to": execution["valid_to"],
        "source_state": "available",
        "source_url": execution["source_url"],
        "source_sha256": execution["source_sha256"],
        "page_manifest_sha256": manifest.get("manifest_sha256"),
        "parser_identity_sha256": parser_identity.get("implementation_sha256"),
        "parity_contract_sha256": file_sha256(Path(gate_b_module.__file__)),
        "candidate_projection_sha256": projection.get("projection_sha256"),
        "card_ledger_sha256": ledger.get("ledger_sha256"),
        "semantic_output_sha256": c_identity.get("semantic_output_sha256"),
        "evidence_artifact_sha256": canonical_sha256(evidence_identity),
        "candidate_count": summary.get("candidate_count"),
        "card_count": summary.get("card_count"),
        "review_routed_count": summary.get("review_candidate_count"),
        "excluded_count": summary.get("excluded_card_count"),
        "review_pending_count": 0,
        "unexplained_card_count": 0,
        "replay_new_candidate_count": 0,
        "replay_duplicate_candidate_count": 0,
        "immutable_payload_drift_count": 0,
        "shadow_state_sha256_before_replay": execution["shadow_state_sha256_before_replay"],
        "shadow_state_sha256_after_replay": execution["shadow_state_sha256_after_replay"],
        "production_database_write_count": 0,
        "review_write_count": 0,
        "publication_write_count": 0,
        "source_mutation_count": 0,
        "immutable_evidence": True,
        "production_published": False,
        "production_eligible": False,
    }


def _cycle_for_two_cycle_gate(raw_value: Any, *, cycle_id: str) -> dict[str, Any]:
    raw = dict(_mapping(raw_value, cycle_id))
    require(raw.get("cycle_id") in {"cycle-current", cycle_id}, f"{cycle_id} identity mismatch")
    raw["cycle_id"] = cycle_id
    return raw


def validate_observability_input(raw_value: Any) -> list[dict[str, Any]]:
    raw = _mapping(raw_value, "observability evidence")
    require(raw.get("schema_version") == 1, "observability schema mismatch")
    rows = raw.get("observability_proofs")
    require(isinstance(rows, list), "observability_proofs must be a list")
    return [dict(_mapping(row, "observability row")) for row in rows]


def _call(label: str, function: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return function(*args, **kwargs)
    except Exception as exc:
        raise BridgeError(f"{label} blocked: {exc}") from exc


def run_bridge(*, request_dir: Path, request_sha256: str, expected_main_sha: str, authorization_comment_id: int, github_run_id: int) -> dict[str, Any]:
    _request, resolved = validate_request(
        request_dir,
        request_sha256=request_sha256,
        expected_main_sha=expected_main_sha,
        authorization_comment_id=authorization_comment_id,
        github_run_id=github_run_id,
    )
    loaded = {key: load_json(path, key) for key, (path, _digest) in resolved.items()}
    hashes = {key: digest for key, (_path, digest) in resolved.items()}
    gate_a = _call("Gate A", gate_a_module.validate_baseline, loaded["gate_a_input"])
    require(loaded["gate_b_input"].get("baseline") == expected_gate_b_binding(gate_a), "Gate B input is not exactly bound to this Gate A result")
    gate_b = _call("Gate B", gate_b_module.validate_parity, loaded["gate_b_input"])
    require(loaded["gate_c_input"].get("gate_b") == expected_gate_c_binding(gate_b), "Gate C input is not exactly bound to this Gate B result")
    gate_c = _call("Gate C", gate_c_module.build_result, loaded["gate_c_input"])
    require(gate_c.get("decision") == "READY_FOR_TWO_CONSECUTIVE_WEEKLY_SHADOW_CYCLES", "Gate C is not ready for real weekly shadow evidence")
    execution = validate_execution_evidence(loaded["execution_evidence"], gate_a=gate_a, gate_b=gate_b, github_run_id=github_run_id)
    current_cycle = build_cycle(
        gate_a=gate_a,
        gate_b=gate_b,
        gate_c=gate_c,
        execution=execution,
        request_sha256=request_sha256,
        input_hashes={key: hashes[key] for key in FIXED_FILES},
        authorization_comment_id=authorization_comment_id,
    )
    _call(
        "current weekly cycle contract",
        two_cycle_module.validate_cycle,
        _cycle_for_two_cycle_gate(current_cycle, cycle_id="cycle-01"),
        index=1,
    )

    two_cycle_result: dict[str, Any] | None = None
    decision = FIRST_WEEK_DECISION
    if "prior_cycle" in loaded:
        payload = {
            "schema_version": 1,
            "mode": two_cycle_module.MODE,
            "issue_number": ISSUE_NUMBER,
            "gate_c": gate_c,
            "cycles": [
                _cycle_for_two_cycle_gate(loaded["prior_cycle"], cycle_id="cycle-01"),
                _cycle_for_two_cycle_gate(current_cycle, cycle_id="cycle-02"),
            ],
            "observability_proofs": validate_observability_input(loaded["observability_proofs"]),
        }
        two_cycle_result = _call("two-cycle acceptance", two_cycle_module.build_result, payload)
        decision = two_cycle_result["decision"]

    result = {
        "schema_version": 1,
        "mode": MODE,
        "issue_number": ISSUE_NUMBER,
        "decision": decision,
        "request_sha256": request_sha256,
        "authorized_main_sha": expected_main_sha,
        "owner_authorization": {
            "login": OWNER_LOGIN,
            "id": OWNER_ID,
            "comment_id": authorization_comment_id,
            "github_run_id": github_run_id,
        },
        "gate_a": gate_a,
        "gate_b": gate_b,
        "gate_c": gate_c,
        "current_cycle": current_cycle,
        "two_cycle_result": two_cycle_result,
        "production_canary_plan_ready": bool(two_cycle_result and two_cycle_result.get("decision") == TWO_WEEK_READY_DECISION),
        "production_canary_authorized": False,
        "production_deploy_authorized": False,
        "production_database_write_authorized": False,
        "review_or_publication_write_authorized": False,
        "source_mutation_authorized": False,
        "automatic_schedule": False,
        "automatic_approval_or_publication": False,
        "historical_issue_56_completion_claimed": False,
    }
    result["result_fingerprint"] = canonical_sha256({
        "request_sha256": request_sha256,
        "decision": decision,
        "current_cycle": current_cycle,
        "two_cycle_acceptance_fingerprint": two_cycle_result.get("acceptance_fingerprint") if two_cycle_result else None,
    })
    return result


def write_outputs(output_dir: Path, result: Mapping[str, Any]) -> None:
    require(not output_dir.exists(), f"output directory already exists: {output_dir}")
    output_dir.mkdir(parents=True, mode=0o700)
    files = {
        "gate-a-result.json": result["gate_a"],
        "gate-b-result.json": result["gate_b"],
        "gate-c-result.json": result["gate_c"],
        "cycle-evidence.json": result["current_cycle"],
        "sanitized-result.json": result,
    }
    if result.get("two_cycle_result") is not None:
        files["two-cycle-result.json"] = result["two_cycle_result"]
    lines = []
    for name, value in files.items():
        path = output_dir / name
        path.write_bytes(canonical_bytes(value))
        lines.append(f"{file_sha256(path)}  {name}")
    (output_dir / "MANIFEST.sha256").write_text("\n".join(sorted(lines)) + "\n", encoding="utf-8")


def write_blocked_outputs(output_dir: Path, *, request_sha256: str, expected_main_sha: str, authorization_comment_id: int, github_run_id: int, reason: str) -> dict[str, Any]:
    require(not output_dir.exists(), f"output directory already exists: {output_dir}")
    output_dir.mkdir(parents=True, mode=0o700)
    result = {
        "schema_version": 1,
        "mode": MODE,
        "issue_number": ISSUE_NUMBER,
        "decision": "BLOCKED",
        "request_sha256": request_sha256 if SHA256_RE.fullmatch(request_sha256) else None,
        "authorized_main_sha": expected_main_sha if COMMIT_RE.fullmatch(expected_main_sha) else None,
        "owner_authorization": {
            "login": OWNER_LOGIN,
            "id": OWNER_ID,
            "comment_id": authorization_comment_id if authorization_comment_id > 0 else None,
            "github_run_id": github_run_id if github_run_id > 0 else None,
        },
        "reason_code": "bridge_validation_failed",
        "reason_sha256": sha256(reason.encode("utf-8", errors="replace")).hexdigest(),
        "production_canary_plan_ready": False,
        "production_canary_authorized": False,
        "production_deploy_authorized": False,
        "production_database_write_authorized": False,
        "review_or_publication_write_authorized": False,
        "source_mutation_authorized": False,
        "automatic_schedule": False,
        "automatic_approval_or_publication": False,
        "historical_issue_56_completion_claimed": False,
    }
    path = output_dir / "sanitized-result.json"
    path.write_bytes(canonical_bytes(result))
    (output_dir / "MANIFEST.sha256").write_text(f"{file_sha256(path)}  sanitized-result.json\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate one owner-authorized ALDI real-week shadow evidence family.")
    parser.add_argument("--request-dir", type=Path, required=True)
    parser.add_argument("--request-sha256", required=True)
    parser.add_argument("--expected-main-sha", required=True)
    parser.add_argument("--authorization-comment-id", type=int, required=True)
    parser.add_argument("--github-run-id", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run_bridge(
            request_dir=args.request_dir,
            request_sha256=args.request_sha256,
            expected_main_sha=args.expected_main_sha,
            authorization_comment_id=args.authorization_comment_id,
            github_run_id=args.github_run_id,
        )
        write_outputs(args.output_dir, result)
    except BridgeError as exc:
        blocked = write_blocked_outputs(
            args.output_dir,
            request_sha256=args.request_sha256,
            expected_main_sha=args.expected_main_sha,
            authorization_comment_id=args.authorization_comment_id,
            github_run_id=args.github_run_id,
            reason=str(exc),
        )
        print("ALDI_NEW_BASELINE_WEEKLY_SHADOW_BRIDGE=BLOCKED")
        print(f"REASON_SHA256={blocked['reason_sha256']}")
        print("PRODUCTION_DATABASE_WRITE=false")
        print("REVIEW_PUBLICATION_WRITE=false")
        print("SOURCE_MUTATION=false")
        print("PRODUCTION_DEPLOY=false")
        print("AUTOMATIC_SCHEDULE=false")
        return 20
    print(f"ALDI_NEW_BASELINE_WEEKLY_SHADOW_BRIDGE={result['decision']}")
    print(f"RESULT_FINGERPRINT={result['result_fingerprint']}")
    print(f"PRODUCTION_CANARY_PLAN_READY={str(result['production_canary_plan_ready']).lower()}")
    print("PRODUCTION_CANARY_AUTHORIZED=false")
    print("PRODUCTION_DATABASE_WRITE=false")
    print("REVIEW_PUBLICATION_WRITE=false")
    print("SOURCE_MUTATION=false")
    print("PRODUCTION_DEPLOY=false")
    print("AUTOMATIC_SCHEDULE=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
