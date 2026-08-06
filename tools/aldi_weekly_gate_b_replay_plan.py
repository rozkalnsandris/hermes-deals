#!/usr/bin/env python3
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


MODE = "ALDI_WEEKLY_GATE_B_REPLAY_PLAN_V01"
RECEIPT_MODE = "ALDI_A30_ROLLOVER_RECONCILIATION_RECEIPT_V01"
EXPECTED_RECEIPT_SHA256 = (
    "6e335a4c696ca3d43e5d1c4d0549a23b231db547ab9d5413b4a13b93de545ab9"
)
EXPECTED_ARTIFACT_SHA256 = (
    "fce7766060b9ff32874b55e474ea28a957b9ee21a7b0e2ecbe11952c36879bd4"
)
EXPECTED_REGISTERED_COMMIT = "10e22b745a92bcf4e7213aafe83e165e08719c99"
EXPECTED_REPORT_SHA256 = (
    "ece18d2c357236d77ae4ed453cf8bdc9cd642aec675abe1463dcddf3b15d3925"
)
EXPECTED_MANUAL_REVIEW_SHA256 = (
    "f6b4a4e32f7c038a0ef18402bc5ef7680494abe419b7bc7738f0ae74d4daeca3"
)
EXPECTED_MOVED_PAGES = [
    {
        "old_page": 3,
        "new_page": 4,
        "sha256": "9ec7d0f2981013edf21e866b7c7bd9a9a8bf4c9f38e6b2f1fe48f42b585b9bd1",
    },
    {
        "old_page": 4,
        "new_page": 5,
        "sha256": "f61a951cdd7ef74d1c4a790fec778b68dc0b6043e9ace59a5f8e7a3191985930",
    },
    {
        "old_page": 5,
        "new_page": 37,
        "sha256": "d7d9587bd4730d4240941cb33156c27333c64f5985ccd57f6b2d319f033c36b8",
    },
]
LEGACY_A31_REFERENCE = {
    "strategy": "aldi_a31_deterministic_bidirectional_parity_v1",
    "projection_sha256": (
        "64699b7ede52dcaa5b85f3306426f3b90399dd037209621a38bacd166161d5ea"
    ),
    "page_counts": {"current": 49, "preview": 41},
    "target_counts": {"auto_candidate": 346, "review_required": 54},
    "reuse_mode": "frozen_reference_only",
}


class GateBError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise GateBError(message)


def _sha256(data: bytes) -> str:
    return sha256(data).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _safe_path(root: Path, value: str) -> Path:
    relative = PurePosixPath(value)
    _require(value != "", "empty relative path forbidden")
    _require(not relative.is_absolute(), f"absolute path forbidden: {value}")
    _require(".." not in relative.parts, f"parent traversal forbidden: {value}")
    current = root
    _require(current.is_dir() and not current.is_symlink(), "evidence root invalid")
    for part in relative.parts:
        current = current / part
        _require(not current.is_symlink(), f"symlinked evidence forbidden: {value}")
    _require(current.is_file(), f"required file missing: {value}")
    return current


def _read_verified_file(root: Path, descriptor: Mapping[str, Any]) -> bytes:
    path = _safe_path(root, str(descriptor.get("path") or ""))
    data = path.read_bytes()
    _require(
        len(data) == int(descriptor.get("bytes", -1)),
        f"byte-size mismatch: {descriptor.get('path')}",
    )
    _require(
        _sha256(data) == descriptor.get("sha256"),
        f"SHA256 mismatch: {descriptor.get('path')}",
    )
    return data


def _load_json(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateBError(f"invalid {label} JSON: {exc}") from exc
    _require(isinstance(value, dict), f"{label} must be a JSON object")
    return value


def load_receipt(path: Path) -> dict[str, Any]:
    _require(path.is_file() and not path.is_symlink(), "receipt must be a regular file")
    data = path.read_bytes()
    _require(_sha256(data) == EXPECTED_RECEIPT_SHA256, "receipt SHA256 mismatch")
    receipt = _load_json(data, "receipt")
    validate_receipt_contract(receipt)
    return receipt


def validate_receipt_contract(receipt: Mapping[str, Any]) -> None:
    _require(receipt.get("schema_version") == 1, "unexpected receipt schema")
    _require(receipt.get("mode") == RECEIPT_MODE, "unexpected receipt mode")
    _require(receipt.get("issue_number") == 191, "receipt issue binding mismatch")
    _require(
        receipt.get("decision") == "shadow_reconciliation_accepted",
        "reconciliation receipt is not accepted",
    )

    artifact = receipt.get("artifact") or {}
    _require(artifact.get("run_id") == 31105044968, "workflow run binding mismatch")
    _require(artifact.get("artifact_id") == 8969175974, "artifact ID binding mismatch")
    _require(
        artifact.get("zip_sha256") == EXPECTED_ARTIFACT_SHA256,
        "artifact ZIP binding mismatch",
    )
    _require(
        artifact.get("registered_commit") == EXPECTED_REGISTERED_COMMIT,
        "registered commit binding mismatch",
    )

    evidence = receipt.get("evidence") or {}
    report = evidence.get("authoritative_report") or {}
    manual = evidence.get("manual_review") or {}
    _require(
        report.get("sha256") == EXPECTED_REPORT_SHA256,
        "authoritative report binding mismatch",
    )
    _require(
        manual.get("sha256") == EXPECTED_MANUAL_REVIEW_SHA256,
        "manual-review binding mismatch",
    )

    rollover = receipt.get("rollover") or {}
    _require(rollover.get("current_page_count") == 41, "current page count must be 41")
    _require(rollover.get("preview_page_count") == 41, "preview page count must be 41")
    _require(
        rollover.get("positional_visual_matched_pages") == 36,
        "positional match count must be 36",
    )
    _require(
        rollover.get("content_set_matched_pages") == 39,
        "content-set match count must be 39",
    )
    _require(
        rollover.get("moved_pages") == EXPECTED_MOVED_PAGES,
        "moved-page mapping mismatch",
    )
    _require(rollover.get("old_only_pages") == [37, 41], "old-only page mismatch")
    _require(rollover.get("new_only_pages") == [3, 41], "new-only page mismatch")
    _require(
        rollover.get("duplicate_content_groups") == [],
        "duplicate content groups must be empty",
    )
    _require(
        rollover.get("strict_41_of_41_automatic_promotion_passed") is False,
        "strict 41/41 gate must remain blocked",
    )

    classifications = receipt.get("classifications") or {}
    page3 = classifications.get("new_current_page_3") or {}
    _require(
        page3.get("classification") == "offer_page_added_to_current_ledger",
        "new current page 3 classification mismatch",
    )
    _require(page3.get("current_ledger_action") == "include", "page 3 ledger action mismatch")
    _require(
        page3.get("automatic_offer_approval_allowed") is False,
        "page 3 automatic approval must remain blocked",
    )
    page37 = classifications.get("old_preview_page_37") or {}
    _require(
        page37.get("classification") == "removed_non_offer_competition_page",
        "old preview page 37 classification mismatch",
    )
    _require(page37.get("carry_forward") is False, "old page 37 must not carry forward")
    page41 = classifications.get("information_page_41_change") or {}
    _require(
        page41.get("classification") == "non_offer_information_page_content_changed",
        "page 41 classification mismatch",
    )
    _require(
        page41.get("automatic_offer_extraction_allowed") is False,
        "page 41 offer extraction must remain blocked",
    )

    safety = receipt.get("safety") or {}
    _require(
        safety.get("next_step_scope") == "shadow_parser_and_parity_only",
        "receipt next-step scope mismatch",
    )
    _require(
        safety.get("strict_41_of_41_gate_unchanged") is True,
        "strict gate changed",
    )
    for key in (
        "automatic_promotion_allowed",
        "automatic_approval_allowed",
        "automatic_publication_allowed",
        "production_database_write_allowed",
        "production_deployment_allowed",
        "scheduler_installation_allowed",
        "b15m2_v08_action_allowed",
    ):
        _require(safety.get(key) is False, f"unsafe receipt flag: {key}")


def _manifest_rows(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    rows = manifest.get("files")
    _require(isinstance(rows, list), "dispatcher manifest files must be a list")
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        _require(isinstance(row, Mapping), "dispatcher manifest row must be an object")
        path = str(row.get("path") or "")
        _require(path and path not in result, "dispatcher manifest paths must be unique")
        result[path] = row
    return result


def _verify_manifest_descriptor(
    rows: Mapping[str, Mapping[str, Any]],
    descriptor: Mapping[str, Any],
) -> None:
    path = str(descriptor.get("path") or "")
    row = rows.get(path)
    _require(row is not None, f"dispatcher manifest evidence missing: {path}")
    _require(row.get("sha256") == descriptor.get("sha256"), f"manifest SHA mismatch: {path}")
    _require(
        int(row.get("bytes", -1)) == int(descriptor.get("bytes", -2)),
        f"manifest byte-size mismatch: {path}",
    )


def _page_rows(report: Mapping[str, Any], label: str) -> dict[int, Mapping[str, Any]]:
    source = (report.get("sources") or {}).get(label) or {}
    rows = source.get("pages")
    _require(isinstance(rows, list), f"{label} pages must be a list")
    result: dict[int, Mapping[str, Any]] = {}
    for row in rows:
        _require(isinstance(row, Mapping), f"{label} page row must be an object")
        page = int(row.get("page_number", 0))
        _require(page in range(1, 42), f"{label} page outside 1..41")
        _require(page not in result, f"duplicate {label} page: {page}")
        result[page] = row
    _require(sorted(result) == list(range(1, 42)), f"{label} pages must be exactly 1..41")
    _require(source.get("page_count") == 41, f"{label} page_count must be 41")
    return result


def validate_evidence(
    receipt: Mapping[str, Any],
    artifact_root: Path,
    *,
    verify_page_bytes: bool = True,
) -> tuple[dict[str, Any], dict[str, Any], dict[int, Mapping[str, Any]]]:
    validate_receipt_contract(receipt)
    _require(artifact_root.is_dir() and not artifact_root.is_symlink(), "artifact root invalid")

    manifest_descriptor = (receipt.get("evidence") or {}).get("dispatcher_manifest") or {}
    manifest_data = _read_verified_file(artifact_root, manifest_descriptor)
    manifest = _load_json(manifest_data, "dispatcher manifest")
    _require(manifest.get("schema_version") == 1, "unexpected dispatcher manifest schema")
    _require(manifest.get("audit") == "aldi-a30-authoritative-cycle", "unexpected audit name")
    _require(manifest.get("audit_exit_code") == 3, "expected controlled exit code 3")
    _require(
        manifest.get("commit_sha") == EXPECTED_REGISTERED_COMMIT,
        "dispatcher commit mismatch",
    )
    _require(manifest.get("sanitization_passed") is True, "sanitization did not pass")
    _require(
        manifest.get("production_apply_authorized") is False,
        "production apply must remain unauthorized",
    )
    manifest_rows = _manifest_rows(manifest)

    evidence = receipt.get("evidence") or {}
    for key in ("authoritative_report", "manual_review"):
        descriptor = evidence.get(key) or {}
        _verify_manifest_descriptor(manifest_rows, descriptor)

    report_descriptor = evidence["authoritative_report"]
    report = _load_json(
        _read_verified_file(artifact_root, report_descriptor),
        "authoritative report",
    )
    manual_descriptor = evidence["manual_review"]
    manual = _load_json(
        _read_verified_file(artifact_root, manual_descriptor),
        "manual review",
    )

    _require(report.get("schema_version") == 2, "unexpected report schema")
    _require(
        report.get("mode") == "ALDI_A30_AUTHORITATIVE_CYCLE_ACQUISITION_V01",
        "unexpected report mode",
    )
    _require(report.get("commit_sha") == EXPECTED_REGISTERED_COMMIT, "report commit mismatch")
    _require(report.get("result") == "blocked", "report must remain blocked")
    _require(report.get("state") == "authoritative_cycle_blocked", "report state mismatch")
    _require(report.get("source_roots_distinct") is True, "source roots must be distinct")
    for key in (
        "production_database_write",
        "production_deployment",
        "collector_executed",
        "automatic_approval",
        "automatic_publication",
    ):
        _require(report.get(key) is False, f"unsafe report flag: {key}")

    current = _page_rows(report, "current")
    _page_rows(report, "preview")
    for page, row in current.items():
        descriptor = {
            "path": f"evidence/{row.get('path')}",
            "sha256": row.get("sha256"),
            "bytes": row.get("bytes"),
        }
        _verify_manifest_descriptor(manifest_rows, descriptor)
    rollover = report.get("rollover") or {}
    _require(rollover.get("required_pages") == 41, "required page count mismatch")
    _require(rollover.get("matched_pages") == 36, "positional match count mismatch")
    _require(rollover.get("all_pages_match") is False, "strict gate unexpectedly passed")
    comparisons = rollover.get("comparisons")
    _require(isinstance(comparisons, list) and len(comparisons) == 41, "comparison set mismatch")
    by_page: dict[int, Mapping[str, Any]] = {}
    for row in comparisons:
        _require(isinstance(row, Mapping), "comparison row must be an object")
        page = int(row.get("page_number", 0))
        _require(page in range(1, 42) and page not in by_page, "comparison pages must be unique")
        by_page[page] = row
    _require(sorted(by_page) == list(range(1, 42)), "comparison pages must be 1..41")

    analysis = report.get("rollover_analysis") or {}
    _require(
        analysis.get("mode") == "ALDI_A30_ROLLOVER_REVIEW_ANALYSIS_V01",
        "unexpected rollover analysis mode",
    )
    _require(analysis.get("exact_positional_matched_pages") == 36, "exact positional mismatch")
    _require(analysis.get("content_set_matched_pages") == 39, "content-set mismatch")
    _require(analysis.get("moved_pages") == EXPECTED_MOVED_PAGES, "analysis moved-page mismatch")
    _require(analysis.get("old_only_pages") == [37, 41], "analysis old-only mismatch")
    _require(analysis.get("new_only_pages") == [3, 41], "analysis new-only mismatch")
    _require(analysis.get("duplicate_content_groups") == [], "analysis duplicate groups")
    _require(analysis.get("manual_review_required") is True, "manual review must remain required")
    _require(
        analysis.get("strict_41_of_41_gate_unchanged") is True,
        "analysis strict gate changed",
    )
    _require(
        analysis.get("automatic_promotion_allowed") is False,
        "analysis promotion must remain blocked",
    )

    same_position_pages = sorted(set(range(1, 42)) - {3, 4, 5, 37, 41})
    _require(len(same_position_pages) == 36, "internal positional page set mismatch")
    for page in same_position_pages:
        row = by_page[page]
        _require(row.get("exact_bytes") is True, f"page {page} is not an exact positional match")
        _require(row.get("visual_match") is True, f"page {page} visual match missing")
        _require(
            row.get("left_sha256") == row.get("right_sha256") == current[page].get("sha256"),
            f"page {page} positional SHA mismatch",
        )

    for moved in EXPECTED_MOVED_PAGES:
        old_page = moved["old_page"]
        new_page = moved["new_page"]
        _require(
            by_page[old_page].get("left_sha256") == moved["sha256"],
            f"old moved-page SHA mismatch: {old_page}",
        )
        _require(
            current[new_page].get("sha256") == moved["sha256"],
            f"new moved-page SHA mismatch: {new_page}",
        )

    classifications = receipt["classifications"]
    page3 = classifications["new_current_page_3"]
    page41 = classifications["information_page_41_change"]["new"]
    _require(current[3].get("sha256") == page3["sha256"], "page 3 SHA mismatch")
    _require(int(current[3].get("bytes", -1)) == page3["bytes"], "page 3 size mismatch")
    _require(current[41].get("sha256") == page41["sha256"], "page 41 SHA mismatch")
    _require(int(current[41].get("bytes", -1)) == page41["bytes"], "page 41 size mismatch")

    _require(manual.get("schema_version") == 1, "unexpected manual-review schema")
    _require(manual.get("classification") == "manual_review_required", "manual class mismatch")
    _require(manual.get("content_set_matched_pages") == 39, "manual content-set mismatch")
    _require(manual.get("moved_pages") == EXPECTED_MOVED_PAGES, "manual moved-page mismatch")
    _require(manual.get("old_only_pages") == [37, 41], "manual old-only mismatch")
    _require(manual.get("new_only_pages") == [3, 41], "manual new-only mismatch")
    _require(manual.get("automatic_promotion_allowed") is False, "manual promotion unsafe")

    if verify_page_bytes:
        evidence_root = artifact_root / "evidence"
        _require(evidence_root.is_dir() and not evidence_root.is_symlink(), "evidence root invalid")
        for page, row in current.items():
            relative = str(row.get("path") or "")
            path = _safe_path(evidence_root, relative)
            data = path.read_bytes()
            _require(len(data) == int(row.get("bytes", -1)), f"current page {page} size mismatch")
            _require(_sha256(data) == row.get("sha256"), f"current page {page} SHA mismatch")

    return report, manual, current


def _carry_forward_mappings(
    report: Mapping[str, Any],
    current: Mapping[int, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    comparisons = {
        int(row["page_number"]): row
        for row in (report.get("rollover") or {}).get("comparisons") or []
    }
    positional_pages = sorted(set(range(1, 42)) - {3, 4, 5, 37, 41})
    rows = [
        {
            "old_preview_page": page,
            "new_current_page": page,
            "sha256": str(current[page]["sha256"]),
            "method": "exact_same_position",
        }
        for page in positional_pages
    ]
    rows.extend(
        {
            "old_preview_page": int(item["old_page"]),
            "new_current_page": int(item["new_page"]),
            "sha256": str(item["sha256"]),
            "method": "exact_moved_page",
        }
        for item in EXPECTED_MOVED_PAGES
    )
    rows.sort(key=lambda row: (row["new_current_page"], row["old_preview_page"]))
    _require(len(rows) == 39, "carry-forward mapping count must be 39")
    old_pages = [row["old_preview_page"] for row in rows]
    new_pages = [row["new_current_page"] for row in rows]
    _require(len(old_pages) == len(set(old_pages)), "duplicate old page assignment")
    _require(len(new_pages) == len(set(new_pages)), "duplicate new page assignment")
    _require(set(old_pages) == set(range(1, 42)) - {37, 41}, "old carry-forward set mismatch")
    _require(set(new_pages) == set(range(1, 42)) - {3, 41}, "new carry-forward set mismatch")
    _require(37 not in old_pages, "removed old competition page carried forward")
    _require(3 not in new_pages, "changed new offer page silently carried forward")
    _require(41 not in new_pages, "informational page entered carry-forward set")
    for row in rows:
        if row["method"] == "exact_same_position":
            comparison = comparisons[row["old_preview_page"]]
            _require(comparison.get("exact_bytes") is True, "positional mapping not exact")
    return rows


def validate_prior_plan(prior: Mapping[str, Any]) -> str:
    _require(prior.get("schema_version") == 1, "prior plan schema mismatch")
    _require(prior.get("mode") == MODE, "prior plan mode mismatch")
    _require(prior.get("issue_number") == 200, "prior plan issue mismatch")
    _require(
        prior.get("upstream_issue_numbers") == [64, 165, 191, 196],
        "prior upstream issue binding mismatch",
    )
    _require(
        prior.get("decision") in {"READY_FOR_SHADOW_REPLAY", "NO_OP"},
        "prior plan decision is not successful",
    )
    fingerprint = str(prior.get("replay_fingerprint") or "")
    _require(len(fingerprint) == 64, "prior replay fingerprint missing")
    identity = prior.get("identity")
    _require(isinstance(identity, Mapping), "prior identity is incomplete")
    _require(
        _sha256(_canonical_bytes(identity)) == fingerprint,
        "prior replay fingerprint does not bind identity",
    )
    artifact = identity.get("artifact") or {}
    _require(artifact.get("run_id") == 31105044968, "prior run binding mismatch")
    _require(artifact.get("artifact_id") == 8969175974, "prior artifact ID mismatch")
    _require(
        artifact.get("zip_sha256") == EXPECTED_ARTIFACT_SHA256,
        "prior artifact ZIP mismatch",
    )
    _require(
        identity.get("receipt_sha256") == EXPECTED_RECEIPT_SHA256,
        "prior receipt binding mismatch",
    )
    _require(
        identity.get("authoritative_report_sha256") == EXPECTED_REPORT_SHA256,
        "prior report binding mismatch",
    )
    _require(
        identity.get("manual_review_sha256") == EXPECTED_MANUAL_REVIEW_SHA256,
        "prior manual-review binding mismatch",
    )
    _require(
        identity.get("legacy_a31_reference") == LEGACY_A31_REFERENCE,
        "prior legacy A3.1 boundary mismatch",
    )
    _require(prior.get("legacy_a31_reference") == LEGACY_A31_REFERENCE, "prior legacy reference mismatch")
    _require(prior.get("safety") == safety_contract(), "prior plan safety mismatch")
    _require(prior.get("candidate_parity_claimed") is False, "prior candidate parity claim unsafe")
    _require(prior.get("production_eligible") is False, "prior production eligibility unsafe")
    _require(prior.get("promotion_ready") is False, "prior promotion flag unsafe")
    _require(
        prior.get("next_step_scope")
        == "carry_forward_parity_plus_page_3_fresh_shadow_extraction",
        "prior next-step scope mismatch",
    )
    counts = prior.get("partition_counts") or {}
    _require(
        counts == {
            "carry_forward_parity": 39,
            "fresh_shadow_extraction": 1,
            "excluded_informational": 1,
        },
        "prior partition counts mismatch",
    )
    mappings = prior.get("carry_forward_mappings")
    _require(isinstance(mappings, list) and len(mappings) == 39, "prior carry-forward mappings incomplete")
    _require(identity.get("carry_forward_mappings") == mappings, "prior mapping identity mismatch")
    manifest = prior.get("current_page_manifest")
    _require(isinstance(manifest, list) and len(manifest) == 41, "prior current manifest incomplete")
    _require(
        _sha256(_canonical_bytes(manifest)) == identity.get("current_manifest_sha256"),
        "prior current manifest hash mismatch",
    )
    dispositions = [str(row.get("disposition") or "") for row in manifest if isinstance(row, Mapping)]
    _require(dispositions.count("carry_forward_parity") == 39, "prior carry-forward partition incomplete")
    _require(
        dispositions.count("fresh_shadow_extraction_required") == 1,
        "prior fresh-extraction partition incomplete",
    )
    _require(
        dispositions.count("non_offer_informational_excluded") == 1,
        "prior informational exclusion incomplete",
    )
    fresh = prior.get("fresh_shadow_extraction")
    _require(isinstance(fresh, list) and len(fresh) == 1, "prior fresh extraction row missing")
    _require(fresh[0].get("new_current_page") == 3, "prior fresh extraction page mismatch")
    _require(
        fresh[0].get("automatic_candidate_creation_allowed") is False,
        "prior fresh extraction safety mismatch",
    )
    excluded = prior.get("excluded_informational")
    _require(isinstance(excluded, list) and len(excluded) == 1, "prior informational row missing")
    _require(excluded[0].get("new_current_page") == 41, "prior informational page mismatch")
    _require(
        excluded[0].get("automatic_offer_extraction_allowed") is False,
        "prior informational safety mismatch",
    )
    return fingerprint


def safety_contract() -> dict[str, Any]:
    return {
        "plan_only": True,
        "network_acquisition_authorized": False,
        "source_or_corpus_write_authorized": False,
        "parser_execution_authorized": False,
        "candidate_creation_authorized": False,
        "production_database_write_authorized": False,
        "review_write_authorized": False,
        "automatic_approval_authorized": False,
        "automatic_publication_authorized": False,
        "production_deployment_authorized": False,
        "scheduler_or_retry_authorized": False,
        "production_canary_authorized": False,
        "b15m2_v08_action_authorized": False,
        "strict_41_of_41_gate_unchanged": True,
    }


def build_plan(
    receipt: Mapping[str, Any],
    report: Mapping[str, Any],
    current: Mapping[int, Mapping[str, Any]],
    *,
    prior: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    validate_receipt_contract(receipt)
    mappings = _carry_forward_mappings(report, current)
    inverse = {row["new_current_page"]: row for row in mappings}
    page_rows: list[dict[str, Any]] = []
    for page in range(1, 42):
        source = current[page]
        if page == 3:
            disposition = "fresh_shadow_extraction_required"
            old_page = None
        elif page == 41:
            disposition = "non_offer_informational_excluded"
            old_page = None
        else:
            disposition = "carry_forward_parity"
            old_page = inverse[page]["old_preview_page"]
        page_rows.append(
            {
                "page_number": page,
                "sha256": str(source["sha256"]),
                "bytes": int(source["bytes"]),
                "image_format": str(source.get("image_format") or ""),
                "source_path": str(source["path"]),
                "disposition": disposition,
                "old_preview_page": old_page,
            }
        )

    current_manifest_sha = _sha256(_canonical_bytes(page_rows))
    identity = {
        "artifact": {
            "run_id": receipt["artifact"]["run_id"],
            "artifact_id": receipt["artifact"]["artifact_id"],
            "zip_sha256": receipt["artifact"]["zip_sha256"],
            "registered_commit": receipt["artifact"]["registered_commit"],
        },
        "receipt_sha256": EXPECTED_RECEIPT_SHA256,
        "authoritative_report_sha256": EXPECTED_REPORT_SHA256,
        "manual_review_sha256": EXPECTED_MANUAL_REVIEW_SHA256,
        "current_manifest_sha256": current_manifest_sha,
        "carry_forward_mappings": mappings,
        "fresh_shadow_extraction_pages": [3],
        "excluded_informational_pages": [41],
        "removed_old_preview_pages": [37, 41],
        "legacy_a31_reference": LEGACY_A31_REFERENCE,
    }
    fingerprint = _sha256(_canonical_bytes(identity))
    prior_fingerprint = validate_prior_plan(prior) if prior is not None else None
    decision = "NO_OP" if prior_fingerprint == fingerprint else "READY_FOR_SHADOW_REPLAY"

    return {
        "schema_version": 1,
        "mode": MODE,
        "issue_number": 200,
        "upstream_issue_numbers": [64, 165, 191, 196],
        "decision": decision,
        "replay_fingerprint": fingerprint,
        "identity": identity,
        "partition_counts": {
            "carry_forward_parity": 39,
            "fresh_shadow_extraction": 1,
            "excluded_informational": 1,
        },
        "carry_forward_mappings": mappings,
        "fresh_shadow_extraction": [
            {
                "new_current_page": 3,
                "classification": "fresh_shadow_extraction_required",
                "automatic_candidate_creation_allowed": False,
                "sha256": str(current[3]["sha256"]),
            }
        ],
        "excluded_informational": [
            {
                "new_current_page": 41,
                "classification": "non_offer_informational_excluded",
                "automatic_offer_extraction_allowed": False,
                "sha256": str(current[41]["sha256"]),
            }
        ],
        "removed_old_preview_pages": [
            {
                "old_preview_page": 37,
                "classification": "removed_non_offer_competition_page",
                "carry_forward": False,
            },
            {
                "old_preview_page": 41,
                "classification": "superseded_non_offer_information_page",
                "carry_forward": False,
            },
        ],
        "current_page_manifest": page_rows,
        "legacy_a31_reference": LEGACY_A31_REFERENCE,
        "next_step_scope": "carry_forward_parity_plus_page_3_fresh_shadow_extraction",
        "candidate_parity_claimed": False,
        "production_eligible": False,
        "promotion_ready": False,
        "safety": safety_contract(),
    }


def write_plan(path: Path, plan: Mapping[str, Any]) -> str:
    data = _canonical_bytes(plan)
    if path.exists():
        _require(path.is_file() and not path.is_symlink(), "existing output is not a regular file")
        _require(path.read_bytes() == data, "existing Gate B plan differs")
        return "unchanged"
    path.parent.mkdir(parents=True, exist_ok=True)
    _require(not path.parent.is_symlink(), "output parent symlink forbidden")
    with path.open("xb") as handle:
        handle.write(data)
    return "created"


def verify_artifact_zip(path: Path) -> None:
    _require(path.is_file() and not path.is_symlink(), "artifact ZIP must be a regular file")
    _require(_sha256(path.read_bytes()) == EXPECTED_ARTIFACT_SHA256, "artifact ZIP SHA256 mismatch")


def run(
    *,
    receipt_path: Path,
    artifact_zip_path: Path,
    artifact_root: Path,
    output_path: Path,
    prior_path: Path | None = None,
) -> dict[str, Any]:
    verify_artifact_zip(artifact_zip_path)
    receipt = load_receipt(receipt_path)
    report, _manual, current = validate_evidence(receipt, artifact_root)
    prior = None
    if prior_path is not None:
        _require(prior_path.is_file() and not prior_path.is_symlink(), "prior plan invalid")
        prior = _load_json(prior_path.read_bytes(), "prior plan")
    plan = build_plan(receipt, report, current, prior=prior)
    state = write_plan(output_path, plan)
    return {
        "decision": plan["decision"],
        "output_state": state,
        "replay_fingerprint": plan["replay_fingerprint"],
        "current_manifest_sha256": plan["identity"]["current_manifest_sha256"],
        "carry_forward_page_count": 39,
        "fresh_shadow_extraction_page_count": 1,
        "excluded_informational_page_count": 1,
        "production_eligible": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the read-only ALDI weekly Gate B shadow replay plan"
    )
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--artifact-zip", required=True, type=Path)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--prior-plan", type=Path)
    args = parser.parse_args()
    try:
        result = run(
            receipt_path=args.receipt,
            artifact_zip_path=args.artifact_zip,
            artifact_root=args.artifact_root,
            output_path=args.output,
            prior_path=args.prior_plan,
        )
    except (GateBError, OSError, ValueError) as exc:
        print(f"ERROR|{exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
