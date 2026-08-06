from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
from typing import Any


MODE = "ALDI_A30_ROLLOVER_RECONCILIATION_RECEIPT_V01"
EXPECTED_RECEIPT_SHA256 = "6e335a4c696ca3d43e5d1c4d0549a23b231db547ab9d5413b4a13b93de545ab9"
EXPECTED_ARTIFACT_SHA256 = "fce7766060b9ff32874b55e474ea28a957b9ee21a7b0e2ecbe11952c36879bd4"
EXPECTED_COMMIT_SHA = "10e22b745a92bcf4e7213aafe83e165e08719c99"


class ReconciliationError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReconciliationError(message)


def _sha256(data: bytes) -> str:
    return sha256(data).hexdigest()


def _safe_path(root: Path, value: str) -> Path:
    relative = PurePosixPath(value)
    _require(not relative.is_absolute(), f"absolute evidence path forbidden: {value}")
    _require(".." not in relative.parts, f"parent traversal forbidden: {value}")
    path = root.joinpath(*relative.parts)
    _require(path.is_file(), f"evidence file missing: {value}")
    return path


def _verify_file(root: Path, descriptor: dict[str, Any]) -> bytes:
    path = _safe_path(root, str(descriptor["path"]))
    data = path.read_bytes()
    _require(len(data) == int(descriptor["bytes"]), f"byte-size mismatch: {descriptor['path']}")
    _require(_sha256(data) == descriptor["sha256"], f"SHA256 mismatch: {descriptor['path']}")
    return data


def _load_json_bytes(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReconciliationError(f"invalid {label} JSON: {exc}") from exc
    _require(isinstance(value, dict), f"{label} must be a JSON object")
    return value


def load_authoritative_receipt(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    _require(_sha256(data) == EXPECTED_RECEIPT_SHA256, "receipt SHA256 mismatch")
    receipt = _load_json_bytes(data, "receipt")
    validate_receipt_contract(receipt)
    return receipt


def validate_receipt_contract(receipt: dict[str, Any]) -> None:
    _require(receipt.get("schema_version") == 1, "unexpected receipt schema")
    _require(receipt.get("mode") == MODE, "unexpected receipt mode")
    _require(receipt.get("issue_number") == 191, "receipt issue mismatch")
    _require(receipt.get("upstream_issue_numbers") == [80, 121, 165], "upstream issue binding mismatch")
    _require(receipt.get("decision") == "shadow_reconciliation_accepted", "receipt decision mismatch")

    artifact = receipt.get("artifact") or {}
    _require(artifact.get("run_id") == 31105044968, "workflow run binding mismatch")
    _require(artifact.get("artifact_id") == 8969175974, "artifact ID binding mismatch")
    _require(artifact.get("zip_sha256") == EXPECTED_ARTIFACT_SHA256, "artifact ZIP SHA mismatch")
    _require(artifact.get("registered_commit") == EXPECTED_COMMIT_SHA, "registered commit mismatch")

    rollover = receipt.get("rollover") or {}
    _require(rollover.get("current_page_count") == 41, "current page count must be 41")
    _require(rollover.get("preview_page_count") == 41, "preview page count must be 41")
    _require(rollover.get("positional_visual_matched_pages") == 36, "positional match count must be 36")
    _require(rollover.get("content_set_matched_pages") == 39, "content-set match count must be 39")
    _require(rollover.get("strict_41_of_41_automatic_promotion_passed") is False, "strict gate must remain blocked")
    _require(rollover.get("old_only_pages") == [37, 41], "old-only page set mismatch")
    _require(rollover.get("new_only_pages") == [3, 41], "new-only page set mismatch")
    _require(rollover.get("duplicate_content_groups") == [], "duplicate content groups must be empty")

    expected_moved = [
        {"old_page": 3, "new_page": 4, "sha256": "9ec7d0f2981013edf21e866b7c7bd9a9a8bf4c9f38e6b2f1fe48f42b585b9bd1"},
        {"old_page": 4, "new_page": 5, "sha256": "f61a951cdd7ef74d1c4a790fec778b68dc0b6043e9ace59a5f8e7a3191985930"},
        {"old_page": 5, "new_page": 37, "sha256": "d7d9587bd4730d4240941cb33156c27333c64f5985ccd57f6b2d319f033c36b8"},
    ]
    _require(rollover.get("moved_pages") == expected_moved, "moved-page mapping mismatch")

    classifications = receipt.get("classifications") or {}
    page3 = classifications.get("new_current_page_3") or {}
    _require(page3.get("classification") == "offer_page_added_to_current_ledger", "new page 3 classification weakened")
    _require(page3.get("current_ledger_action") == "include", "new page 3 must enter current ledger")
    _require(page3.get("automatic_offer_approval_allowed") is False, "page 3 automatic approval must remain blocked")

    page37 = classifications.get("old_preview_page_37") or {}
    _require(page37.get("classification") == "removed_non_offer_competition_page", "old page 37 classification weakened")
    _require(page37.get("carry_forward") is False, "old page 37 must not be carried forward")
    _require(page37.get("automatic_offer_extraction_allowed") is False, "old page 37 extraction must remain blocked")

    page41 = classifications.get("information_page_41_change") or {}
    _require(page41.get("classification") == "non_offer_information_page_content_changed", "page 41 classification weakened")
    _require(page41.get("automatic_offer_extraction_allowed") is False, "page 41 extraction must remain blocked")

    safety = receipt.get("safety") or {}
    _require(safety.get("strict_41_of_41_gate_unchanged") is True, "strict 41/41 gate changed")
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
    _require(safety.get("next_step_scope") == "shadow_parser_and_parity_only", "next-step scope mismatch")


def _manifest_rows(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = manifest.get("files")
    _require(isinstance(rows, list), "dispatcher manifest files must be a list")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        _require(isinstance(row, dict), "dispatcher manifest file row must be an object")
        path = str(row.get("path") or "")
        _require(path and path not in result, "dispatcher manifest paths must be unique")
        result[path] = row
    return result


def _require_manifest_descriptor(rows: dict[str, dict[str, Any]], descriptor: dict[str, Any]) -> None:
    path = str(descriptor["path"])
    manifest_path = path
    row = rows.get(manifest_path)
    _require(row is not None, f"manifest evidence missing: {manifest_path}")
    _require(row.get("sha256") == descriptor["sha256"], f"manifest SHA mismatch: {manifest_path}")
    _require(int(row.get("bytes", -1)) == int(descriptor["bytes"]), f"manifest byte-size mismatch: {manifest_path}")


def _page_rows(report: dict[str, Any], label: str) -> dict[int, dict[str, Any]]:
    source = (report.get("sources") or {}).get(label) or {}
    rows = source.get("pages")
    _require(isinstance(rows, list), f"{label} pages must be a list")
    result: dict[int, dict[str, Any]] = {}
    for row in rows:
        page = int(row.get("page_number", 0))
        _require(page > 0 and page not in result, f"{label} page identities must be unique")
        result[page] = row
    _require(sorted(result) == list(range(1, 42)), f"{label} page sequence must be 1..41")
    return result


def validate_evidence_semantics(
    receipt: dict[str, Any],
    manifest: dict[str, Any],
    report: dict[str, Any],
    manual: dict[str, Any],
) -> dict[str, Any]:
    validate_receipt_contract(receipt)

    artifact = receipt["artifact"]
    _require(manifest.get("schema_version") == 1, "unexpected dispatcher manifest schema")
    _require(manifest.get("audit") == "aldi-a30-authoritative-cycle", "unexpected dispatcher audit")
    _require(manifest.get("audit_exit_code") == 3, "expected REVIEW_REQUIRED exit code 3")
    _require(manifest.get("commit_sha") == artifact["registered_commit"], "dispatcher commit mismatch")
    _require(manifest.get("sanitization_passed") is True, "dispatcher sanitization did not pass")
    _require(manifest.get("production_apply_authorized") is False, "production apply must remain unauthorized")
    manifest_rows = _manifest_rows(manifest)

    for key in ("authoritative_report", "manual_review"):
        _require_manifest_descriptor(manifest_rows, receipt["evidence"][key])
    classes = receipt["classifications"]
    page_descriptors = [
        classes["new_current_page_3"],
        classes["old_preview_page_37"],
        classes["information_page_41_change"]["old"],
        classes["information_page_41_change"]["new"],
    ]
    for descriptor in page_descriptors:
        _require_manifest_descriptor(manifest_rows, descriptor)

    _require(report.get("schema_version") == 2, "unexpected authoritative report schema")
    _require(report.get("mode") == "ALDI_A30_AUTHORITATIVE_CYCLE_ACQUISITION_V01", "unexpected authoritative report mode")
    _require(report.get("commit_sha") == artifact["registered_commit"], "report commit mismatch")
    _require(report.get("result") == "blocked", "authoritative report must remain blocked")
    _require(report.get("state") == "authoritative_cycle_blocked", "authoritative state mismatch")
    _require(report.get("source_roots_distinct") is True, "source roots must remain distinct")
    for key in (
        "production_database_write",
        "production_deployment",
        "collector_executed",
        "automatic_approval",
        "automatic_publication",
    ):
        _require(report.get(key) is False, f"unsafe authoritative report flag: {key}")

    current = _page_rows(report, "current")
    _page_rows(report, "preview")
    _require(report["sources"]["current"].get("page_count") == 41, "report current page count mismatch")
    _require(report["sources"]["preview"].get("page_count") == 41, "report preview page count mismatch")
    rollover = report.get("rollover") or {}
    _require(rollover.get("required_pages") == 41, "report required-page count mismatch")
    _require(rollover.get("matched_pages") == 36, "report positional match count mismatch")
    _require(rollover.get("all_pages_match") is False, "report strict gate unexpectedly passed")

    analysis = report.get("rollover_analysis") or {}
    expected_rollover = receipt["rollover"]
    _require(analysis.get("mode") == "ALDI_A30_ROLLOVER_REVIEW_ANALYSIS_V01", "rollover analysis mode mismatch")
    _require(analysis.get("positional_visual_matched_pages") == 36, "analysis positional count mismatch")
    _require(analysis.get("exact_positional_matched_pages") == 36, "analysis exact positional count mismatch")
    _require(analysis.get("content_set_matched_pages") == 39, "analysis content-set count mismatch")
    _require(analysis.get("moved_pages") == expected_rollover["moved_pages"], "analysis moved-page mapping mismatch")
    _require(analysis.get("old_only_pages") == [37, 41], "analysis old-only pages mismatch")
    _require(analysis.get("new_only_pages") == [3, 41], "analysis new-only pages mismatch")
    _require(analysis.get("duplicate_content_groups") == [], "analysis duplicate groups mismatch")
    _require(analysis.get("manual_review_required") is True, "manual review must remain required")
    _require(analysis.get("strict_41_of_41_gate_unchanged") is True, "analysis strict gate changed")
    _require(analysis.get("automatic_promotion_allowed") is False, "analysis promotion must remain blocked")

    for moved in expected_rollover["moved_pages"]:
        row = current[moved["new_page"]]
        _require(row.get("sha256") == moved["sha256"], f"current moved-page SHA mismatch: {moved['new_page']}")
    descriptor = classes["new_current_page_3"]
    row = current[3]
    _require(row.get("sha256") == descriptor["sha256"], "new current page 3 report SHA mismatch")
    _require(int(row.get("bytes", -1)) == descriptor["bytes"], "new current page 3 report size mismatch")
    new41 = classes["information_page_41_change"]["new"]
    _require(current[41].get("sha256") == new41["sha256"], "new page 41 report SHA mismatch")
    _require(int(current[41].get("bytes", -1)) == new41["bytes"], "new page 41 report size mismatch")

    _require(manual.get("schema_version") == 1, "unexpected manual-review schema")
    _require(manual.get("mode") == "ALDI_A30_ROLLOVER_REVIEW_ANALYSIS_V01", "unexpected manual-review mode")
    _require(manual.get("classification") == "manual_review_required", "manual-review classification mismatch")
    _require(manual.get("exact_positional_matched_pages") == 36, "manual positional count mismatch")
    _require(manual.get("content_set_matched_pages") == 39, "manual content-set count mismatch")
    _require(manual.get("moved_pages") == expected_rollover["moved_pages"], "manual moved-page mapping mismatch")
    _require(manual.get("old_only_pages") == [37, 41], "manual old-only pages mismatch")
    _require(manual.get("new_only_pages") == [3, 41], "manual new-only pages mismatch")
    _require(manual.get("duplicate_content_groups") == [], "manual duplicate groups mismatch")
    _require(manual.get("automatic_promotion_allowed") is False, "manual promotion must remain blocked")

    manual_rows: dict[tuple[str, int], dict[str, Any]] = {}
    for label, field in (("old_preview", "old_preview_files"), ("new_current", "new_current_files")):
        rows = manual.get(field)
        _require(isinstance(rows, list), f"manual {field} must be a list")
        for item in rows:
            key = (label, int(item.get("page_number", 0)))
            _require(key not in manual_rows, "manual page evidence must be unique")
            manual_rows[key] = item

    expected_manual = {
        ("new_current", 3): classes["new_current_page_3"],
        ("old_preview", 37): classes["old_preview_page_37"],
        ("old_preview", 41): classes["information_page_41_change"]["old"],
        ("new_current", 41): classes["information_page_41_change"]["new"],
    }
    _require(set(manual_rows) == set(expected_manual), "manual page evidence set mismatch")
    for key, descriptor in expected_manual.items():
        item = manual_rows[key]
        _require(item.get("path") == descriptor["path"].removeprefix("evidence/"), f"manual path mismatch: {key}")
        _require(item.get("sha256") == descriptor["sha256"], f"manual SHA mismatch: {key}")
        _require(int(item.get("bytes", -1)) == descriptor["bytes"], f"manual byte-size mismatch: {key}")

    return {
        "schema_version": 1,
        "mode": MODE,
        "decision": "shadow_reconciliation_accepted",
        "run_id": artifact["run_id"],
        "artifact_id": artifact["artifact_id"],
        "registered_commit": artifact["registered_commit"],
        "current_page_count": 41,
        "preview_page_count": 41,
        "positional_visual_matched_pages": 36,
        "content_set_matched_pages": 39,
        "moved_page_count": 3,
        "strict_41_of_41_gate_unchanged": True,
        "automatic_promotion_allowed": False,
        "production_database_write": False,
        "production_deployment": False,
        "scheduler_installation": False,
        "b15m2_v08_action": False,
        "next_step_scope": "shadow_parser_and_parity_only",
    }


def reconcile_authoritative_artifact(
    receipt_path: Path,
    evidence_root: Path,
    artifact_sha256: str,
) -> dict[str, Any]:
    _require(artifact_sha256 == EXPECTED_ARTIFACT_SHA256, "artifact ZIP SHA mismatch")
    receipt = load_authoritative_receipt(receipt_path)

    evidence_descriptors = receipt["evidence"]
    manifest = _load_json_bytes(
        _verify_file(evidence_root, evidence_descriptors["dispatcher_manifest"]),
        "dispatcher manifest",
    )
    report = _load_json_bytes(
        _verify_file(evidence_root, evidence_descriptors["authoritative_report"]),
        "authoritative report",
    )
    manual = _load_json_bytes(
        _verify_file(evidence_root, evidence_descriptors["manual_review"]),
        "manual review",
    )

    classes = receipt["classifications"]
    for descriptor in (
        classes["new_current_page_3"],
        classes["old_preview_page_37"],
        classes["information_page_41_change"]["old"],
        classes["information_page_41_change"]["new"],
    ):
        _verify_file(evidence_root, descriptor)

    return validate_evidence_semantics(receipt, manifest, report, manual)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--artifact-sha256", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        result = reconcile_authoritative_artifact(
            args.receipt,
            args.evidence_root,
            args.artifact_sha256,
        )
    except (OSError, ReconciliationError) as exc:
        print("RESULT=ALDI_A30_ROLLOVER_RECONCILIATION_BLOCKED")
        print(f"ERROR={type(exc).__name__}: {exc}")
        return 2

    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    print("RESULT=ALDI_A30_ROLLOVER_RECONCILIATION_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
