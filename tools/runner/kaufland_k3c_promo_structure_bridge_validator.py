from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

BRIDGE_SCHEMA_VERSION = 1
BRIDGE_CONTRACT_VERSION = "kaufland-k3c-promo-structure-rpi5-bridge-v1"
DIAGNOSTIC_SCHEMA_VERSION = 1
DIAGNOSTIC_CONTRACT_VERSION = "kaufland-k3c-promo-structure-diagnostic-v1"
PROJECTION_CONTRACT_VERSION = DIAGNOSTIC_CONTRACT_VERSION
PROMO_ROLE_POLICY = "BLOCKED_UNTIL_EXPLICIT_SOURCE_ROLE_EVIDENCE"
PARSER_BACKEND = "html.parser"
EXPECTED_BUNDLE_KEY = "kaufland/1503/k2/2026-08-13_2026-09_02"
EXPECTED_BUNDLE_IDENTITY = "afdd992c547165259e760e05f41687793c56abc0af9869c8aa70f39d6f41dbbf"
EXPECTED_ARTIFACT_COUNT = 6
EXPECTED_FAMILY_COUNT = 4
MAX_RAW_BYTES = 2 * 1024 * 1024
MAX_MARKER_SAMPLES = 12
MAX_CANDIDATE_SAMPLES_PER_MARKER = 12
MAX_SIGNATURES = 32
MAX_LOCATOR_LENGTH = 512

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_REASON_RE = re.compile(r"^[A-Z0-9_]{1,96}$")
_TAG_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9:-]{0,63}$")
_PRICE_CLASS_RE = re.compile(r"^k-price[A-Za-z0-9_-]{0,63}$")
_ALLOWED_RELATIONS = {
    "same_element",
    "candidate_descendant_of_marker_parent",
    "marker_parent_descendant_of_candidate",
    "siblings",
    "shared_ancestor",
}
_SAFETY_FIELDS = (
    "network_performed",
    "retained_evidence_write_performed",
    "runtime_executor_invoked",
    "parser_702_implemented",
    "production_database_write_performed",
    "review_write_performed",
    "publication_write_performed",
    "production_deploy_performed",
    "scheduler_change_performed",
    "systemd_change_performed",
    "host_mutation_performed",
)
_PASS_KEYS = {
    "schema_version",
    "contract_version",
    "status",
    "evidence_only",
    "promo_role_promoted",
    "k2_verifier",
    "target_fingerprint_before",
    "target_fingerprint_after",
    "target_fingerprint_unchanged",
    "second_derivation_deterministic",
    "projection",
    *_SAFETY_FIELDS,
    "result_identity_sha256",
}
_BLOCKED_KEYS = {
    "schema_version",
    "contract_version",
    "status",
    "reason_code",
    "evidence_only",
    "promo_role_promoted",
    *_SAFETY_FIELDS,
}
_PROJECTION_KEYS = {
    "schema_version",
    "contract_version",
    "parser_backend",
    "diagnostic_status",
    "promo_role_promoted",
    "promo_role_policy",
    "nur_marker_count",
    "card_local_nur_marker_count",
    "orphan_nur_marker_count",
    "public_amount_candidate_pair_count",
    "distinct_structure_signature_count",
    "structure_signature_samples",
    "structure_signatures_truncated",
    "marker_samples",
    "marker_samples_truncated",
    "orphan_marker_samples",
    "orphan_marker_samples_truncated",
    "projection_identity_sha256",
}
_MARKER_BASE_KEYS = {
    "marker",
    "marker_tag",
    "marker_locator",
    "marker_fragment_sha256",
    "marker_price_classes",
    "marker_amount_count",
}
_MARKER_KEYS = {
    *_MARKER_BASE_KEYS,
    "owner_card_locator",
    "owner_card_fragment_sha256",
    "public_amount_candidate_count",
    "public_amount_candidate_samples",
    "candidate_samples_truncated",
}
_CANDIDATE_KEYS = {
    "relation",
    "marker_parent_to_lca_steps",
    "candidate_to_lca_steps",
    "lca_tag",
    "lca_locator",
    "lca_price_classes",
    "candidate_tag",
    "candidate_locator",
    "candidate_fragment_sha256",
    "candidate_price_classes",
    "candidate_generic_price_tag_class_present",
    "candidate_amount_count",
    "candidate_xtra_class_present",
    "candidate_old_price_class_present",
}
_SIGNATURE_KEYS = {
    "signature_identity_sha256",
    "count",
    "relation",
    "marker_parent_to_lca_steps",
    "candidate_to_lca_steps",
    "candidate_tag",
    "candidate_price_classes",
    "candidate_generic_price_tag_class_present",
    "lca_tag",
    "lca_price_classes",
}


class BridgeValidationError(RuntimeError):
    pass


def _fail(message: str) -> None:
    raise BridgeValidationError(message)


def _sanitizer_failure_reason(exc: Exception) -> str:
    if not isinstance(exc, BridgeValidationError):
        return "SANITIZER_INPUT_READ_REJECTED"

    message = str(exc)
    if "price" in message:
        return "SANITIZER_PRICE_CLASS_REJECTED"
    if "locator" in message:
        return "SANITIZER_LOCATOR_REJECTED"
    if "identity" in message or "SHA-256" in message:
        return "SANITIZER_IDENTITY_REJECTED"
    if any(
        token in message
        for token in (
            "field set mismatch",
            "schema version mismatch",
            "contract version mismatch",
            "parser backend mismatch",
            "diagnostic status",
            "must be an object",
        )
    ):
        return "SANITIZER_SCHEMA_REJECTED"
    if any(
        token in message
        for token in (
            "bounded",
            "bound exceeded",
            "sample count",
            "truncation",
            "truncated",
            "exactly one",
        )
    ):
        return "SANITIZER_BOUND_REJECTED"
    return "SANITIZER_OUTPUT_REJECTED"


def _sanitizer_blocked_receipt(
    *,
    expected_sha: str,
    reason: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    artifact: dict[str, Any] = {
        "bridge_schema_version": BRIDGE_SCHEMA_VERSION,
        "bridge_contract_version": BRIDGE_CONTRACT_VERSION,
        "registered_commit_sha": expected_sha,
        "diagnostic_schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "diagnostic_contract_version": DIAGNOSTIC_CONTRACT_VERSION,
        "diagnostic_status": "BLOCKED",
        "reason_code": reason,
        "evidence_only": True,
        "promo_role_promoted": False,
        "promo_role_policy": PROMO_ROLE_POLICY,
        **{field: False for field in _SAFETY_FIELDS},
    }
    summary = {
        "bridge_schema_version": BRIDGE_SCHEMA_VERSION,
        "bridge_contract_version": BRIDGE_CONTRACT_VERSION,
        "bridge_execution_status": "PASS",
        "registered_commit_sha": expected_sha,
        "diagnostic_status": "BLOCKED",
        "reason_code": reason,
        "evidence_only": True,
        "promo_role_promoted": False,
        "nur_marker_count": None,
        "card_local_nur_marker_count": None,
        "orphan_nur_marker_count": None,
        "public_amount_candidate_pair_count": None,
        "distinct_structure_signature_count": None,
        "diagnostic_result_identity_sha256": None,
        "production_deploy_authorized": False,
        "host_mutation_authorized": False,
    }
    return artifact, summary


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        _fail(f"{label} field set mismatch")


def _json_sha(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_bool(value: object, expected: bool, label: str) -> None:
    if value is not expected:
        _fail(f"{label} must be {expected}")


def _require_int(value: object, label: str, *, maximum: int = 100_000) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > maximum:
        _fail(f"{label} must be a bounded non-negative integer")
    return value


def _require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        _fail(f"{label} must be a lowercase SHA-256")
    return value


def _require_locator(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("rawpath:/")
        or len(value) > MAX_LOCATOR_LENGTH
        or "\n" in value
        or "\r" in value
    ):
        _fail(f"{label} is not a bounded rawpath locator")
    return value


def _require_tag(value: object, label: str) -> str:
    if not isinstance(value, str) or not _TAG_RE.fullmatch(value):
        _fail(f"{label} is not a bounded tag")
    return value


def _price_classes(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or len(value) > 16:
        _fail(f"{label} must be a bounded list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not _PRICE_CLASS_RE.fullmatch(item):
            _fail(f"{label} contains a non-price structural class")
        result.append(item)
    if result != sorted(set(result)):
        _fail(f"{label} must be sorted and unique")
    return result


def _relation_fields(item: dict[str, Any], label: str) -> None:
    relation = item.get("relation")
    if relation not in _ALLOWED_RELATIONS:
        _fail(f"{label} relation is not allowlisted")
    _require_int(item.get("marker_parent_to_lca_steps"), f"{label}.marker_parent_to_lca_steps", maximum=64)
    _require_int(item.get("candidate_to_lca_steps"), f"{label}.candidate_to_lca_steps", maximum=64)
    _require_tag(item.get("lca_tag"), f"{label}.lca_tag")
    _price_classes(item.get("lca_price_classes"), f"{label}.lca_price_classes")


def _validate_candidate(item: object, label: str) -> None:
    if not isinstance(item, dict):
        _fail(f"{label} must be an object")
    _exact_keys(item, _CANDIDATE_KEYS, label)
    _relation_fields(item, label)
    _require_locator(item["lca_locator"], f"{label}.lca_locator")
    _require_tag(item["candidate_tag"], f"{label}.candidate_tag")
    _require_locator(item["candidate_locator"], f"{label}.candidate_locator")
    _require_sha256(item["candidate_fragment_sha256"], f"{label}.candidate_fragment_sha256")
    _price_classes(item["candidate_price_classes"], f"{label}.candidate_price_classes")
    if not isinstance(item["candidate_generic_price_tag_class_present"], bool):
        _fail(f"{label}.candidate_generic_price_tag_class_present must be boolean")
    if item["candidate_amount_count"] != 1:
        _fail(f"{label}.candidate_amount_count must be exactly one")
    _require_bool(item["candidate_xtra_class_present"], False, f"{label}.candidate_xtra_class_present")
    _require_bool(item["candidate_old_price_class_present"], False, f"{label}.candidate_old_price_class_present")


def _validate_marker_base(item: dict[str, Any], label: str) -> None:
    if item.get("marker") != "text:nur":
        _fail(f"{label}.marker must be text:nur")
    _require_tag(item.get("marker_tag"), f"{label}.marker_tag")
    _require_locator(item.get("marker_locator"), f"{label}.marker_locator")
    _require_sha256(item.get("marker_fragment_sha256"), f"{label}.marker_fragment_sha256")
    _price_classes(item.get("marker_price_classes"), f"{label}.marker_price_classes")
    _require_int(item.get("marker_amount_count"), f"{label}.marker_amount_count", maximum=32)


def _validate_marker(item: object, label: str) -> None:
    if not isinstance(item, dict):
        _fail(f"{label} must be an object")
    _exact_keys(item, _MARKER_KEYS, label)
    _validate_marker_base(item, label)
    _require_locator(item["owner_card_locator"], f"{label}.owner_card_locator")
    _require_sha256(item["owner_card_fragment_sha256"], f"{label}.owner_card_fragment_sha256")
    candidate_count = _require_int(
        item["public_amount_candidate_count"],
        f"{label}.public_amount_candidate_count",
        maximum=10_000,
    )
    samples = item["public_amount_candidate_samples"]
    if not isinstance(samples, list) or len(samples) > MAX_CANDIDATE_SAMPLES_PER_MARKER:
        _fail(f"{label}.public_amount_candidate_samples exceeds bound")
    for index, candidate in enumerate(samples):
        _validate_candidate(candidate, f"{label}.public_amount_candidate_samples[{index}]")
    truncated = item["candidate_samples_truncated"]
    if not isinstance(truncated, bool):
        _fail(f"{label}.candidate_samples_truncated must be boolean")
    if candidate_count < len(samples):
        _fail(f"{label}.public_amount_candidate_count is smaller than sample count")
    if truncated != (candidate_count > MAX_CANDIDATE_SAMPLES_PER_MARKER):
        _fail(f"{label}.candidate_samples_truncated is inconsistent")


def _validate_orphan(item: object, label: str) -> None:
    if not isinstance(item, dict):
        _fail(f"{label} must be an object")
    _exact_keys(item, _MARKER_BASE_KEYS, label)
    _validate_marker_base(item, label)


def _validate_signature(item: object, label: str) -> None:
    if not isinstance(item, dict):
        _fail(f"{label} must be an object")
    _exact_keys(item, _SIGNATURE_KEYS, label)
    _require_sha256(item["signature_identity_sha256"], f"{label}.signature_identity_sha256")
    _require_int(item["count"], f"{label}.count", maximum=100_000)
    _relation_fields(item, label)
    _require_tag(item["candidate_tag"], f"{label}.candidate_tag")
    _price_classes(item["candidate_price_classes"], f"{label}.candidate_price_classes")
    if not isinstance(item["candidate_generic_price_tag_class_present"], bool):
        _fail(f"{label}.candidate_generic_price_tag_class_present must be boolean")
    identity_payload = {key: value for key, value in item.items() if key not in {"signature_identity_sha256", "count"}}
    if _json_sha(identity_payload) != item["signature_identity_sha256"]:
        _fail(f"{label}.signature_identity_sha256 mismatch")


def _validate_projection(projection: object) -> dict[str, Any]:
    if not isinstance(projection, dict):
        _fail("projection must be an object")
    _exact_keys(projection, _PROJECTION_KEYS, "projection")
    if projection["schema_version"] != DIAGNOSTIC_SCHEMA_VERSION:
        _fail("projection schema version mismatch")
    if projection["contract_version"] != PROJECTION_CONTRACT_VERSION:
        _fail("projection contract version mismatch")
    if projection["parser_backend"] != PARSER_BACKEND:
        _fail("projection parser backend mismatch")
    if projection["diagnostic_status"] != "EVIDENCE_ONLY":
        _fail("projection is not evidence-only")
    _require_bool(projection["promo_role_promoted"], False, "projection.promo_role_promoted")
    if projection["promo_role_policy"] != PROMO_ROLE_POLICY:
        _fail("projection promo role policy mismatch")

    marker_count = _require_int(projection["nur_marker_count"], "projection.nur_marker_count", maximum=10_000)
    local_count = _require_int(
        projection["card_local_nur_marker_count"],
        "projection.card_local_nur_marker_count",
        maximum=10_000,
    )
    orphan_count = _require_int(
        projection["orphan_nur_marker_count"],
        "projection.orphan_nur_marker_count",
        maximum=10_000,
    )
    if marker_count != local_count + orphan_count:
        _fail("projection marker ownership counts are inconsistent")
    _require_int(
        projection["public_amount_candidate_pair_count"],
        "projection.public_amount_candidate_pair_count",
    )
    distinct_count = _require_int(
        projection["distinct_structure_signature_count"],
        "projection.distinct_structure_signature_count",
        maximum=10_000,
    )

    signatures = projection["structure_signature_samples"]
    if not isinstance(signatures, list) or len(signatures) > MAX_SIGNATURES:
        _fail("projection structure signature sample bound exceeded")
    for index, item in enumerate(signatures):
        _validate_signature(item, f"projection.structure_signature_samples[{index}]")
    if distinct_count < len(signatures):
        _fail("projection distinct signature count smaller than samples")
    if projection["structure_signatures_truncated"] is not (distinct_count > MAX_SIGNATURES):
        _fail("projection structure signature truncation flag is inconsistent")

    markers = projection["marker_samples"]
    if not isinstance(markers, list) or len(markers) > MAX_MARKER_SAMPLES:
        _fail("projection marker sample bound exceeded")
    for index, item in enumerate(markers):
        _validate_marker(item, f"projection.marker_samples[{index}]")
    if local_count < len(markers):
        _fail("projection local marker count smaller than samples")
    if projection["marker_samples_truncated"] is not (local_count > MAX_MARKER_SAMPLES):
        _fail("projection marker truncation flag is inconsistent")

    orphans = projection["orphan_marker_samples"]
    if not isinstance(orphans, list) or len(orphans) > MAX_MARKER_SAMPLES:
        _fail("projection orphan sample bound exceeded")
    for index, item in enumerate(orphans):
        _validate_orphan(item, f"projection.orphan_marker_samples[{index}]")
    if orphan_count < len(orphans):
        _fail("projection orphan marker count smaller than samples")
    if projection["orphan_marker_samples_truncated"] is not (orphan_count > MAX_MARKER_SAMPLES):
        _fail("projection orphan truncation flag is inconsistent")

    identity = _require_sha256(
        projection["projection_identity_sha256"],
        "projection.projection_identity_sha256",
    )
    without_identity = dict(projection)
    del without_identity["projection_identity_sha256"]
    if _json_sha(without_identity) != identity:
        _fail("projection identity mismatch")
    return projection


def _validate_common(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != DIAGNOSTIC_SCHEMA_VERSION:
        _fail("diagnostic schema version mismatch")
    if payload.get("contract_version") != DIAGNOSTIC_CONTRACT_VERSION:
        _fail("diagnostic contract version mismatch")
    _require_bool(payload.get("evidence_only"), True, "diagnostic.evidence_only")
    _require_bool(payload.get("promo_role_promoted"), False, "diagnostic.promo_role_promoted")
    for field in _SAFETY_FIELDS:
        _require_bool(payload.get(field), False, f"diagnostic.{field}")


def validate_and_sanitize(
    payload: object,
    *,
    expected_sha: str,
    diagnostic_rc: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not _SHA_RE.fullmatch(expected_sha):
        _fail("registered commit SHA is invalid")
    if not isinstance(payload, dict):
        _fail("diagnostic output must be an object")

    status = payload.get("status")
    if status == "PASS":
        _exact_keys(payload, _PASS_KEYS, "diagnostic PASS")
        if diagnostic_rc != 0:
            _fail("PASS diagnostic must exit zero")
        _validate_common(payload)
        _require_bool(payload["target_fingerprint_unchanged"], True, "diagnostic.target_fingerprint_unchanged")
        _require_bool(
            payload["second_derivation_deterministic"],
            True,
            "diagnostic.second_derivation_deterministic",
        )
        if payload["target_fingerprint_before"] != payload["target_fingerprint_after"]:
            _fail("diagnostic target fingerprints differ")

        verifier = payload["k2_verifier"]
        if not isinstance(verifier, dict):
            _fail("k2 verifier receipt must be an object")
        _exact_keys(
            verifier,
            {"action", "bundle_key", "bundle_identity_sha256", "artifact_count", "family_count"},
            "k2 verifier",
        )
        if verifier["action"] != "NO_OP":
            _fail("k2 verifier action must be NO_OP")
        if verifier["bundle_key"] != EXPECTED_BUNDLE_KEY:
            _fail("k2 verifier bundle key mismatch")
        if verifier["bundle_identity_sha256"] != EXPECTED_BUNDLE_IDENTITY:
            _fail("k2 verifier bundle identity mismatch")
        if verifier["artifact_count"] != EXPECTED_ARTIFACT_COUNT:
            _fail("k2 verifier artifact count mismatch")
        if verifier["family_count"] != EXPECTED_FAMILY_COUNT:
            _fail("k2 verifier family count mismatch")

        projection = _validate_projection(payload["projection"])
        result_identity = _require_sha256(payload["result_identity_sha256"], "diagnostic.result_identity_sha256")
        without_identity = dict(payload)
        del without_identity["result_identity_sha256"]
        if _json_sha(without_identity) != result_identity:
            _fail("diagnostic result identity mismatch")

        artifact: dict[str, Any] = {
            "bridge_schema_version": BRIDGE_SCHEMA_VERSION,
            "bridge_contract_version": BRIDGE_CONTRACT_VERSION,
            "registered_commit_sha": expected_sha,
            "diagnostic_schema_version": DIAGNOSTIC_SCHEMA_VERSION,
            "diagnostic_contract_version": DIAGNOSTIC_CONTRACT_VERSION,
            "diagnostic_status": "PASS",
            "evidence_only": True,
            "promo_role_promoted": False,
            "promo_role_policy": PROMO_ROLE_POLICY,
            "k2_verifier": verifier,
            "target_fingerprint_unchanged": True,
            "second_derivation_deterministic": True,
            "projection": projection,
            "diagnostic_result_identity_sha256": result_identity,
            **{field: False for field in _SAFETY_FIELDS},
        }
        summary = {
            "bridge_schema_version": BRIDGE_SCHEMA_VERSION,
            "bridge_contract_version": BRIDGE_CONTRACT_VERSION,
            "bridge_execution_status": "PASS",
            "registered_commit_sha": expected_sha,
            "diagnostic_status": "PASS",
            "reason_code": None,
            "evidence_only": True,
            "promo_role_promoted": False,
            "nur_marker_count": projection["nur_marker_count"],
            "card_local_nur_marker_count": projection["card_local_nur_marker_count"],
            "orphan_nur_marker_count": projection["orphan_nur_marker_count"],
            "public_amount_candidate_pair_count": projection["public_amount_candidate_pair_count"],
            "distinct_structure_signature_count": projection["distinct_structure_signature_count"],
            "diagnostic_result_identity_sha256": result_identity,
            "production_deploy_authorized": False,
            "host_mutation_authorized": False,
        }
        return artifact, summary

    if status == "BLOCKED":
        _exact_keys(payload, _BLOCKED_KEYS, "diagnostic BLOCKED")
        if diagnostic_rc != 20:
            _fail("BLOCKED diagnostic must exit 20")
        _validate_common(payload)
        reason = payload["reason_code"]
        if not isinstance(reason, str) or not _REASON_RE.fullmatch(reason):
            _fail("diagnostic reason code is not bounded")
        artifact = {
            "bridge_schema_version": BRIDGE_SCHEMA_VERSION,
            "bridge_contract_version": BRIDGE_CONTRACT_VERSION,
            "registered_commit_sha": expected_sha,
            "diagnostic_schema_version": DIAGNOSTIC_SCHEMA_VERSION,
            "diagnostic_contract_version": DIAGNOSTIC_CONTRACT_VERSION,
            "diagnostic_status": "BLOCKED",
            "reason_code": reason,
            "evidence_only": True,
            "promo_role_promoted": False,
            "promo_role_policy": PROMO_ROLE_POLICY,
            **{field: False for field in _SAFETY_FIELDS},
        }
        summary = {
            "bridge_schema_version": BRIDGE_SCHEMA_VERSION,
            "bridge_contract_version": BRIDGE_CONTRACT_VERSION,
            "bridge_execution_status": "PASS",
            "registered_commit_sha": expected_sha,
            "diagnostic_status": "BLOCKED",
            "reason_code": reason,
            "evidence_only": True,
            "promo_role_promoted": False,
            "nur_marker_count": None,
            "card_local_nur_marker_count": None,
            "orphan_nur_marker_count": None,
            "public_amount_candidate_pair_count": None,
            "distinct_structure_signature_count": None,
            "diagnostic_result_identity_sha256": None,
            "production_deploy_authorized": False,
            "host_mutation_authorized": False,
        }
        return artifact, summary

    _fail("diagnostic status is not allowlisted")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate and sanitize Kaufland K3C RPi diagnostic output")
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--diagnostic-rc", type=int, required=True)
    args = parser.parse_args(argv)

    try:
        if args.raw.is_symlink() or not args.raw.is_file():
            _fail("raw diagnostic output is missing or unsafe")
        if args.raw.stat().st_size > MAX_RAW_BYTES:
            _fail("raw diagnostic output exceeds size bound")
        payload = json.loads(args.raw.read_text(encoding="utf-8"))
        artifact, summary = validate_and_sanitize(
            payload,
            expected_sha=args.expected_sha,
            diagnostic_rc=args.diagnostic_rc,
        )
    except (BridgeValidationError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        reason = _sanitizer_failure_reason(exc)
        artifact, summary = _sanitizer_blocked_receipt(
            expected_sha=args.expected_sha,
            reason=reason,
        )

    _write_json(args.artifact, artifact)
    _write_json(args.summary, summary)
    print(
        f"VALIDATION_RESULT=PASS DIAGNOSTIC_STATUS={summary['diagnostic_status']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())