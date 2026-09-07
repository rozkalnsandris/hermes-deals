from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REVIEW_WORKFLOW = ROOT / ".github" / "workflows" / "netto-hz37-blind-review-pack.yml"
TRUTH_WORKFLOW = ROOT / ".github" / "workflows" / "netto-hz37-completed-truth-import.yml"
VALIDATOR = ROOT / "tools" / "netto_hz37_completed_source_truth.py"
RETENTION = ROOT / "audit" / "netto" / "hz37" / "independent-retention-receipt.json"


def test_retention_receipt_is_exact_public_safe_binding() -> None:
    raw = RETENTION.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "7e38d310c7da1766f7fa6d536f68e8902d6bb67b2144e1838760e3557fbfedff"
    payload = json.loads(raw)
    assert payload["schema"] == "hermes.netto.heldout-independent-retention.v1"
    assert payload["campaign_key"] == "hz37_hasb"
    assert payload["registered_commit"] == "fbe3cfa143788607446d0095ae1f887354d10eb3"
    assert payload["independent_copy_verified"] is True
    assert payload["candidate_payload_opened"] is False
    assert payload["actions_artifact"]["id"] == 10022687292
    assert payload["independent_copy"]["retention_class"] == "owner_side_retained_filesystem"


def test_hz37_validator_binds_exact_frozen_source_and_dynamic_safe_pack() -> None:
    text = VALIDATOR.read_text(encoding="utf-8")
    for value in (
        'CAMPAIGN = "hz37_hasb"',
        'STORE = "5659"',
        'SCOPE = "family_primary_netto"',
        'VALID_FROM = "2026-09-07"',
        'VALID_UNTIL = "2026-09-12"',
        'SOURCE_SHA256 = "7b5b04bcf4af5c51f6ddfbd40096595e8a6da9cd7dd701c2d11b2916e0cd7951"',
        'PDF_SHA256 = "7da859b19345891538521d2ec3b0be75fb9b2a2675626a6dbd942f15f1356322"',
        'EXPECTED_PAGES = 73',
    ):
        assert value in text
    assert "review_pack_artifact_id" in text
    assert "review_pack_artifact_digest" in text
    assert "candidate_provenance_payload_parsed" in text
    assert "base.validate_truth_file" in text


def test_reviewer_pack_workflow_preserves_blindness_and_retention_gate() -> None:
    text = REVIEW_WORKFLOW.read_text(encoding="utf-8")
    assert "audit:netto-hz37-blind-review-pack-v1" in text
    assert "RETENTION_RECEIPT_SHA256: 7e38d310c7da1766f7fa6d536f68e8902d6bb67b2144e1838760e3557fbfedff" in text
    assert "UPSTREAM_ARTIFACT_ID: \"10022687292\"" in text
    assert "UPSTREAM_ARTIFACT_DIGEST: sha256:6a6394e91df0aab2681f7c042397cc4c572f4254e3f7df008840165f97cae2dc" in text
    assert "tools/netto_heldout_blind_artifact_pack.py" in text
    assert "candidate-side member leaked into reviewer pack" in text
    assert "independent_copy_verified" in text
    assert "candidate_payload_opened" in text
    assert "truth/adjudication started: **false**" in text


def test_completed_truth_workflow_accepts_only_truth_file_and_safe_pack() -> None:
    text = TRUTH_WORKFLOW.read_text(encoding="utf-8")
    assert "audit:netto-hz37-completed-source-truth-v1" in text
    assert "EXPECTED_TRUTH_PATH: audit/netto/hz37/completed-source-truth.json" in text
    assert "truth PR must create only the canonical completed truth file" in text
    assert "truth PR base is not exact current main" in text
    assert "review-pack artifact metadata mismatch" in text
    assert "netto-hz37-blind-review-pack-" in text
    assert "frozen_predictions_opened" in text
    assert "candidate_provenance_opened" in text
    assert "adjudication_started" in text
    assert "git push origin \"HEAD:${EXPECTED_HEAD_REF}\"" in text


def test_source_runtime_pr_scope_is_exact_and_no_live_trigger_is_automatic() -> None:
    text = REVIEW_WORKFLOW.read_text(encoding="utf-8")
    expected_paths = {
        ".github/workflows/netto-hz37-blind-review-pack.yml",
        ".github/workflows/netto-hz37-completed-truth-import.yml",
        "audit/netto/hz37/independent-retention-receipt.json",
        "backend/tests/test_netto_hz37_truth_boundary.py",
        "tools/netto_hz37_completed_source_truth.py",
    }
    for path in expected_paths:
        assert path in text
    assert "pull_request_target:" in text
    assert "types: [labeled]" in text
    assert "workflow_dispatch" not in text
