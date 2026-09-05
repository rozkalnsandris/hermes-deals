from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import netto_hz34_completed_source_card_truth as truth  # noqa: E402

WORKFLOW = ROOT / ".github" / "workflows" / "netto-hz34-completed-truth-import.yml"


def _dimensions() -> dict[int, tuple[float, float]]:
    return {page: (566.929, 737.008) for page in range(1, 71)}


def _payload() -> dict:
    pages = []
    for page in range(1, 71):
        rows = []
        if page == 1:
            rows = [{
                "source_region_id": "p001-r001",
                "rect_points": [10.0, 10.0, 110.0, 120.0],
                "scope_classification": "in_scope",
                "boundary_state": "clear_single_card",
                "observed_label": "source-only label",
                "reviewer_confidence": "high",
                "reviewer_note": None,
            }]
        pages.append({
            "page_number": page,
            "page_width_points": 566.929,
            "page_height_points": 737.008,
            "review_complete": True,
            "page_disposition": "source_regions_recorded" if rows else "no_target_source_regions",
            "source_regions": rows,
        })
    return {
        "schema_version": 1,
        "strategy": truth.STRATEGY,
        "campaign_key": truth.CAMPAIGN,
        "campaign_window": {"start": truth.VALID_FROM, "end": truth.VALID_UNTIL},
        "store_external_id": truth.STORE,
        "scope": truth.SCOPE,
        "source_sha256": truth.SOURCE_SHA256,
        "source_pdf_sha256": truth.PDF_SHA256,
        "freeze_manifest_sha256": truth.FREEZE_MANIFEST_SHA256,
        "review_pack_manifest_sha256": truth.REVIEW_PACK_MANIFEST_SHA256,
        "supersedes_blank_ledger_sha256": truth.BLANK_LEDGER_SHA256,
        "coordinate_space": "unrotated_page_points",
        "page_count": 70,
        "review_state": "completed_independent_source_truth_before_prediction_adjudication",
        "truth_unit": "independent_source_region",
        "source_scope_classes": ["in_scope", "excluded_non_target"],
        "boundary_states": ["clear_single_card", "partial_single_card"],
        "parser_predictions_included": False,
        "candidate_provenance_included": False,
        "expected_truth_included": False,
        "adjudication_started": False,
        "reviewer_process": {
            "review_pack_artifact_id": truth.REVIEW_PACK_ARTIFACT_ID,
            "review_pack_workflow_run_id": truth.REVIEW_PACK_RUN_ID,
            "review_pack_artifact": truth.REVIEW_PACK_ARTIFACT,
            "review_pack_artifact_digest": truth.REVIEW_PACK_ARTIFACT_DIGEST,
            "frozen_predictions_opened": False,
            "candidate_provenance_opened": False,
            "adjudication_started": False,
            "review_order": "pages_001_through_070_sequential",
        },
        "prediction_ownership_derivation": {
            "performed_during_source_review": False,
            "allowed_only_after_completed_truth_sha_is_frozen": True,
        },
        "pages": pages,
    }


def test_completed_truth_accepts_source_only_complete_pages() -> None:
    summary = truth.validate_truth_payload(_payload(), _dimensions())
    assert summary == {
        "page_count": 70,
        "source_region_count": 1,
        "in_scope_region_count": 1,
        "excluded_non_target_region_count": 0,
        "partial_single_card_count": 0,
        "empty_reviewed_page_count": 69,
    }


def test_completed_truth_rejects_prediction_or_candidate_leakage() -> None:
    payload = _payload()
    payload["pages"][0]["source_regions"][0]["production_eligible"] = True
    with pytest.raises(truth.Hz34CompletedTruthError, match="leaked into truth"):
        truth.validate_truth_payload(payload, _dimensions())


def test_completed_truth_rejects_unknown_schema_fields_at_every_level() -> None:
    payload = _payload()
    payload["candidate_hint"] = {"price": "9.99"}
    with pytest.raises(truth.Hz34CompletedTruthError, match="unknown completed truth fields"):
        truth.validate_truth_payload(payload, _dimensions())

    payload = _payload()
    payload["reviewer_process"]["candidate_visibility"] = False
    with pytest.raises(truth.Hz34CompletedTruthError, match="unknown completed truth fields"):
        truth.validate_truth_payload(payload, _dimensions())

    payload = _payload()
    payload["prediction_ownership_derivation"]["candidate_count"] = 0
    with pytest.raises(truth.Hz34CompletedTruthError, match="unknown completed truth fields"):
        truth.validate_truth_payload(payload, _dimensions())

    payload = _payload()
    payload["pages"][0]["candidate_summary"] = None
    with pytest.raises(truth.Hz34CompletedTruthError, match="unknown completed truth fields"):
        truth.validate_truth_payload(payload, _dimensions())

    payload = _payload()
    payload["pages"][0]["source_regions"][0]["candidate_score"] = 0.99
    with pytest.raises(truth.Hz34CompletedTruthError, match="unknown completed truth fields"):
        truth.validate_truth_payload(payload, _dimensions())


def test_completed_truth_rejects_overlap_and_unreviewed_empty_page() -> None:
    payload = _payload()
    payload["pages"][0]["source_regions"].append({
        "source_region_id": "p001-r002",
        "rect_points": [50.0, 50.0, 150.0, 160.0],
        "scope_classification": "excluded_non_target",
        "boundary_state": "partial_single_card",
        "observed_label": None,
        "reviewer_confidence": "medium",
        "reviewer_note": None,
    })
    with pytest.raises(truth.Hz34CompletedTruthError, match="rectangles overlap"):
        truth.validate_truth_payload(payload, _dimensions())

    payload = _payload()
    payload["pages"][1]["review_complete"] = False
    with pytest.raises(truth.Hz34CompletedTruthError, match="review_complete"):
        truth.validate_truth_payload(payload, _dimensions())


def test_workflow_is_exact_reviewer_pack_and_truth_only_gated() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "audit:netto-hz34-completed-source-truth-v1" in text
    assert 'REVIEW_PACK_ARTIFACT_ID: "9737495579"' in text
    assert 'REVIEW_PACK_RUN_ID: "33330445681"' in text
    assert "sha256:ba30feab1ed792ed62fc613acc2c1c1b06a43bfaa3754666170a98a4da1e5b32" in text
    assert "eff911a09ef343abda3c6c16922e998b4903ef0ccaa679a1423a83f26ffc43f3" in text
    assert "5e0dcb89d9cd957175e5c4bdcba5de1fb7c8075c1b16db9a139c20052e108d79" in text
    assert "cc50b5f49dd3f62618556832416dc2f694e023000664bbb145e9b2b3cdb2bad8" in text
    assert "9362894718" not in text
    assert "predictions.json" not in text
    assert "candidate-provenance.json" not in text
    assert "truth PR must change exactly the canonical completed truth file" in text
    assert "completed truth evidence is create-only" in text
    assert "Checkout trusted control plane from exact current main" in text
    assert "Checkout exact evidence PR head only after truth validation" in text
    assert 'os.environ["GITHUB_EVENT_PATH"]' in text
    assert 'EVENT_PATH: ${{ github.event_path }}' not in text
    assert 'git add -f -- "$EXPECTED_RECEIPT_PATH"' in text
    assert 'git add -- "$EXPECTED_RECEIPT_PATH"' not in text
    assert "production/DB/Review/deploy: **false**" in text
    assert "self-hosted" not in text
    assert "sudo " not in text
    assert "docker " not in text
