#!/usr/bin/env python3
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import stat
import sys
from typing import Any, Mapping
import zipfile


PLAN_VERSION = "lidl-source-refresh-r3-plan-v1"
RESULT = "R3_PLAN_READY"

EXPECTED_ARTIFACT_ID = 9021545332
EXPECTED_ARTIFACT_DIGEST = "d4f9be1a19592a45739e4cc6a2827833682460e1c41bdd6496e0375077ef33c4"
EXPECTED_R2_RUN_ID = 31256539018
EXPECTED_R2_RESULT = "R2_STAGING_SCAN_READY"
EXPECTED_FAMILY = "aktionsprospekt-03-08-2026-08-08-2026-b1cf3b--src-6da2135ea984"
EXPECTED_PDF_SHA256 = "6da2135ea984d1f79bdb311dfa0d8affd1d2f8d46c63a1bba25b202a30a5fb16"
EXPECTED_FROZEN_RAW_SHA256 = "d1af2062f10f5fd25d4ac197fe74459bf0c313d7f5890f5d96c3db9572b7ddf1"
EXPECTED_STABLE_SHA256 = "7486e32f837869b3dedc36b5a129c034129f653bf698df4ad55649510623ff17"
EXPECTED_REFERENCE_INPUT_SHA256 = "8d63c989fd1897215f9556942aec16636ce7c0e5a8bb05b5a672693f58519c5a"
EXPECTED_LIVE_INPUT_SHA256 = "e6ebe5669551a2d455e7b2c036746e08e3bdd20e8e0562fab6972ab97e2a88e8"
EXPECTED_BINDING_SHA256 = "12ebbb79bb7bfd46e603e766d357549bf4fb381e6afe4dfdcfeaa1844d6ac6dd"
EXPECTED_BINDING_COUNT = 140
EXPECTED_PRODUCT_LINK_COUNT = 141
EXPECTED_SCAN_NAME = "scan-v631-7191e910f07b"
EXPECTED_SCAN_TREE_SHA256 = "701902c873126d8bb6a6756a650b7ed46ea4a32b302742d6f3a4969f5db48e96"
EXPECTED_SCAN_RAW_SHA256 = "3139e33fce2c56bf1daf0db2b220e52389551c243ab91143037e5e1c102f09df"
EXPECTED_REVIEW_SHA256 = "b1563ab386fffe5ace6a3441b593596df98d0e7166bd07dff37602d9575adc09"
EXPECTED_PARSER_VERSION = "lidl-pdf-v08c-r61-shadow-v631"
EXPECTED_PARSER_SHA256 = "7191e910f07bb0a14ece3f398f1ba73e3ea250fc4bec1aeafea3afa8ce6dda90"
EXPECTED_GATE_A_MERGE_SHA = "f814092c06068547cac03923f40f470ae5a33e5e"
EXPECTED_GATE_A_VALIDATOR_SHA256 = "54e8a86d8e3b883c9bb58f9eac9d4a51153e6e169bec0ffd083fc129549313f5"
EXPECTED_REV04_PROFILE_SHA256 = "35944611b36b04d42b570e6f10f42e1fc393eca1c0aa12cda14d7ae230e46780"

EXPECTED_R2_SAFETY = {
    "authoritative_corpus_write": False,
    "auto_approve": False,
    "auto_publish": False,
    "automatic_retry": False,
    "b15m2_v08_authorized": False,
    "database_write": False,
    "gate_c_d_authorized": False,
    "production_deploy": False,
    "review_write": False,
    "source_review_promotion": False,
    "staging_scan": True,
    "systemd_change": False,
}

AUTHORITY_PERMISSIONS = {
    "gate_a_refresh_acceptance": True,
    "source_pdf_replace": False,
    "source_json_replace": False,
    "db_write": False,
    "review_write": False,
    "auto_approve": False,
    "auto_publish": False,
    "production_deploy": False,
    "systemd_change": False,
}

PLAN_SAFETY = {
    "plan_only": True,
    "corpus_write_authorized": False,
    "source_review_promotion_authorized": False,
    "scan_promotion_authorized": False,
    "authority_promotion_authorized": False,
    "profile_promotion_authorized": False,
    "database_write_authorized": False,
    "review_write_authorized": False,
    "auto_approve_authorized": False,
    "auto_publish_authorized": False,
    "production_deploy_authorized": False,
    "systemd_change_authorized": False,
    "automatic_retry_authorized": False,
    "gate_c_d_authorized": False,
    "b15m2_v08_authorized": False,
}


class R3PlanError(RuntimeError):
    pass


def _canonical_bytes(payload: Any) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _digest_payload(payload: Any) -> str:
    return sha256(_canonical_bytes(payload)).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def _safe_member(info: zipfile.ZipInfo) -> None:
    path = PurePosixPath(info.filename)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise R3PlanError(f"unsafe artifact path: {info.filename}")
    mode = info.external_attr >> 16
    if stat.S_ISLNK(mode):
        raise R3PlanError(f"artifact symlink is forbidden: {info.filename}")
    if info.is_dir():
        return
    if mode and not stat.S_ISREG(mode):
        raise R3PlanError(f"unsupported artifact entry: {info.filename}")


def _load_json(data: bytes, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise R3PlanError(f"{label} is invalid JSON") from exc
    if not isinstance(payload, Mapping):
        raise R3PlanError(f"{label} must contain an object")
    return dict(payload)


def _scan_tree_manifest(files: Mapping[str, bytes]) -> list[dict[str, Any]]:
    prefix = f"staging-scan/{EXPECTED_SCAN_NAME}/"
    rows = []
    for name in sorted(files):
        if not name.startswith(prefix):
            continue
        relative = name[len(prefix) :]
        if not relative:
            continue
        data = files[name]
        rows.append({"path": relative, "bytes": len(data), "sha256": _sha256_bytes(data)})
    return rows


def _scan_tree_digest(rows: list[dict[str, Any]]) -> str:
    content = "\n".join(
        f"{row['path']}|{row['bytes']}|{row['sha256']}" for row in rows
    ) + "\n"
    return sha256(content.encode("utf-8")).hexdigest()


def _validate_artifact_manifest(files: Mapping[str, bytes]) -> dict[str, Any]:
    manifest = _load_json(files["evidence/artifact-manifest.json"], "artifact manifest")
    if manifest.get("result") != EXPECTED_R2_RESULT:
        raise R3PlanError("artifact manifest result mismatch")
    if manifest.get("raw_source_exported") is not False:
        raise R3PlanError("artifact claims raw source export")
    if manifest.get("safety") != EXPECTED_R2_SAFETY:
        raise R3PlanError("artifact safety mismatch")
    declared = manifest.get("files")
    if not isinstance(declared, list):
        raise R3PlanError("artifact manifest files must be a list")
    declared_paths: set[str] = set()
    for row in declared:
        if not isinstance(row, Mapping):
            raise R3PlanError("artifact manifest file row is invalid")
        path = str(row.get("path") or "")
        if not path or path == "evidence/artifact-manifest.json":
            raise R3PlanError("artifact manifest path is invalid")
        if path in declared_paths:
            raise R3PlanError("artifact manifest contains duplicate paths")
        declared_paths.add(path)
        data = files.get(path)
        if data is None:
            raise R3PlanError(f"artifact declared file is missing: {path}")
        if int(row.get("bytes") or -1) != len(data):
            raise R3PlanError(f"artifact declared size mismatch: {path}")
        if str(row.get("sha256") or "") != _sha256_bytes(data):
            raise R3PlanError(f"artifact declared SHA mismatch: {path}")
    actual_payload_paths = set(files) - {"evidence/artifact-manifest.json"}
    if declared_paths != actual_payload_paths:
        raise R3PlanError("artifact payload file set differs from manifest")
    retained_rows = [dict(row) for row in declared]
    if manifest.get("payload_tree_sha256") != _digest_payload(retained_rows):
        raise R3PlanError("artifact payload tree digest mismatch")
    return manifest


def _validate_r2(files: Mapping[str, bytes]) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    forbidden = [
        name
        for name in files
        if name == "source.pdf"
        or name == "source.json"
        or name.endswith("/source.pdf")
        or name.endswith("/source.json")
    ]
    if forbidden:
        raise R3PlanError("raw source material leaked into retained R2 artifact")

    _validate_artifact_manifest(files)
    summary = _load_json(files["evidence/r2-summary.json"], "R2 summary")
    review = _load_json(files["evidence/approved-source-review.json"], "source review")

    if summary.get("result") != EXPECTED_R2_RESULT:
        raise R3PlanError("R2 summary result mismatch")
    if summary.get("safety") != EXPECTED_R2_SAFETY:
        raise R3PlanError("R2 summary safety mismatch")
    source = summary.get("source")
    if not isinstance(source, Mapping):
        raise R3PlanError("R2 source binding missing")
    expected_source = {
        "parser_input_identity_sha256": EXPECTED_LIVE_INPUT_SHA256,
        "pdf_sha256": EXPECTED_PDF_SHA256,
        "product_binding_count": EXPECTED_BINDING_COUNT,
        "product_binding_sha256": EXPECTED_BINDING_SHA256,
        "product_link_count": EXPECTED_PRODUCT_LINK_COUNT,
        "raw_sha256": EXPECTED_SCAN_RAW_SHA256,
        "raw_sha_is_provenance_only": True,
        "stable_source_identity_sha256": EXPECTED_STABLE_SHA256,
    }
    if dict(source) != expected_source:
        raise R3PlanError("R2 source identity mismatch")

    if summary.get("reference_input") != {
        "parser_input_identity_sha256": EXPECTED_REFERENCE_INPUT_SHA256,
        "product_binding_count": EXPECTED_BINDING_COUNT,
        "product_binding_sha256": EXPECTED_BINDING_SHA256,
    }:
        raise R3PlanError("R2 reference input mismatch")
    if summary.get("approved_live_input") != {
        "parser_input_identity_sha256": EXPECTED_LIVE_INPUT_SHA256,
        "product_binding_count": EXPECTED_BINDING_COUNT,
        "product_binding_sha256": EXPECTED_BINDING_SHA256,
    }:
        raise R3PlanError("R2 approved live input mismatch")
    if summary.get("observed_changes") != {
        "binding_added": 0,
        "binding_removed": 0,
        "binding_title_changed": 0,
    }:
        raise R3PlanError("R2 binding change summary mismatch")
    if summary.get("parser") != {
        "version": EXPECTED_PARSER_VERSION,
        "sha256": EXPECTED_PARSER_SHA256,
    }:
        raise R3PlanError("R2 parser identity mismatch")
    scan = summary.get("scan")
    if not isinstance(scan, Mapping):
        raise R3PlanError("R2 scan binding missing")
    expected_scan_scalars = {
        "name": EXPECTED_SCAN_NAME,
        "tree_sha256": EXPECTED_SCAN_TREE_SHA256,
        "rows": 363,
        "physical_rows": 362,
        "online_only_rows": 1,
        "in_scope_rows": 218,
        "review_required_rows": 362,
        "accepted_physical_rows": 0,
        "file_count": 11,
    }
    for key, value in expected_scan_scalars.items():
        if scan.get(key) != value:
            raise R3PlanError(f"R2 scan {key} mismatch")
    replay = summary.get("replay")
    if not isinstance(replay, Mapping) or replay.get("isolated_runs") != 2 or replay.get("byte_identical") is not True:
        raise R3PlanError("R2 deterministic replay proof missing")
    if replay.get("scan_a_tree_sha256") != EXPECTED_SCAN_TREE_SHA256 or replay.get("scan_b_tree_sha256") != EXPECTED_SCAN_TREE_SHA256:
        raise R3PlanError("R2 replay tree SHA mismatch")

    if _sha256_bytes(files["evidence/approved-source-review.json"]) != EXPECTED_REVIEW_SHA256:
        raise R3PlanError("source-review SHA mismatch")
    if review.get("flyer_key") != EXPECTED_FAMILY or review.get("pdf_sha256") != EXPECTED_PDF_SHA256:
        raise R3PlanError("source-review flyer/PDF binding mismatch")
    if review.get("decision") != "approve_parser_input_refresh" or review.get("scope") != "authoritative_staging_scan_only":
        raise R3PlanError("source-review decision/scope mismatch")
    if review.get("permissions") != {
        "staging_scan": True,
        "corpus_write": False,
        "db_write": False,
        "review_seed": False,
        "auto_approve": False,
        "auto_publish": False,
        "systemd_change": False,
    }:
        raise R3PlanError("source-review permissions mismatch")

    tree = _scan_tree_manifest(files)
    if len(tree) != 11:
        raise R3PlanError("retained scan file count mismatch")
    if _scan_tree_digest(tree) != EXPECTED_SCAN_TREE_SHA256:
        raise R3PlanError("retained scan tree SHA mismatch")
    scan_summary = _load_json(
        files[f"staging-scan/{EXPECTED_SCAN_NAME}/summary.json"],
        "retained scan summary",
    )
    if scan_summary.get("flyer_key") != EXPECTED_FAMILY:
        raise R3PlanError("retained scan flyer mismatch")
    if scan_summary.get("scan") != EXPECTED_SCAN_NAME:
        raise R3PlanError("retained scan name mismatch")
    if scan_summary.get("parser_version") != EXPECTED_PARSER_VERSION or scan_summary.get("parser_sha256") != EXPECTED_PARSER_SHA256:
        raise R3PlanError("retained scan parser mismatch")
    if scan_summary.get("source") != {
        "pdf_sha256": EXPECTED_PDF_SHA256,
        "raw_sha256": EXPECTED_SCAN_RAW_SHA256,
    }:
        raise R3PlanError("retained scan source provenance mismatch")
    return summary, review, tree


def _authority_core(summary: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "authority_version": "lidl-source-refresh-authority-v1",
        "decision": "accept_reviewed_parser_input_refresh",
        "scope": "gate_a_authoritative_scan_only",
        "flyer_key": EXPECTED_FAMILY,
        "pdf_sha256": EXPECTED_PDF_SHA256,
        "stable_source_identity_sha256": EXPECTED_STABLE_SHA256,
        "reference_input": {
            "parser_input_identity_sha256": EXPECTED_REFERENCE_INPUT_SHA256,
            "product_binding_sha256": EXPECTED_BINDING_SHA256,
            "product_binding_count": EXPECTED_BINDING_COUNT,
        },
        "approved_live_input": {
            "parser_input_identity_sha256": EXPECTED_LIVE_INPUT_SHA256,
            "product_binding_sha256": EXPECTED_BINDING_SHA256,
            "product_binding_count": EXPECTED_BINDING_COUNT,
            "product_link_count": EXPECTED_PRODUCT_LINK_COUNT,
        },
        "observed_changes": {
            "binding_added": 0,
            "binding_removed": 0,
            "binding_title_changed": 0,
        },
        "source_review": {"sha256": EXPECTED_REVIEW_SHA256},
        "parser": {
            "version": EXPECTED_PARSER_VERSION,
            "sha256": EXPECTED_PARSER_SHA256,
        },
        "scan": {
            "name": EXPECTED_SCAN_NAME,
            "tree_sha256": EXPECTED_SCAN_TREE_SHA256,
            "scan_time_raw_sha256": EXPECTED_SCAN_RAW_SHA256,
        },
        "permissions": dict(AUTHORITY_PERMISSIONS),
    }


def build_plan(*, artifact_zip: Path, artifact_id: int, artifact_digest: str) -> dict[str, Any]:
    artifact_zip = artifact_zip.resolve()
    if not artifact_zip.is_file() or artifact_zip.is_symlink():
        raise R3PlanError("R2 artifact ZIP is missing or unsafe")
    if artifact_id != EXPECTED_ARTIFACT_ID:
        raise R3PlanError("unexpected R2 artifact ID")
    if artifact_digest != EXPECTED_ARTIFACT_DIGEST:
        raise R3PlanError("unexpected R2 artifact digest")
    if _sha256_bytes(artifact_zip.read_bytes()) != EXPECTED_ARTIFACT_DIGEST:
        raise R3PlanError("R2 artifact ZIP digest mismatch")

    with zipfile.ZipFile(artifact_zip) as archive:
        infos = archive.infolist()
        if len(infos) != 15:
            raise R3PlanError("unexpected R2 artifact member count")
        files: dict[str, bytes] = {}
        for info in infos:
            _safe_member(info)
            if info.is_dir():
                raise R3PlanError("directory entries are not expected in R2 artifact")
            if info.filename in files:
                raise R3PlanError("duplicate R2 artifact member")
            files[info.filename] = archive.read(info)

    required = {
        "evidence/approved-source-review.json",
        "evidence/r2-summary.json",
        "evidence/artifact-manifest.json",
        "evidence/scan-tree-manifest.json",
        f"staging-scan/{EXPECTED_SCAN_NAME}/summary.json",
    }
    if not required.issubset(files):
        raise R3PlanError("R2 artifact required members are missing")
    summary, review, scan_tree = _validate_r2(files)
    core = _authority_core(summary)
    core_sha = _digest_payload(core)

    refresh_root = f"flyers/{EXPECTED_FAMILY}/source-refresh/{EXPECTED_LIVE_INPUT_SHA256}"
    targets = {
        "scan_dir": f"flyers/{EXPECTED_FAMILY}/scans/{EXPECTED_SCAN_NAME}",
        "source_review": f"{refresh_root}/source-review.json",
        "authority": f"{refresh_root}/authority.json",
        "promotion_receipt": f"{refresh_root}/promotion-receipt.json",
    }
    exact_payloads = {
        "scan_tree_sha256": EXPECTED_SCAN_TREE_SHA256,
        "scan_file_count": len(scan_tree),
        "source_review_sha256": EXPECTED_REVIEW_SHA256,
        "authority_core_sha256": core_sha,
        "authority_core": core,
    }
    preconditions = {
        "immutable_source_pdf_sha256": EXPECTED_PDF_SHA256,
        "immutable_source_json_sha256": EXPECTED_FROZEN_RAW_SHA256,
        "current_live_semantic_identity": {
            "pdf_sha256": EXPECTED_PDF_SHA256,
            "stable_source_identity_sha256": EXPECTED_STABLE_SHA256,
            "parser_input_identity_sha256": EXPECTED_LIVE_INPUT_SHA256,
            "product_binding_sha256": EXPECTED_BINDING_SHA256,
            "product_binding_count": EXPECTED_BINDING_COUNT,
            "product_link_count": EXPECTED_PRODUCT_LINK_COUNT,
            "binding_changes": {
                "binding_added": 0,
                "binding_removed": 0,
                "binding_title_changed": 0,
            },
            "raw_sha_is_provenance_only": True,
        },
        "all_targets_must_be_absent": list(targets.values()),
        "rev05_review_profile_must_be_absent": f"flyers/{EXPECTED_FAMILY}/review-profile.json",
        "rev04_profile_reuse_forbidden_sha256": EXPECTED_REV04_PROFILE_SHA256,
        "required_gate_a_merge_sha": EXPECTED_GATE_A_MERGE_SHA,
        "required_gate_a_validator_sha256": EXPECTED_GATE_A_VALIDATOR_SHA256,
        "fresh_owner_r3_promotion_authorization_required": True,
        "authorization_must_bind_plan_fingerprint": True,
        "exclusive_create_only": True,
        "overwrite_immutable_source_forbidden": True,
    }
    prediction = {
        "expected_gate_a_state_after_valid_promotion": "WAIT_PROFILE",
        "expected_gate_a_reason_class": "rev05_review_profile_missing",
        "ready_is_forbidden_without_independent_rev05_profile": True,
        "rev04_profile_reuse_forbidden": True,
    }
    plan_basis = {
        "schema_version": 1,
        "plan_version": PLAN_VERSION,
        "result": RESULT,
        "r2_artifact": {
            "id": EXPECTED_ARTIFACT_ID,
            "digest": EXPECTED_ARTIFACT_DIGEST,
            "workflow_run_id": EXPECTED_R2_RUN_ID,
        },
        "targets": targets,
        "exact_payloads": {
            "scan_tree_sha256": exact_payloads["scan_tree_sha256"],
            "scan_file_count": exact_payloads["scan_file_count"],
            "source_review_sha256": exact_payloads["source_review_sha256"],
            "authority_core_sha256": exact_payloads["authority_core_sha256"],
        },
        "preconditions": preconditions,
        "prediction": prediction,
        "safety": PLAN_SAFETY,
    }
    fingerprint = _digest_payload(plan_basis)
    return {
        **plan_basis,
        "plan_fingerprint": fingerprint,
        "authority_core": core,
        "authority_finalization_contract": {
            "dynamic_field": "promotion",
            "final_authority_equals_core_plus_promotion": True,
            "promotion_fields": [
                "approved_by",
                "approved_at",
                "authorization_comment_id",
                "r2_artifact_id",
                "r2_artifact_digest",
            ],
            "r2_artifact_id": EXPECTED_ARTIFACT_ID,
            "r2_artifact_digest": EXPECTED_ARTIFACT_DIGEST,
            "fresh_owner_authorization_required": True,
            "final_authority_sha256_is_not_known_before_authorization": True,
        },
        "source_review_payload_sha256": _sha256_bytes(files["evidence/approved-source-review.json"]),
        "scan_tree_manifest": scan_tree,
        "r2_summary_sha256": _sha256_bytes(files["evidence/r2-summary.json"]),
        "artifact_manifest_sha256": _sha256_bytes(files["evidence/artifact-manifest.json"]),
    }


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    if temporary.exists():
        raise R3PlanError("temporary output path already exists")
    temporary.write_bytes(_canonical_bytes(payload))
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Lidl rev05 R3 source-refresh promotion planner")
    parser.add_argument("--artifact-zip", type=Path, required=True)
    parser.add_argument("--artifact-id", type=int, required=True)
    parser.add_argument("--artifact-digest", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        plan = build_plan(
            artifact_zip=args.artifact_zip,
            artifact_id=args.artifact_id,
            artifact_digest=args.artifact_digest,
        )
        if args.output.exists():
            raise R3PlanError("output path already exists")
        _atomic_json(args.output, plan)
    except Exception as exc:
        print(f"R3_PLAN_BLOCKED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 30
    print(json.dumps(plan, sort_keys=True))
    print(f"RESULT={plan['result']}")
    print(f"PLAN_FINGERPRINT={plan['plan_fingerprint']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
