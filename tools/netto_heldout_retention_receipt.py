#!/usr/bin/env python3
"""Validate independent retention evidence for a frozen Netto held-out artifact.

This tool is deliberately source/storage agnostic. It never downloads, copies, opens, or
publishes the candidate artifact. It only validates a public-safe receipt against the
already-recorded frozen capture identities. A valid receipt is required before a future
held-out campaign may cross from capture-complete to heldout-eligible.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
OPAQUE_LOCATOR_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{2,255}$")


class ReceiptError(ValueError):
    pass


def _require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise ReceiptError(f"{field} must be a lowercase SHA256 hex digest")
    return value


def _require_nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReceiptError(f"{field} must be a non-empty string")
    return value


def _require_positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ReceiptError(f"{field} must be a positive integer")
    return value


def _parse_utc(value: Any, field: str) -> datetime:
    raw = _require_nonempty(value, field)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReceiptError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ReceiptError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def validate_receipt(capture: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
    if capture.get("schema_version") != 3:
        raise ReceiptError("capture schema_version must be 3")
    if capture.get("result") != "PASS":
        raise ReceiptError("capture result must be PASS")
    if capture.get("truth_available_at_freeze") is not False:
        raise ReceiptError("capture was not truth-blind")
    if capture.get("candidate_decisions_frozen_before_truth") is not True:
        raise ReceiptError("candidate decisions were not frozen before truth")
    if capture.get("independent_retention_verified") is not False:
        raise ReceiptError("capture must begin retention-unverified")
    if capture.get("heldout_eligible") is not False:
        raise ReceiptError("capture must begin heldout-ineligible")

    if receipt.get("schema") != "hermes.netto.heldout-independent-retention.v1":
        raise ReceiptError("unexpected retention receipt schema")
    if receipt.get("independent_copy_verified") is not True:
        raise ReceiptError("independent copy is not verified")
    if receipt.get("candidate_payload_opened") is not False:
        raise ReceiptError("retention verification must not open candidate payloads")

    expected_pairs = {
        "registered_commit": capture.get("registered_commit"),
        "campaign_key": capture.get("campaign_key"),
        "base_freeze_manifest_sha256": capture.get("base_freeze_manifest_sha256"),
        "v2_freeze_manifest_sha256": capture.get("v2_freeze_manifest_sha256"),
        "candidate_implementation_commit": capture.get("candidate_implementation_commit"),
        "candidate_file_sha256": capture.get("candidate_file_sha256"),
        "candidate_provenance_sha256": capture.get("candidate_provenance_sha256"),
        "candidate_decisions_sha256": capture.get("candidate_decisions_sha256"),
    }
    for field, expected in expected_pairs.items():
        if receipt.get(field) != expected:
            raise ReceiptError(f"{field} does not match frozen capture")

    artifact = receipt.get("actions_artifact")
    retained = receipt.get("independent_copy")
    if not isinstance(artifact, dict) or not isinstance(retained, dict):
        raise ReceiptError("actions_artifact and independent_copy objects are required")

    artifact_id = _require_positive_int(artifact.get("id"), "actions_artifact.id")
    run_id = _require_positive_int(artifact.get("workflow_run_id"), "actions_artifact.workflow_run_id")
    artifact_name = _require_nonempty(artifact.get("name"), "actions_artifact.name")
    artifact_sha = _require_sha256(artifact.get("zip_sha256"), "actions_artifact.zip_sha256")
    artifact_size = _require_positive_int(artifact.get("size_bytes"), "actions_artifact.size_bytes")

    retention_class = _require_nonempty(retained.get("retention_class"), "independent_copy.retention_class")
    if retention_class in {"github_actions_artifact", "runner_temp", "repository_worktree"}:
        raise ReceiptError("independent copy must use a genuinely independent retention class")
    locator = _require_nonempty(retained.get("opaque_locator"), "independent_copy.opaque_locator")
    if not OPAQUE_LOCATOR_RE.fullmatch(locator) or "?" in locator or "#" in locator:
        raise ReceiptError("opaque locator must be public-safe and contain no query/fragment")
    retained_sha = _require_sha256(retained.get("zip_sha256"), "independent_copy.zip_sha256")
    retained_size = _require_positive_int(retained.get("size_bytes"), "independent_copy.size_bytes")
    if retained_sha != artifact_sha or retained_size != artifact_size:
        raise ReceiptError("independent copy digest/size does not match Actions artifact bytes")

    verified_at = _parse_utc(receipt.get("verified_at"), "verified_at")
    retain_through = _parse_utc(retained.get("retain_through"), "independent_copy.retain_through")
    if retain_through <= verified_at:
        raise ReceiptError("independent retention horizon must be after verification")

    verifier = receipt.get("verifier")
    if not isinstance(verifier, dict):
        raise ReceiptError("verifier object is required")
    _require_nonempty(verifier.get("actor"), "verifier.actor")
    _require_nonempty(verifier.get("tool"), "verifier.tool")

    return {
        "schema": "hermes.netto.heldout-retention-validation.v1",
        "result": "PASS",
        "registered_commit": capture["registered_commit"],
        "campaign_key": capture["campaign_key"],
        "actions_artifact_id": artifact_id,
        "actions_workflow_run_id": run_id,
        "actions_artifact_name": artifact_name,
        "artifact_zip_sha256": artifact_sha,
        "artifact_size_bytes": artifact_size,
        "retention_class": retention_class,
        "retention_locator": locator,
        "retain_through": retained["retain_through"],
        "independent_retention_verified": True,
        "heldout_eligible": True,
        "candidate_payload_opened": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture_result", type=Path)
    parser.add_argument("retention_receipt", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    capture = json.loads(args.capture_result.read_text(encoding="utf-8"))
    receipt = json.loads(args.retention_receipt.read_text(encoding="utf-8"))
    result = validate_receipt(capture, receipt)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        if args.output.exists() or args.output.is_symlink():
            raise SystemExit("output must be create-only")
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
