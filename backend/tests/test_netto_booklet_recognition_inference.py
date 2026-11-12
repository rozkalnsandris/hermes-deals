"""Tests for the local-only Netto booklet recognition inference runner."""
import base64
from hashlib import sha256
import json
from pathlib import Path
import sys

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from netto_booklet_recognition_inference import (
    InferenceRunnerError,
    _json_value,
    _read_pdf,
    native_page_structure,
    parse_pages,
    run_inference,
)


class FakePaddle:
    def predict_file(self, path: Path):
        assert path.is_file()
        return {
            "res": {
                "rec_texts": ["Milka", "0,99 €"],
                "rec_scores": [0.99, 0.98],
                "rec_boxes": [[10, 10, 90, 30], [100, 100, 150, 130]],
            }
        }


class FakeFlorence:
    def predict_png(self, png: bytes):
        assert png.startswith(b"\x89PNG")
        return {
            "<DENSE_REGION_CAPTION>": {
                "bboxes": [[5, 5, 180, 180]],
                "labels": ["a product offer"],
            }
        }


def _pdf_bytes(page_count=3):
    with fitz.open() as doc:
        for index in range(page_count):
            page = doc.new_page(width=300, height=420)
            page.insert_text((30, 70), f"Page {index + 1}", fontsize=18)
        return doc.tobytes()


def _native_pdf_bytes():
    image = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZQmcAAAAASUVORK5CYII="
    )
    with fitz.open() as doc:
        page = doc.new_page(width=300, height=420)
        page.insert_text((30, 70), "Milka 0,99", fontsize=18)
        page.insert_image(fitz.Rect(30, 100, 130, 200), stream=image)
        return doc.tobytes()


def test_parse_pages_is_bounded_sorted_and_unique():
    assert parse_pages("4,2,2,6-8", 10) == [2, 4, 6, 7, 8]
    with pytest.raises(InferenceRunnerError, match="descending"):
        parse_pages("8-6", 10)
    with pytest.raises(InferenceRunnerError, match="outside PDF"):
        parse_pages("11", 10)
    with pytest.raises(InferenceRunnerError, match="sample page count"):
        parse_pages("1-13", 20)
    with pytest.raises(InferenceRunnerError, match="malformed"):
        parse_pages("1,a", 10)


def test_read_pdf_requires_exact_sha_and_rejects_bad_size(tmp_path):
    pdf = tmp_path / "booklet.pdf"
    raw = _pdf_bytes()
    pdf.write_bytes(raw)
    digest = sha256(raw).hexdigest()
    assert _read_pdf(pdf, digest) == raw
    with pytest.raises(InferenceRunnerError, match="SHA256 mismatch"):
        _read_pdf(pdf, "0" * 64)
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    with pytest.raises(InferenceRunnerError, match="size outside"):
        _read_pdf(empty, sha256(b"").hexdigest())


def test_json_value_accepts_only_object_json():
    assert _json_value('{"res":{"rec_texts":[]}}') == {"res": {"rec_texts": []}}
    assert _json_value({"x": 1}) == {"x": 1}
    with pytest.raises(InferenceRunnerError, match="not a JSON object"):
        _json_value("[1,2]")
    with pytest.raises(InferenceRunnerError, match="malformed"):
        _json_value("{")


def test_run_inference_combines_backends_without_identity(tmp_path):
    raw = _pdf_bytes()
    result = run_inference(
        raw,
        [1, 3],
        paddle=FakePaddle(),
        florence=FakeFlorence(),
        render_dpi=144,
    )
    assert [row["page_number"] for row in result["pages"]] == [1, 3]
    assert all(row["image_width"] == 600 for row in result["pages"])
    assert all(row["image_height"] == 840 for row in result["pages"])
    assert result["pages"][0]["paddle"]["res"]["rec_texts"] == ["Milka", "0,99 €"]
    assert result["pages"][0]["florence"]["<DENSE_REGION_CAPTION>"]["labels"] == [
        "a product offer"
    ]
    assert all(row["runtime_seconds"] >= 0 for row in result["pages"])


def test_run_inference_requires_backend_and_bounded_dpi():
    raw = _pdf_bytes()
    with pytest.raises(InferenceRunnerError, match="backend"):
        run_inference(raw, [1], paddle=None, florence=None)
    for dpi in (95, 241):
        with pytest.raises(InferenceRunnerError, match="DPI"):
            run_inference(raw, [1], paddle=FakePaddle(), render_dpi=dpi)


def test_run_inference_rejects_noncanonical_or_out_of_range_pages():
    raw = _pdf_bytes()
    with pytest.raises(InferenceRunnerError, match="canonical"):
        run_inference(raw, [2, 1], paddle=FakePaddle())
    with pytest.raises(InferenceRunnerError, match="outside PDF"):
        run_inference(raw, [4], paddle=FakePaddle())


def test_model_json_shape_is_compatible_with_normalizer_contract():
    raw = _pdf_bytes(1)
    result = run_inference(
        raw,
        [1],
        paddle=FakePaddle(),
        florence=FakeFlorence(),
    )
    row = result["pages"][0]
    serialized = json.loads(json.dumps(result))
    assert serialized["pages"][0]["paddle"]["res"]["rec_boxes"][0] == [10, 10, 90, 30]
    assert row["florence"]["<DENSE_REGION_CAPTION>"]["bboxes"][0] == [5, 5, 180, 180]


def test_native_page_structure_extracts_review_only_source_geometry():
    raw = _native_pdf_bytes()
    with fitz.open(stream=raw, filetype="pdf") as doc:
        native = native_page_structure(doc[0])
    assert native["text_region_count"] >= 2
    assert native["image_region_count"] == 1
    assert native["price_candidate_count"] == 1
    assert native["price_candidates"][0]["text"] == "0,99"
    assert native["price_candidates"][0]["product_boundary_proven"] is False
    assert native["price_candidates"][0]["verified_product_identity"] is None
    assert native["automatic_offer_links"] == 0
    assert all(
        0 <= value <= 1
        for row in native["text_regions"] + native["image_regions"]
        for value in row["bbox"]
    )


def test_run_inference_allows_model_free_native_baseline():
    result = run_inference(
        _native_pdf_bytes(),
        [1],
        include_native=True,
        render_dpi=144,
    )
    row = result["pages"][0]
    assert "paddle" not in row
    assert "florence" not in row
    assert row["native"]["text_region_count"] >= 2
    assert row["native"]["image_region_count"] == 1
    assert row["native"]["verified_product_identities"] == 0