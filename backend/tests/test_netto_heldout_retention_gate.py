from __future__ import annotations

from copy import deepcopy
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "netto_heldout_retention_receipt.py"
CAPTURE = ROOT / "tools" / "run-netto-heldout-github-capture-v02.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "netto-heldout-github-capture-v2.yml"

spec = spec_from_file_location("netto_heldout_retention_receipt", TOOL)
assert spec and spec.loader
retention = module_from_spec(spec)
spec.loader.exec_module(retention)

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64


def capture_result() -> dict[str, object]:
    return {
        "schema_version": 3,
        "result": "PASS",
        "registered_commit": "1" * 40,
        "campaign_key": "future-source-proven-campaign",
        "base_freeze_manifest_sha256": SHA_A,
        "v2_freeze_manifest_sha256": SHA_B,
        "candidate_implementation_commit": "2" * 40,
        "candidate_file_sha256": SHA_C,
        "candidate_provenance_sha256": SHA_D,
        "candidate_decisions_sha256": SHA_E,
        "truth_available_at_freeze": False,
        "candidate_decisions_frozen_before_truth": True,
        "independent_retention_verified": False,
        "heldout_eligible": False,
    }


def retention_receipt() -> dict[str, object]:
    capture = capture_result()
    return {
        "schema": "hermes.netto.heldout-independent-retention.v1",
        "registered_commit": capture["registered_commit"],
        "campaign_key": capture["campaign_key"],
        "base_freeze_manifest_sha256": capture["base_freeze_manifest_sha256"],
        "v2_freeze_manifest_sha256": capture["v2_freeze_manifest_sha256"],
        "candidate_implementation_commit": capture["candidate_implementation_commit"],
        "candidate_file_sha256": capture["candidate_file_sha256"],
        "candidate_provenance_sha256": capture["candidate_provenance_sha256"],
        "candidate_decisions_sha256": capture["candidate_decisions_sha256"],
        "actions_artifact": {
            "id": 12345,
            "workflow_run_id": 67890,
            "name": "netto-heldout-v2-example",
            "zip_sha256": SHA_F,
            "size_bytes": 35113989,
        },
        "independent_copy": {
            "retention_class": "offline_archive",
            "opaque_locator": "vault:netto/heldout/run-67890",
            "zip_sha256": SHA_F,
            "size_bytes": 35113989,
            "retain_through": "2027-03-01T00:00:00Z",
        },
        "verified_at": "2026-09-03T17:00:00Z",
        "verifier": {"actor": "owner", "tool": "sha256sum"},
        "independent_copy_verified": True,
        "candidate_payload_opened": False,
    }


def test_valid_receipt_unlocks_only_retention_gate() -> None:
    result = retention.validate_receipt(capture_result(), retention_receipt())
    assert result["result"] == "PASS"
    assert result["independent_retention_verified"] is True
    assert result["heldout_eligible"] is True
    assert result["candidate_payload_opened"] is False
    assert result["artifact_zip_sha256"] == SHA_F


@pytest.mark.parametrize("retention_class", ["github_actions_artifact", "runner_temp", "repository_worktree"])
def test_non_independent_storage_is_rejected(retention_class: str) -> None:
    receipt = retention_receipt()
    receipt["independent_copy"]["retention_class"] = retention_class  # type: ignore[index]
    with pytest.raises(retention.ReceiptError, match="genuinely independent"):
        retention.validate_receipt(capture_result(), receipt)


def test_byte_identity_mismatch_is_rejected() -> None:
    receipt = retention_receipt()
    receipt["independent_copy"]["zip_sha256"] = SHA_A  # type: ignore[index]
    with pytest.raises(retention.ReceiptError, match="digest/size"):
        retention.validate_receipt(capture_result(), receipt)


def test_candidate_identity_mismatch_is_rejected() -> None:
    receipt = retention_receipt()
    receipt["candidate_provenance_sha256"] = SHA_A
    with pytest.raises(retention.ReceiptError, match="candidate_provenance_sha256"):
        retention.validate_receipt(capture_result(), receipt)


def test_retention_horizon_must_follow_verification() -> None:
    receipt = retention_receipt()
    receipt["independent_copy"]["retain_through"] = "2026-09-03T16:59:59Z"  # type: ignore[index]
    with pytest.raises(retention.ReceiptError, match="retention horizon"):
        retention.validate_receipt(capture_result(), receipt)


def test_capture_contract_is_fail_closed_pending_retention() -> None:
    text = CAPTURE.read_text(encoding="utf-8")
    assert '"schema_version": 3' in text
    assert '"independent_retention_verified": False' in text
    assert '"heldout_eligible": False' in text
    assert '"retention_gate": "BLOCKED_PENDING_INDEPENDENT_COPY_RECEIPT"' in text
    assert "HELDOUT_ELIGIBLE=false" in text


def test_workflow_reports_transient_artifact_as_not_heldout_eligible() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "tools/netto_heldout_retention_receipt.py" in text
    assert "retention-days: 14" in text
    assert "artifact-id" in text
    assert "artifact-digest" in text
    assert "Independent retention verified: **false**" in text
    assert "Held-out eligible: **false**" in text
    assert "separate retained-evidence authorization" in text
