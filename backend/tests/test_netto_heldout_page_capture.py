from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pymupdf
import pytest


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools/netto_heldout_page_capture.py"
SPEC = importlib.util.spec_from_file_location("netto_heldout_page_capture_tested", TOOL)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

capture_heldout = MODULE.capture_heldout
HeldoutCaptureError = MODULE.HeldoutCaptureError
PREDICTION_PARSER = MODULE.geometry.PARSER_IDENTITY
SOURCE_PARSER = "netto-heldout-source-fixture-v1"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_pdf(path: Path) -> None:
    doc = pymupdf.open()
    try:
        page1 = doc.new_page(width=300, height=400)
        page1.insert_text((30, 45), "Apfelsaft", fontsize=15)
        page1.insert_text((30, 95), "1,99", fontsize=22)
        page1.draw_rect(pymupdf.Rect(20, 20, 150, 125), color=(0, 0, 0), width=1)

        page2 = doc.new_page(width=300, height=400)
        page2.insert_text((35, 55), "Mineralwasser", fontsize=15)
        page2.insert_text((35, 105), "2,49", fontsize=22)
        page2.draw_line(pymupdf.Point(10, 180), pymupdf.Point(290, 180), color=(0, 0, 0), width=1)
        doc.save(path)
    finally:
        doc.close()


def binding(tmp_path: Path, *, campaign: str = "heldout_hz33") -> dict[str, object]:
    pdf = tmp_path / "source.pdf"
    html = tmp_path / "source.html"
    manifest = tmp_path / "source-manifest.json"
    write_pdf(pdf)
    html.write_text("<html>Netto store 5659</html>\n", encoding="utf-8")
    manifest_payload = {
        "strategy": "netto-heldout-source-fixture-v1",
        "store_external_id": "5659",
        "scope": "family_primary_netto",
        "prospect_slug": campaign,
        "valid_from": "2026-08-10",
        "valid_until": "2026-08-15",
        "prospect_pdf_sha256": sha(pdf),
    }
    manifest.write_text(json.dumps(manifest_payload, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "manifest_path": str(manifest),
        "manifest_sha256": sha(manifest),
        "html_path": str(html),
        "html_sha256": sha(html),
        "evidence_status": "pdf_bound",
        "pdf_path": str(pdf),
        "pdf_sha256": sha(pdf),
        "parser_identity": SOURCE_PARSER,
        "store_external_id": "5659",
        "scope": "family_primary_netto",
        "valid_from": "2026-08-10",
        "valid_until": "2026-08-15",
        "no_pdf_reason": None,
    }


def load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def verify_sha256s(root: Path) -> None:
    for line in (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        assert sha(root / name) == digest


def assert_no_truth_payload(value: object) -> None:
    if isinstance(value, dict):
        forbidden = {
            "expected_title",
            "expected_normal_price",
            "expected_primary_price_eur",
            "truth_sha256",
            "adjudication_sha256",
            "truth_rows",
            "cell_reviews",
        }
        assert not (forbidden & set(value))
        for child in value.values():
            assert_no_truth_payload(child)
    elif isinstance(value, list):
        for child in value:
            assert_no_truth_payload(child)


def test_capture_all_pages_is_deterministic_truth_blind_and_review_only(tmp_path: Path) -> None:
    source = binding(tmp_path)
    first = tmp_path / "capture-a"
    second = tmp_path / "capture-b"

    first_summary = capture_heldout(source, first)
    second_summary = capture_heldout(source, second)

    assert first_summary == second_summary
    assert first_summary["page_count"] == 2
    assert first_summary["prediction_parser_identity"] == PREDICTION_PARSER
    assert first_summary["truth_available_at_freeze"] is False
    assert first_summary["promotion_ready"] is False

    for name in (*MODULE.ARTIFACT_FILES, "SHA256SUMS"):
        assert (first / name).read_bytes() == (second / name).read_bytes()

    evidence = load(first / "source-evidence.json")
    predictions = load(first / "predictions.json")
    freeze = load(first / "freeze-manifest.json")
    receipt = load(first / "freeze-receipt.json")
    review = load(first / "blind-review-template.json")

    assert evidence["capture_scope"] == "all_pdf_pages"
    assert evidence["page_count"] == 2
    assert evidence["source_parser_identity"] == SOURCE_PARSER
    assert evidence["prediction_parser_identity"] == PREDICTION_PARSER
    assert evidence["truth_included"] is False
    assert evidence["expected_metadata_included"] is False
    assert evidence["review_labels_included"] is False
    assert [row["page_number"] for row in evidence["pages"]] == [1, 2]  # type: ignore[index]

    assert predictions["page_count"] == 2
    assert predictions["prediction_parser_identity"] == PREDICTION_PARSER
    assert predictions["truth_included"] is False
    assert predictions["review_only"] is True
    assert predictions["promotion_ready"] is False
    evidence_layouts = {
        row["page_number"]: row["layout_sha256"] for row in evidence["pages"]  # type: ignore[index]
    }
    prediction_layouts = {
        row["page_number"]: row["layout_sha256"] for row in predictions["pages"]  # type: ignore[index]
    }
    assert prediction_layouts == evidence_layouts

    assert freeze["campaign_key"] == "heldout_hz33"
    assert freeze["parser_identity"] == PREDICTION_PARSER
    assert freeze["parser_identity"] != SOURCE_PARSER
    assert freeze["truth_sha256"] is None
    assert freeze["adjudication_sha256"] is None
    assert receipt["truth_available_at_freeze"] is False

    assert review["parser_predictions_included"] is False
    assert review["expected_truth_included"] is False
    assert review["review_status"] == "blank_before_independent_review"
    assert all(row["source_cards"] == [] for row in review["pages"])  # type: ignore[index]

    assert_no_truth_payload(evidence)
    assert_no_truth_payload(predictions)
    verify_sha256s(first)


def test_capture_rejects_existing_evaluation_campaign_before_output(tmp_path: Path) -> None:
    source = binding(tmp_path, campaign="hz32_hasb")
    output = tmp_path / "capture"
    with pytest.raises(HeldoutCaptureError, match="overlaps the existing evaluation corpus"):
        capture_heldout(source, output)
    assert not output.exists()


def test_capture_rejects_tampered_pdf_before_output(tmp_path: Path) -> None:
    source = binding(tmp_path)
    Path(str(source["pdf_path"])).write_bytes(b"tampered")
    output = tmp_path / "capture"
    with pytest.raises(HeldoutCaptureError, match="not verified"):
        capture_heldout(source, output)
    assert not output.exists()


def test_capture_is_create_only(tmp_path: Path) -> None:
    source = binding(tmp_path)
    output = tmp_path / "capture"
    output.mkdir()
    sentinel = output / "sentinel.txt"
    sentinel.write_text("keep\n", encoding="utf-8")

    with pytest.raises(HeldoutCaptureError, match="must not already exist"):
        capture_heldout(source, output)
    assert sentinel.read_text(encoding="utf-8") == "keep\n"


def test_capture_does_not_depend_on_n9_n10_truth_contracts() -> None:
    text = TOOL.read_text(encoding="utf-8")
    assert "n9_full_visual" not in text
    assert "n10_full_visual" not in text
    assert "expected_primary_price" not in text
    assert "expected_title" not in text
