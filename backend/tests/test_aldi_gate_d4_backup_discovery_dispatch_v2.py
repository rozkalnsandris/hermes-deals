from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "runner" / "aldi_gate_d4_backup_discovery_dispatch.py"

NEXT_STEPS = {
    "NO_CANDIDATE_IN_DESIGNATED_ROOTS": "authorize_additional_explicit_backup_inputs_or_mark_source_set_complete",
    "READY_FOR_IRRECOVERABLE_DECISION": "record_separate_owner_reviewed_irrecoverable_decision",
    "PLAUSIBLE_RECOVERY_CANDIDATE_FOUND": "bind_candidate_to_independent_historical_provenance",
    "AMBIGUOUS_PLAUSIBLE_RECOVERY_CANDIDATES": "bind_and_resolve_distinct_historical_identities",
}
SAFETY_FALSE_FIELDS = {
    "raw_page_bytes_exported",
    "network_acquisition_authorized",
    "archive_extraction_authorized",
    "source_or_corpus_mutation_authorized",
    "manifest_regeneration_authorized",
    "parser_execution_authorized",
    "candidate_creation_authorized",
    "review_or_publication_write_authorized",
    "production_database_write_authorized",
    "production_deployment_authorized",
    "scheduler_systemd_canary_authorized",
    "destructive_cleanup_authorized",
    "newer_41_plus_41_substitution_authorized",
}


def load_module():
    spec = importlib.util.spec_from_file_location("aldi_gate_d4_backup_discovery_dispatch_v2_tested", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fingerprint(module, payload: dict) -> None:
    payload.pop("diagnostic_fingerprint", None)
    payload["diagnostic_fingerprint"] = hashlib.sha256(module.canonical_bytes(payload)).hexdigest()


def result_payload(
    module,
    *,
    request_schema: int = 1,
    root_count: int = 1,
    file_count: int = 0,
    identities: int = 0,
    authoritative_complete: bool = False,
) -> dict:
    assert root_count + file_count > 0
    complete_identities = [f"{index + 1:064x}" for index in range(identities)]
    source_rows = []
    for index, identity in enumerate(complete_identities):
        if file_count:
            source_rows.append(
                {
                    "input_id": "backup-file",
                    "input_kind": "file",
                    "kind": "archive",
                    "source": "candidate.tar.gz",
                    "identity_sha256": identity,
                    "provenance_status": "unbound_requires_gate_d4_binding",
                    "file_id": "backup-file",
                }
            )
        else:
            source_rows.append(
                {
                    "input_id": "backup-root",
                    "input_kind": "root",
                    "kind": "directory",
                    "source": f"candidate-{index}",
                    "identity_sha256": identity,
                    "provenance_status": "unbound_requires_gate_d4_binding",
                    "root_id": "backup-root",
                }
            )

    if identities > 1:
        decision = "AMBIGUOUS_PLAUSIBLE_RECOVERY_CANDIDATES"
    elif identities == 1:
        decision = "PLAUSIBLE_RECOVERY_CANDIDATE_FOUND"
    elif authoritative_complete:
        decision = "READY_FOR_IRRECOVERABLE_DECISION"
    else:
        decision = "NO_CANDIDATE_IN_DESIGNATED_ROOTS"

    safety = {field: False for field in SAFETY_FALSE_FIELDS}
    safety.update(
        {
            "explicit_inputs_only": True,
            "explicit_roots_only": file_count == 0,
            "exact_file_allowlist_enabled": file_count > 0,
            "strict_49_plus_41_frozen_contract_unchanged": True,
        }
    )
    payload = {
        "schema_version": 1,
        "mode": "ALDI_GATE_D4_BOUNDED_BACKUP_DISCOVERY",
        "issue_number": 631,
        "request_schema_version": request_schema,
        "decision": decision,
        "authoritative_source_set_complete": authoritative_complete,
        "designated_root_count": root_count,
        "designated_file_count": file_count,
        "designated_input_count": root_count + file_count,
        "complete_recovery_source_count": len(source_rows),
        "distinct_complete_identity_count": len(complete_identities),
        "root_reports": [{"root_id": f"root-{index}"} for index in range(root_count)],
        "file_reports": [
            {"file_id": f"file-{index}", "archive": {"path": "candidate.tar.gz"}}
            for index in range(file_count)
        ],
        "plausible_recovery_sources": source_rows,
        "complete_identities": complete_identities,
        "provenance_binding_complete": False,
        "historical_recovery_authorized": False,
        "irrecoverable_decision_recorded": False,
        "next_step": NEXT_STEPS[decision],
        "safety": safety,
    }
    fingerprint(module, payload)
    return payload


def test_v1_root_only_result_remains_accepted() -> None:
    module = load_module()
    module.validate_result(result_payload(module, request_schema=1, root_count=2))


def test_v2_root_only_result_is_accepted_without_exact_file_capability() -> None:
    module = load_module()
    payload = result_payload(module, request_schema=2, root_count=2)
    module.validate_result(payload)
    assert payload["safety"]["explicit_roots_only"] is True
    assert payload["safety"]["exact_file_allowlist_enabled"] is False


def test_v2_exact_file_only_result_is_accepted() -> None:
    module = load_module()
    payload = result_payload(module, request_schema=2, root_count=0, file_count=1)
    module.validate_result(payload)
    assert payload["safety"]["explicit_inputs_only"] is True
    assert payload["safety"]["explicit_roots_only"] is False
    assert payload["safety"]["exact_file_allowlist_enabled"] is True


def test_v2_mixed_candidate_result_is_accepted() -> None:
    module = load_module()
    module.validate_result(
        result_payload(module, request_schema=2, root_count=1, file_count=1, identities=1)
    )


def test_v1_result_cannot_claim_exact_file_inputs() -> None:
    module = load_module()
    payload = result_payload(module, request_schema=1, root_count=0, file_count=1)
    with pytest.raises(module.DispatchError, match="v1 result cannot contain exact-file inputs"):
        module.validate_result(payload)


def test_v2_exact_file_safety_must_match_file_count() -> None:
    module = load_module()
    payload = result_payload(module, request_schema=2, root_count=0, file_count=1)
    payload["safety"]["explicit_roots_only"] = True
    fingerprint(module, payload)
    with pytest.raises(module.DispatchError, match="explicit-roots safety mismatch"):
        module.validate_result(payload)

    payload = result_payload(module, request_schema=2, root_count=0, file_count=1)
    payload["safety"]["exact_file_allowlist_enabled"] = False
    fingerprint(module, payload)
    with pytest.raises(module.DispatchError, match="exact-file safety mismatch"):
        module.validate_result(payload)


def test_result_rejects_unknown_safety_or_top_level_fields() -> None:
    module = load_module()
    payload = result_payload(module)
    payload["safety"]["future_capability"] = False
    fingerprint(module, payload)
    with pytest.raises(module.DispatchError, match="result safety schema mismatch"):
        module.validate_result(payload)

    payload = result_payload(module)
    payload["unexpected"] = False
    fingerprint(module, payload)
    with pytest.raises(module.DispatchError, match="result field set mismatch"):
        module.validate_result(payload)


def test_decision_and_next_step_are_derived_from_identity_counts() -> None:
    module = load_module()
    payload = result_payload(module, request_schema=2, root_count=0, file_count=1)
    payload["decision"] = "PLAUSIBLE_RECOVERY_CANDIDATE_FOUND"
    payload["next_step"] = NEXT_STEPS[payload["decision"]]
    fingerprint(module, payload)
    with pytest.raises(module.DispatchError, match="decision/count semantics mismatch"):
        module.validate_result(payload)

    payload = result_payload(module, request_schema=2, root_count=0, file_count=1, identities=1)
    payload["next_step"] = NEXT_STEPS["NO_CANDIDATE_IN_DESIGNATED_ROOTS"]
    fingerprint(module, payload)
    with pytest.raises(module.DispatchError, match="next-step semantics mismatch"):
        module.validate_result(payload)


def test_recovery_source_identities_must_equal_complete_identity_set() -> None:
    module = load_module()
    payload = result_payload(module, request_schema=2, root_count=0, file_count=1, identities=1)
    payload["plausible_recovery_sources"][0]["identity_sha256"] = "f" * 64
    fingerprint(module, payload)
    with pytest.raises(module.DispatchError, match="recovery source identities mismatch"):
        module.validate_result(payload)


def test_counts_reject_booleans_and_inconsistent_input_totals() -> None:
    module = load_module()
    payload = result_payload(module)
    payload["designated_root_count"] = True
    fingerprint(module, payload)
    with pytest.raises(module.DispatchError, match="designated_root_count invalid"):
        module.validate_result(payload)

    payload = result_payload(module, request_schema=2, root_count=1, file_count=1)
    payload["designated_input_count"] = 1
    fingerprint(module, payload)
    with pytest.raises(module.DispatchError, match="designated input count mismatch"):
        module.validate_result(payload)


def test_legacy_pre_644_result_shape_fails_closed() -> None:
    module = load_module()
    payload = result_payload(module)
    for field in (
        "request_schema_version",
        "authoritative_source_set_complete",
        "designated_file_count",
        "designated_input_count",
        "file_reports",
        "complete_identities",
        "next_step",
    ):
        payload.pop(field)
    payload["safety"].pop("explicit_inputs_only")
    payload["safety"].pop("exact_file_allowlist_enabled")
    fingerprint(module, payload)
    with pytest.raises(module.DispatchError, match="result field set mismatch"):
        module.validate_result(payload)


def test_test_fixture_contains_no_absolute_backup_paths() -> None:
    module = load_module()
    encoded = json.dumps(result_payload(module, request_schema=2, root_count=0, file_count=1))
    assert "/home/andris" not in encoded
    assert "/opt/backups" not in encoded
