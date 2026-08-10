from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest

TOOLS_DIR = Path(__file__).resolve().parents[2] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import netto_heldout_page_capture_v2 as capture_v2
from netto_heldout_ownership_protocol import ACCEPTANCE, freeze_receipt
from netto_heldout_ownership_protocol_v2 import EXPECTED_CANDIDATE_CONFIG, HeldoutV2Error
from netto_local_span_auto_single_candidate import STRATEGY as CANDIDATE_STRATEGY, payload_sha256
from netto_shadow_promotion import EvidenceBinding


SOURCE_ID = "a" * 64
PARSER_ID = "netto-visual-geometry-shadow-v3-unrotated-page-space"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _selector_envelope(campaign: str = "hz34_hasb") -> dict:
    binding = {
        "manifest_path": "/tmp/store-manifest.json",
        "manifest_sha256": "1" * 64,
        "html_path": "/tmp/store.html",
        "html_sha256": "2" * 64,
        "evidence_status": "pdf_bound",
        "pdf_path": "/tmp/prospect.pdf",
        "pdf_sha256": "3" * 64,
        "parser_identity": "netto_store_prospect_v1",
        "store_external_id": "5659",
        "scope": "family_primary_netto",
        "valid_from": "2026-08-17",
        "valid_until": "2026-08-22",
        "no_pdf_reason": None,
    }
    identity = EvidenceBinding.from_mapping(binding).identity_sha256()
    return {
        "schema_version": 1,
        "strategy": capture_v2.SELECTOR_STRATEGY,
        "as_of": "2026-08-16",
        "campaign_key": campaign,
        "campaign_window": {"start": "2026-08-17", "end": "2026-08-22"},
        "evidence_identity_sha256": identity,
        "binding": binding,
        "selection": {
            "scanned_json_count": 1,
            "eligible_manifest_count": 1,
            "latest_window_manifest_count": 1,
            "verified_latest_manifest_count": 1,
            "selected_manifest_name": "store-manifest.json",
            "fallback_to_older_campaign_allowed": False,
        },
        "review_only": True,
        "promotion_ready": False,
        "database_write_performed": False,
        "deployment_performed": False,
    }


def _fake_v1_capture(campaign: str):
    def fake(binding_payload, output: Path):
        output.mkdir(parents=True)
        source = {"fixture": "source", "campaign_key": campaign}
        predictions = {"fixture": "predictions", "campaign_key": campaign}
        _write(output / "source-evidence.json", source)
        _write(output / "predictions.json", predictions)
        source_sha = _sha(output / "source-evidence.json")
        predictions_sha = _sha(output / "predictions.json")
        manifest = {
            "schema_version": 1,
            "protocol": "netto-heldout-ownership-v1",
            "store_external_id": "5659",
            "campaign_key": campaign,
            "campaign_window": {"start": "2026-08-17", "end": "2026-08-22"},
            "source_sha256": SOURCE_ID,
            "parser_identity": PARSER_ID,
            "evidence_sha256": source_sha,
            "predictions_sha256": predictions_sha,
            "truth_sha256": None,
            "adjudication_sha256": None,
            "acceptance": dict(ACCEPTANCE),
            "ownership_classes": ["single_source", "mixed_source", "excluded_control"],
            "review_only": True,
            "promotion_ready": False,
        }
        receipt = freeze_receipt(manifest)
        _write(output / "freeze-manifest.json", manifest)
        _write(output / "freeze-receipt.json", receipt)
        _write(output / "blind-review-template.json", {"fixture": "blind", "campaign_key": campaign})
        (output / "SHA256SUMS").write_text("v1-checksum-manifest\n", encoding="utf-8")
        return {
            "campaign_key": campaign,
            "source_sha256": SOURCE_ID,
            "evidence_sha256": source_sha,
            "predictions_sha256": predictions_sha,
            "freeze_manifest_sha256": receipt["freeze_manifest_sha256"],
            "truth_available_at_freeze": False,
            "review_only": True,
            "promotion_ready": False,
        }
    return fake


def _fake_candidate(campaign: str):
    def fake(source, predictions, *, source_evidence_sha256: str, predictions_sha256: str):
        payload = {
            "schema_version": 1,
            "strategy": CANDIDATE_STRATEGY,
            "store_external_id": "5659",
            "scope": "family_primary_netto",
            "campaign_key": campaign,
            "campaign_window": {"start": "2026-08-17", "end": "2026-08-22"},
            "source_identity_sha256": SOURCE_ID,
            "source_pdf_sha256": "d" * 64,
            "prediction_parser_identity": PARSER_ID,
            "page_count": 1,
            "source_evidence_sha256": source_evidence_sha256,
            "predictions_sha256": predictions_sha256,
            "config": dict(EXPECTED_CANDIDATE_CONFIG),
            "prediction_group_count": 1,
            "parent_unit_count": 1,
            "candidate_auto_single_count": 1,
            "cross_parent_group_reuse_count": 0,
            "truth_used_for_candidate_construction": False,
            "automatic_candidate_decisions_frozen": True,
            "review_only": True,
            "promotion_ready": False,
            "parser_behavior_changed": False,
            "pages": [
                {
                    "page_number": 1,
                    "parent_units": [
                        {
                            "parent_unit_id": "p001-c001",
                            "prediction_unit_ids": ["p001-g001"],
                        }
                    ],
                    "groups": [
                        {
                            "prediction_unit_id": "p001-g001",
                            "parent_unit_ids": ["p001-c001"],
                            "primary_parent_unit_id": "p001-c001",
                            "candidate_auto_single": True,
                            "candidate_reasons": ["conservative_local_span_component_candidate"],
                        }
                    ],
                }
            ],
        }
        payload["candidate_provenance_sha256"] = payload_sha256(payload)
        return payload
    return fake


def test_selector_envelope_is_verified_and_unwrapped_before_v1_capture() -> None:
    envelope = _selector_envelope()
    direct, campaign = capture_v2._normalize_binding_payload(envelope)
    assert campaign == "hz34_hasb"
    assert "binding" not in direct
    assert direct == envelope["binding"]
    assert direct["valid_from"] == "2026-08-17"
    assert direct["valid_until"] == "2026-08-22"


def test_selector_envelope_fails_closed_on_identity_window_or_strategy_drift() -> None:
    envelope = _selector_envelope()
    envelope["evidence_identity_sha256"] = "f" * 64
    with pytest.raises(capture_v2.HeldoutCaptureV2Error, match="evidence identity mismatch"):
        capture_v2._normalize_binding_payload(envelope)

    envelope = _selector_envelope()
    envelope["campaign_window"]["start"] = "2026-08-18"
    with pytest.raises(capture_v2.HeldoutCaptureV2Error, match="campaign window mismatch"):
        capture_v2._normalize_binding_payload(envelope)

    envelope = _selector_envelope()
    envelope["strategy"] = "unexpected_selector"
    with pytest.raises(capture_v2.HeldoutCaptureV2Error, match="strategy mismatch"):
        capture_v2._normalize_binding_payload(envelope)


def test_v2_capture_passes_only_nested_binding_to_historical_v1(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "capture"
    seen: dict = {}
    base_fake = _fake_v1_capture("hz34_hasb")

    def capturing_fake(binding_payload, root: Path):
        seen.update(binding_payload)
        return base_fake(binding_payload, root)

    monkeypatch.setattr(capture_v2, "capture_heldout", capturing_fake)
    monkeypatch.setattr(capture_v2, "freeze_candidate", _fake_candidate("hz34_hasb"))
    capture_v2.capture_heldout_v2(_selector_envelope(), output)

    assert seen["valid_from"] == "2026-08-17"
    assert seen["valid_until"] == "2026-08-22"
    assert "binding" not in seen


def test_v2_capture_preserves_v1_members_and_adds_create_only_provenance(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "capture"
    monkeypatch.setattr(capture_v2, "capture_heldout", _fake_v1_capture("hz34_hasb"))
    monkeypatch.setattr(capture_v2, "freeze_candidate", _fake_candidate("hz34_hasb"))

    summary = capture_v2.capture_heldout_v2({}, output)

    assert summary["campaign_key"] == "hz34_hasb"
    assert summary["candidate_implementation_commit"] == capture_v2.CANDIDATE_IMPLEMENTATION_COMMIT
    assert summary["candidate_auto_single_count"] == 1
    assert summary["automatic_candidate_parent_reuse_count"] == 0
    assert summary["truth_available_at_freeze"] is False
    assert summary["candidate_decisions_frozen_before_truth"] is True
    assert summary["review_only"] is True
    assert summary["promotion_ready"] is False

    assert (output / "SHA256SUMS").read_text(encoding="utf-8") == "v1-checksum-manifest\n"
    for name in (
        "candidate-provenance.json",
        "freeze-manifest-v2.json",
        "freeze-receipt-v2.json",
        "SHA256SUMS.v2",
    ):
        assert (output / name).is_file()

    sums = (output / "SHA256SUMS.v2").read_text(encoding="utf-8")
    for name in capture_v2.V2_MEMBERS:
        assert f"  {name}\n" in sums
    receipt = json.loads((output / "freeze-receipt-v2.json").read_text(encoding="utf-8"))
    candidate = json.loads((output / "candidate-provenance.json").read_text(encoding="utf-8"))
    assert receipt["candidate_provenance_sha256"] == candidate["candidate_provenance_sha256"]
    assert receipt["truth_available_at_freeze"] is False


def test_v2_capture_rejects_exposed_hz33_and_removes_partial_output(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "capture"
    monkeypatch.setattr(capture_v2, "capture_heldout", _fake_v1_capture("hz33_hasb"))
    monkeypatch.setattr(capture_v2, "freeze_candidate", _fake_candidate("hz33_hasb"))

    with pytest.raises(HeldoutV2Error, match="overlaps exposed"):
        capture_v2.capture_heldout_v2({}, output)
    assert not output.exists()


def test_v2_capture_is_create_only(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "capture"
    output.mkdir()
    monkeypatch.setattr(capture_v2, "capture_heldout", _fake_v1_capture("hz34_hasb"))
    monkeypatch.setattr(capture_v2, "freeze_candidate", _fake_candidate("hz34_hasb"))
    with pytest.raises(capture_v2.HeldoutCaptureV2Error, match="must not already exist"):
        capture_v2.capture_heldout_v2({}, output)
