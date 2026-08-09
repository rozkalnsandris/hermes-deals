from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools/netto_heldout_ownership_protocol.py"
SPEC = importlib.util.spec_from_file_location("netto_heldout_ownership_protocol_tested", TOOL)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

ACCEPTANCE = MODULE.ACCEPTANCE
OWNERSHIP_CLASSES = MODULE.OWNERSHIP_CLASSES
PROTOCOL_NAME = MODULE.PROTOCOL_NAME
adjudication_binding = MODULE.adjudication_binding
freeze_receipt = MODULE.freeze_receipt
prepare_freeze = MODULE.prepare_freeze
protocol_digest = MODULE.protocol_digest
validate_freeze_manifest = MODULE.validate_freeze_manifest


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest() -> dict[str, object]:
    return {
        "schema_version": 1,
        "protocol": PROTOCOL_NAME,
        "store_external_id": "5659",
        "campaign_key": "heldout_future_campaign",
        "campaign_window": {"start": "2026-08-10", "end": "2026-08-15"},
        "source_sha256": SHA_A,
        "parser_identity": "netto-heldout-shadow-candidate-v1",
        "evidence_sha256": SHA_B,
        "predictions_sha256": SHA_C,
        "truth_sha256": None,
        "adjudication_sha256": None,
        "acceptance": deepcopy(ACCEPTANCE),
        "ownership_classes": list(OWNERSHIP_CLASSES),
        "review_only": True,
        "promotion_ready": False,
    }


def verified_binding(tmp_path: Path, *, store: str = "5659") -> dict[str, object]:
    source_manifest = tmp_path / "source-manifest.json"
    html = tmp_path / "source.html"
    pdf = tmp_path / "source.pdf"
    source_manifest.write_text('{"source":"netto"}\n', encoding="utf-8")
    html.write_text("<html>verified store source</html>\n", encoding="utf-8")
    pdf.write_bytes(b"%PDF-1.7\nheld-out-source\n")
    return {
        "manifest_path": str(source_manifest),
        "manifest_sha256": digest(source_manifest),
        "html_path": str(html),
        "html_sha256": digest(html),
        "evidence_status": "pdf_bound",
        "pdf_path": str(pdf),
        "pdf_sha256": digest(pdf),
        "parser_identity": "netto-visual-geometry-shadow-v3-unrotated-page-space",
        "store_external_id": store,
        "scope": "family_primary_netto",
        "valid_from": "2026-08-10",
        "valid_until": "2026-08-15",
        "no_pdf_reason": None,
    }


def test_freeze_is_deterministic_and_truth_blind() -> None:
    payload = manifest()
    first = freeze_receipt(payload)
    second = freeze_receipt(deepcopy(payload))

    assert first == second
    assert first["freeze_manifest_sha256"] == protocol_digest(payload)
    assert first["truth_available_at_freeze"] is False
    assert first["review_only"] is True
    assert first["promotion_ready"] is False
    assert "truth_sha256" not in first
    assert "adjudication_sha256" not in first


def test_existing_evaluation_campaigns_cannot_be_reused_as_holdout() -> None:
    for campaign_key in ("hz31_hasb_4", "hz32_hasb"):
        payload = manifest()
        payload["campaign_key"] = campaign_key
        with pytest.raises(ValueError, match="overlaps the existing evaluation corpus"):
            validate_freeze_manifest(payload)


def test_truth_or_adjudication_before_freeze_fails_closed() -> None:
    for key in ("truth_sha256", "adjudication_sha256"):
        payload = manifest()
        payload[key] = SHA_D
        with pytest.raises(ValueError, match="must be absent before evidence freeze"):
            freeze_receipt(payload)


def test_acceptance_contract_cannot_be_relaxed_at_freeze() -> None:
    payload = manifest()
    payload["acceptance"]["minimum_auto_single_precision"] = 0.5  # type: ignore[index]
    with pytest.raises(ValueError, match="acceptance contract drift"):
        freeze_receipt(payload)


def test_adjudication_binds_later_truth_to_exact_frozen_predictions() -> None:
    payload = manifest()
    receipt = freeze_receipt(payload)
    binding = adjudication_binding(payload, receipt, SHA_D, SHA_E)

    assert binding["freeze_manifest_sha256"] == receipt["freeze_manifest_sha256"]
    assert binding["predictions_sha256"] == SHA_C
    assert binding["truth_sha256"] == SHA_D
    assert binding["adjudication_sha256"] == SHA_E
    assert binding["truth_available_at_freeze"] is False
    assert binding["promotion_ready"] is False


def test_prediction_or_protocol_drift_after_freeze_is_rejected() -> None:
    payload = manifest()
    receipt = freeze_receipt(payload)
    mutated = deepcopy(payload)
    mutated["predictions_sha256"] = SHA_D

    with pytest.raises(ValueError, match="freeze receipt does not match"):
        adjudication_binding(mutated, receipt, SHA_D, SHA_E)


def test_store_and_review_only_boundaries_fail_closed() -> None:
    payload = manifest()
    payload["store_external_id"] = "6071"
    with pytest.raises(ValueError, match="store 5659"):
        freeze_receipt(payload)

    payload = manifest()
    payload["promotion_ready"] = True
    with pytest.raises(ValueError, match="Review-only and non-promotable"):
        freeze_receipt(payload)


def test_prepare_freeze_hashes_verified_pdf_binding_before_truth(tmp_path: Path) -> None:
    binding = verified_binding(tmp_path)
    evidence = tmp_path / "object-evidence.json"
    predictions = tmp_path / "predictions.json"
    evidence.write_text('{"object_graph":[]}\n', encoding="utf-8")
    predictions.write_text('{"predictions":[]}\n', encoding="utf-8")

    frozen, receipt = prepare_freeze(binding, "heldout_hz33", evidence, predictions)
    expected_source_identity = MODULE.EvidenceBinding.from_mapping(binding).identity_sha256()

    assert frozen["store_external_id"] == "5659"
    assert frozen["campaign_key"] == "heldout_hz33"
    assert frozen["campaign_window"] == {"start": "2026-08-10", "end": "2026-08-15"}
    assert frozen["source_sha256"] == expected_source_identity
    assert frozen["source_sha256"] != binding["pdf_sha256"]
    assert frozen["evidence_sha256"] == digest(evidence)
    assert frozen["predictions_sha256"] == digest(predictions)
    assert frozen["truth_sha256"] is None
    assert frozen["adjudication_sha256"] is None
    assert receipt == freeze_receipt(frozen)
    assert receipt["truth_available_at_freeze"] is False


def test_prepare_freeze_rejects_wrong_store_before_freeze(tmp_path: Path) -> None:
    binding = verified_binding(tmp_path, store="6071")
    evidence = tmp_path / "evidence.json"
    predictions = tmp_path / "predictions.json"
    evidence.write_text("{}\n", encoding="utf-8")
    predictions.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must be 5659"):
        prepare_freeze(binding, "heldout_hz33", evidence, predictions)


def test_prepare_freeze_requires_verified_pdf_source(tmp_path: Path) -> None:
    binding = verified_binding(tmp_path)
    binding["evidence_status"] = "verified_no_pdf"
    binding["pdf_path"] = None
    binding["pdf_sha256"] = None
    binding["no_pdf_reason"] = "official source did not publish a PDF"
    evidence = tmp_path / "evidence.json"
    predictions = tmp_path / "predictions.json"
    evidence.write_text("{}\n", encoding="utf-8")
    predictions.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="requires pdf_bound evidence"):
        prepare_freeze(binding, "heldout_hz33", evidence, predictions)


def test_prepare_freeze_rejects_tampered_bound_source(tmp_path: Path) -> None:
    binding = verified_binding(tmp_path)
    Path(str(binding["pdf_path"])).write_bytes(b"tampered")
    evidence = tmp_path / "evidence.json"
    predictions = tmp_path / "predictions.json"
    evidence.write_text("{}\n", encoding="utf-8")
    predictions.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="not verified"):
        prepare_freeze(binding, "heldout_hz33", evidence, predictions)


def test_prepare_freeze_rejects_reused_evidence_prediction_file(tmp_path: Path) -> None:
    binding = verified_binding(tmp_path)
    same = tmp_path / "same.json"
    same.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="separate frozen files"):
        prepare_freeze(binding, "heldout_hz33", same, same)


def test_prepare_freeze_still_rejects_existing_evaluation_campaign(tmp_path: Path) -> None:
    binding = verified_binding(tmp_path)
    evidence = tmp_path / "evidence.json"
    predictions = tmp_path / "predictions.json"
    evidence.write_text("{}\n", encoding="utf-8")
    predictions.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="overlaps the existing evaluation corpus"):
        prepare_freeze(binding, "hz32_hasb", evidence, predictions)
