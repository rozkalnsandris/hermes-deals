"""Review-only normalization for PaddleOCR/Florence booklet recognition PoC."""
from hashlib import sha256
import json
from pathlib import Path
import sys

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from netto_booklet_recognition_poc import (
    RecognitionEvidenceError,
    _normalize_rect,
    attach_ocr_to_vision,
    build_manifest,
    build_page,
    florence_regions,
    ocr_price_clusters,
    paddle_text_regions,
)


def _paddle():
    return {
        "res": {
            "rec_texts": ["Milka Alpenmilch", "100 g", "0,99 €"],
            "rec_scores": [0.98, 0.91, 0.99],
            "rec_boxes": [
                [100, 100, 320, 140],
                [110, 150, 180, 180],
                [250, 180, 330, 230],
            ],
        }
    }


def _florence():
    return {
        "<DENSE_REGION_CAPTION>": {
            "bboxes": [[70, 60, 360, 280]],
            "labels": ["a chocolate bar product block"],
        }
    }


def test_paddle_normalizes_text_and_price_cluster_review_only():
    rows = paddle_text_regions(_paddle(), 1000, 1400)
    assert len(rows) == 3
    assert rows[0]["bbox"] == [0.1, 0.071429, 0.22, 0.028571]
    candidates = ocr_price_clusters(rows)
    assert len(candidates) == 1
    assert candidates[0]["price_anchor_text"] == "0,99 €"
    assert candidates[0]["state"] == "REVIEW_ONLY"
    assert candidates[0]["product_boundary_proven"] is False
    assert candidates[0]["verified_product_identity"] is None
    assert candidates[0]["hermes_offer_link"] is None


def test_florence_region_can_collect_ocr_without_proving_identity():
    ocr = paddle_text_regions(_paddle(), 1000, 1400)
    vision = florence_regions(_florence(), 1000, 1400)
    merged = attach_ocr_to_vision(vision, ocr)
    assert merged[0]["ocr_texts"] == ["Milka Alpenmilch", "100 g", "0,99 €"]
    assert merged[0]["product_boundary_proven"] is False
    assert merged[0]["verified_product_identity"] is None
    assert merged[0]["hermes_offer_link"] is None


def test_build_page_never_creates_offer_identity():
    page = build_page(7, 1000, 1400, _paddle(), _florence())
    assert page["page_number"] == 7
    assert page["automatic_offer_links"] == 0
    assert page["verified_product_identities"] == 0
    assert len(page["vision_regions"]) == 1


def test_bad_geometry_and_model_arrays_fail_closed():
    with pytest.raises(RecognitionEvidenceError, match="out-of-page"):
        _normalize_rect([0, 0, 1001, 100], 1000, 1400)
    with pytest.raises(RecognitionEvidenceError, match="nonnumeric"):
        _normalize_rect([True, 0, 100, 100], 1000, 1400)

    bad = _paddle()
    bad["res"]["rec_scores"] = [0.9]
    with pytest.raises(RecognitionEvidenceError, match="inconsistent"):
        paddle_text_regions(bad, 1000, 1400)

    bad = _florence()
    bad["<DENSE_REGION_CAPTION>"]["labels"] = []
    with pytest.raises(RecognitionEvidenceError, match="inconsistent"):
        florence_regions(bad, 1000, 1400)


def test_manifest_binds_exact_pdf_sha_store_validity_and_stays_review_only(tmp_path):
    pdf = tmp_path / "next-week.pdf"
    with fitz.open() as doc:
        page = doc.new_page(width=300, height=420)
        page.insert_text((30, 80), "Netto recognition test", fontsize=20)
        doc.save(pdf)
    digest = sha256(pdf.read_bytes()).hexdigest()
    model_results = {
        "pages": [
            {
                "page_number": 1,
                "image_width": 1000,
                "image_height": 1400,
                "paddle": _paddle(),
                "florence": _florence(),
            }
        ]
    }
    result = build_manifest(
        pdf,
        digest,
        model_results,
        store="5659",
        valid_from="2026-11-16",
        valid_to="2026-11-21",
        publication_url="https://example.invalid/netto/official-publication",
    )
    assert result["source_pdf_sha256"] == digest
    assert result["source_pdf_page_count"] == 1
    assert result["sample_page_count"] == 1
    assert result["automatic_offer_links"] == 0
    assert result["verified_product_identities"] == 0
    assert result["identity_policy"] == "REVIEW_ONLY_NO_VLM_OR_OCR_IDENTITY_PROMOTION"


def test_manifest_rejects_wrong_sha_store_duplicate_page_and_bad_url(tmp_path):
    pdf = tmp_path / "booklet.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.save(pdf)
    digest = sha256(pdf.read_bytes()).hexdigest()
    base = {
        "pages": [
            {
                "page_number": 1,
                "image_width": 100,
                "image_height": 100,
                "paddle": {"rec_texts": [], "rec_scores": [], "rec_boxes": []},
            }
        ]
    }
    with pytest.raises(RecognitionEvidenceError, match="SHA256 mismatch"):
        build_manifest(
            pdf,
            "0" * 64,
            base,
            store="5659",
            valid_from="2026-11-16",
            valid_to="2026-11-21",
            publication_url="https://example.invalid/netto",
        )
    with pytest.raises(RecognitionEvidenceError, match="store 5659"):
        build_manifest(
            pdf,
            digest,
            base,
            store="9999",
            valid_from="2026-11-16",
            valid_to="2026-11-21",
            publication_url="https://example.invalid/netto",
        )
    duplicate = json.loads(json.dumps(base))
    duplicate["pages"].append(dict(duplicate["pages"][0]))
    with pytest.raises(RecognitionEvidenceError, match="duplicate"):
        build_manifest(
            pdf,
            digest,
            duplicate,
            store="5659",
            valid_from="2026-11-16",
            valid_to="2026-11-21",
            publication_url="https://example.invalid/netto",
        )
    with pytest.raises(RecognitionEvidenceError, match="HTTPS"):
        build_manifest(
            pdf,
            digest,
            base,
            store="5659",
            valid_from="2026-11-16",
            valid_to="2026-11-21",
            publication_url="http://example.invalid/netto",
        )
