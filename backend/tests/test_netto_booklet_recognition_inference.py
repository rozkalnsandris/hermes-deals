"""Tests for the local-only Netto booklet recognition inference runner."""
from hashlib import sha256
import json
import struct
import zlib
from pathlib import Path
import sys

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from netto_booklet_recognition_inference import (
    InferenceRunnerError,
    _json_value,
    _normalized_bbox,
    _normalized_visible_image_bbox,
    _date_price_region_ids,
    _native_layout_regions,
    _native_product_card_candidates,
    _native_price_text_candidates,
    _product_text_block,
    _filter_ambiguous_product_cards,
    _read_pdf,
    _validate_florence_generation,
    native_page_structure,
    parse_florence_price_regions,
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


def _png_1x1():
    def chunk(kind, payload):
        body = kind + payload
        return (
            struct.pack(">I", len(payload))
            + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
        + chunk(b"IEND", b"")
    )


def _native_pdf_bytes():
    image = _png_1x1()
    with fitz.open() as doc:
        page = doc.new_page(width=300, height=420)
        page.insert_text((30, 70), "Milka 0,99", fontsize=18)
        page.insert_image(fitz.Rect(30, 100, 130, 200), stream=image)
        return doc.tobytes()


def _native_price_scale_pdf_bytes():
    with fitz.open() as doc:
        page = doc.new_page(width=300, height=420)
        page.insert_text((30, 70), "Milka", fontsize=12)
        page.insert_text((30, 120), "0,99", fontsize=28)
        page.insert_text((100, 120), "2,79", fontsize=8)
        page.insert_text((180, 70), "Butter", fontsize=12)
        page.insert_text((180, 120), "1,99", fontsize=28)
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
    assert native["primary_price_candidate_count"] == 1
    assert native["price_anchor_candidate_count"] == 1
    assert native["price_candidates"][0]["text"] == "0,99"
    assert native["primary_price_candidates"][0]["text"] == "0,99"
    candidate = native["price_anchor_candidates"][0]
    assert candidate["price_region_id"] == native["price_candidates"][0]["region_id"]
    assert candidate["price_text"] == "0,99"
    assert candidate["product_boundary_proven"] is False
    assert candidate["verified_product_identity"] is None
    assert candidate["hermes_offer_link"] is None
    assert candidate["state"] == "REVIEW_ONLY"
    assert "Milka" in candidate["native_text"]
    assert candidate["price_region_id"] in candidate["native_text_region_ids"]
    assert all(0 <= value <= 1 for value in candidate["crop_bbox"])
    assert native["price_candidates"][0]["product_boundary_proven"] is False
    assert native["price_candidates"][0]["verified_product_identity"] is None
    assert native["automatic_offer_links"] == 0
    assert all(
        0 <= value <= 1
        for row in native["text_regions"] + native["image_regions"]
        for value in row["bbox"]
    )


def test_native_primary_prices_filter_small_reference_price_and_group_nearest_text():
    raw = _native_price_scale_pdf_bytes()
    with fitz.open(stream=raw, filetype="pdf") as doc:
        native = native_page_structure(doc[0])

    assert native["price_candidate_count"] == 3
    assert native["primary_price_candidate_count"] == 2
    assert [row["text"] for row in native["primary_price_candidates"]] == ["0,99", "1,99"]
    assert native["price_anchor_candidate_count"] == 2

    by_price = {row["price_text"]: row for row in native["price_anchor_candidates"]}
    assert "Milka" in by_price["0,99"]["native_text"]
    assert "Butter" not in by_price["0,99"]["native_text"]
    assert "Butter" in by_price["1,99"]["native_text"]
    assert "Milka" not in by_price["1,99"]["native_text"]
    assert by_price["0,99"]["basis"] == "native_pdf_nearest_primary_price_group_v2"
    assert by_price["0,99"]["product_boundary_proven"] is False
    assert by_price["0,99"]["verified_product_identity"] is None
    assert by_price["0,99"]["hermes_offer_link"] is None
    assert all(0 <= value <= 1 for value in by_price["0,99"]["crop_bbox"])


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


def test_florence_generation_limits_are_bounded_for_rpi5():
    assert _validate_florence_generation(384, 1) == (384, 1)
    for tokens in (63, 2049):
        with pytest.raises(InferenceRunnerError, match="max_new_tokens"):
            _validate_florence_generation(tokens, 1)
    for beams in (0, 6):
        with pytest.raises(InferenceRunnerError, match="num_beams"):
            _validate_florence_generation(384, beams)


def test_parse_florence_price_regions_is_explicit_bounded_and_unique():
    assert parse_florence_price_regions(None) is None
    assert parse_florence_price_regions(
        ["20:native-word-57", "60:native-word-18"]
    ) == {
        20: {"native-word-57"},
        60: {"native-word-18"},
    }
    with pytest.raises(InferenceRunnerError, match="malformed"):
        parse_florence_price_regions(["20:vision-1"])
    with pytest.raises(InferenceRunnerError, match="duplicate"):
        parse_florence_price_regions(["20:native-word-57", "20:native-word-57"])
    with pytest.raises(InferenceRunnerError, match="count outside"):
        parse_florence_price_regions(
            [f"1:native-word-{index}" for index in range(1, 14)]
        )


def test_run_inference_can_target_florence_to_native_price_crop():
    raw = _native_pdf_bytes()
    with fitz.open(stream=raw, filetype="pdf") as doc:
        price_region_id = native_page_structure(doc[0])["price_candidates"][0]["region_id"]

    result = run_inference(
        raw,
        [1],
        florence=FakeFlorence(),
        render_dpi=144,
        florence_price_regions={1: {price_region_id}},
    )
    row = result["pages"][0]
    assert "florence" not in row
    assert row["native"]["price_anchor_candidate_count"] == 1
    assert len(row["florence_price_crops"]) == 1
    crop = row["florence_price_crops"][0]
    assert crop["price_region_id"] == price_region_id
    assert crop["product_boundary_proven"] is False
    assert crop["verified_product_identity"] is None
    assert crop["hermes_offer_link"] is None
    assert crop["florence"]["<DENSE_REGION_CAPTION>"]["labels"] == [
        "a product offer"
    ]


def test_run_inference_rejects_unknown_florence_price_anchor():
    with pytest.raises(InferenceRunnerError, match="not a native price anchor"):
        run_inference(
            _native_pdf_bytes(),
            [1],
            florence=FakeFlorence(),
            florence_price_regions={1: {"native-word-999"}},
        )


def test_native_image_bbox_clips_visible_intersection_to_page():
    assert _normalized_visible_image_bbox(
        [-22.5, -39.3, 581.1, 866.1],
        566.929,
        793.701,
    ) == [0.0, 0.0, 1.0, 1.0]
    assert _normalized_visible_image_bbox(
        [450.0, 400.0, 600.0, 520.0],
        566.929,
        793.701,
    ) == [0.79375, 0.503968, 0.20625, 0.15119]


def test_native_image_bbox_rejects_nonintersecting_or_degenerate_rectangles():
    with pytest.raises(InferenceRunnerError, match="does not intersect"):
        _normalized_visible_image_bbox([-20, 10, -1, 50], 300, 420)
    with pytest.raises(InferenceRunnerError, match="degenerate"):
        _normalized_visible_image_bbox([10, 10, 10, 50], 300, 420)
    with pytest.raises(InferenceRunnerError, match="invalid"):
        _normalized_visible_image_bbox([0, 0, float("nan"), 50], 300, 420)


def test_native_page_structure_skips_zero_size_image_occurrence_but_keeps_other_degenerate_failures():
    class Rect:
        width = 300.0
        height = 420.0

    class ZeroSizePage:
        rect = Rect()

        def get_text(self, mode, sort=False):
            assert mode == "words"
            return []

        def get_image_info(self, hashes=True, xrefs=True):
            return [
                {
                    "bbox": [0.0, 0.0, 0.0, 0.0],
                    "width": 0,
                    "height": 0,
                    "xref": 0,
                    "digest": b"empty",
                },
                {
                    "bbox": [30.0, 100.0, 130.0, 200.0],
                    "width": 100,
                    "height": 100,
                    "xref": 7,
                    "digest": b"visible",
                },
            ]

        def get_drawings(self):
            return []

    native = native_page_structure(ZeroSizePage())
    assert native["image_region_count"] == 1
    assert native["image_regions"][0]["region_id"] == "native-image-2"

    class NonZeroDegeneratePage(ZeroSizePage):
        def get_image_info(self, hashes=True, xrefs=True):
            return [
                {
                    "bbox": [10.0, 10.0, 10.0, 50.0],
                    "width": 100,
                    "height": 100,
                    "xref": 9,
                    "digest": b"bad",
                }
            ]

    with pytest.raises(InferenceRunnerError, match="degenerate"):
        native_page_structure(NonZeroDegeneratePage())


def test_native_page_structure_skips_fully_offpage_image_occurrence():
    class Rect:
        width = 300.0
        height = 420.0

    class FakePage:
        rect = Rect()

        def get_text(self, mode, sort=False):
            assert mode == "words"
            return []

        def get_image_info(self, hashes=True, xrefs=True):
            assert hashes is True
            assert xrefs is True
            return [
                {
                    "bbox": [-80.0, 100.0, -5.0, 180.0],
                    "width": 308,
                    "height": 300,
                    "xref": 0,
                    "digest": b"offpage",
                },
                {
                    "bbox": [30.0, 100.0, 130.0, 200.0],
                    "width": 100,
                    "height": 100,
                    "xref": 7,
                    "digest": b"visible",
                },
            ]

        def get_drawings(self):
            return []

    native = native_page_structure(FakePage())
    assert native["image_region_count"] == 1
    assert native["image_regions"][0]["region_id"] == "native-image-2"
    assert native["image_regions"][0]["bbox"] == [
        0.1,
        0.238095,
        0.333333,
        0.238095,
    ]
    assert native["image_regions"][0]["xref"] == 7
    assert native["automatic_offer_links"] == 0


def test_native_text_bbox_remains_strict_outside_page():
    with pytest.raises(InferenceRunnerError, match="outside page"):
        _normalized_bbox([-1, 10, 40, 50], 300, 420)



def _native_row(region_id, text, bbox, block_no, line_no=0, word_no=0):
    return {
        "region_id": region_id,
        "text": text,
        "bbox": bbox,
        "block_no": block_no,
        "line_no": line_no,
        "word_no": word_no,
        "state": "REVIEW_ONLY",
    }


def _native_price(region_id, text, bbox):
    return {
        "region_id": region_id,
        "text": text,
        "bbox": bbox,
        "basis": "native_pdf_price_like_token",
        "product_boundary_proven": False,
        "verified_product_identity": None,
        "hermes_offer_link": None,
        "state": "REVIEW_ONLY",
    }


def test_price_text_candidates_use_global_one_to_one_competition():
    words = [
        _native_row("title-a", "Popp Fleischsalat", [0.44, 0.40, 0.08, 0.03], 1),
        _native_row("title-b", "Nestle Gold Mousse", [0.55, 0.40, 0.08, 0.03], 2),
        _native_row("price-a", "1.29", [0.40, 0.50, 0.06, 0.05], 3),
        _native_row("price-b", "1.99", [0.70, 0.50, 0.06, 0.05], 4),
    ]
    prices = [
        _native_price("price-a", "1.29", [0.40, 0.50, 0.06, 0.05]),
        _native_price("price-b", "1.99", [0.70, 0.50, 0.06, 0.05]),
    ]

    candidates = _native_price_text_candidates(words, prices)
    by_price = {row["price_region_id"]: row for row in candidates}

    assert by_price["price-a"]["assignment_state"] == "SELECTED"
    assert by_price["price-a"]["product_text"] == "Popp Fleischsalat"
    assert by_price["price-b"]["assignment_state"] == "SELECTED"
    assert by_price["price-b"]["product_text"] == "Nestle Gold Mousse"
    assert (
        by_price["price-a"]["product_text_region_ids"]
        != by_price["price-b"]["product_text_region_ids"]
    )


def test_price_text_candidate_survives_without_product_image():
    words = [
        _native_row("title", "Chiquita Bananen", [0.20, 0.20, 0.16, 0.03], 1),
        _native_row("price", "1.99", [0.30, 0.34, 0.08, 0.05], 2),
    ]
    prices = [_native_price("price", "1.99", [0.30, 0.34, 0.08, 0.05])]

    candidates = _native_price_text_candidates(words, prices)

    assert len(candidates) == 1
    row = candidates[0]
    assert row["assignment_state"] == "SELECTED"
    assert row["product_text"] == "Chiquita Bananen"
    assert row["image_state"] == "UNRESOLVED"
    assert row["product_image_region_id"] is None
    assert row["product_image_bbox"] is None
    assert row["product_boundary_proven"] is False
    assert row["verified_product_identity"] is None
    assert row["hermes_offer_link"] is None


def test_price_text_candidates_preserve_rejected_and_losing_alternatives():
    words = [
        _native_row("promo", "+APP", [0.42, 0.42, 0.06, 0.03], 1),
        _native_row("title", "Bio Mozzarella", [0.50, 0.42, 0.12, 0.03], 2),
        _native_row("price", "1.29", [0.62, 0.50, 0.08, 0.05], 3),
    ]
    prices = [_native_price("price", "1.29", [0.62, 0.50, 0.08, 0.05])]

    row = _native_price_text_candidates(words, prices)[0]
    alternatives = {alt["product_text"]: alt for alt in row["alternatives"]}

    assert row["product_text"] == "Bio Mozzarella"
    assert alternatives["Bio Mozzarella"]["selection_state"] == "SELECTED"
    assert alternatives["+APP"]["selection_state"] == "REJECTED"
    assert "nonproduct_card_copy" in alternatives["+APP"]["rejection_reasons"]



def test_price_text_candidates_use_unit_price_proof_beyond_geometry_radius():
    words = [
        _native_row(
            "tafelspitz-title",
            "Tafelspitz vom Irischen Weiderind ca. 2 kg 100 g (14.90 / kg)",
            [0.10, 0.10, 0.26, 0.04],
            1,
        ),
        _native_row("correct-price", "1.49", [0.70, 0.70, 0.08, 0.05], 2),
        _native_row("near-wrong-price", "2.99", [0.34, 0.18, 0.08, 0.05], 3),
    ]
    prices = [
        _native_price("correct-price", "1.49", [0.70, 0.70, 0.08, 0.05]),
        _native_price("near-wrong-price", "2.99", [0.34, 0.18, 0.08, 0.05]),
    ]

    candidates = _native_price_text_candidates(words, prices)
    by_price = {row["price_region_id"]: row for row in candidates}

    correct = by_price["correct-price"]
    assert correct["assignment_state"] == "SELECTED"
    assert correct["product_text"].startswith("Tafelspitz")
    selected = next(
        alt for alt in correct["alternatives"]
        if alt["selection_state"] == "SELECTED"
    )
    assert selected["price_basis_state"] == "MATCH"
    assert selected["price_basis_expected_total"] == 1.49
    assert selected["price_basis_quantity_kg"] == 0.1
    assert selected["price_basis_unit_price_per_kg"] == 14.9

    wrong = by_price["near-wrong-price"]
    matching_text = next(
        alt for alt in wrong["alternatives"]
        if alt["product_text"].startswith("Tafelspitz")
    )
    assert matching_text["price_basis_state"] == "MISMATCH"
    assert "printed_price_unit_price_mismatch" in matching_text["rejection_reasons"]


def test_price_text_candidates_lock_arithmetic_proof_before_geometry_fallback():
    words = [
        _native_row(
            "spanferkel-title",
            "Spanferkel-Cevapcici vorgegart 300 g (9.97 / kg)",
            [0.10, 0.20, 0.22, 0.04],
            1,
        ),
        _native_row(
            "gyros-title",
            "Geschnetzeltes Gyros Art 800 g (5.61 / kg)",
            [0.55, 0.20, 0.22, 0.04],
            2,
        ),
        _native_row("price-299", "2.99", [0.62, 0.28, 0.08, 0.05], 3),
        _native_row("price-449", "4.49", [0.30, 0.28, 0.08, 0.05], 4),
    ]
    prices = [
        _native_price("price-299", "2.99", [0.62, 0.28, 0.08, 0.05]),
        _native_price("price-449", "4.49", [0.30, 0.28, 0.08, 0.05]),
    ]

    candidates = _native_price_text_candidates(words, prices)
    by_price = {row["price_region_id"]: row for row in candidates}

    assert by_price["price-299"]["product_text"].startswith("Spanferkel-Cevapcici")
    assert by_price["price-449"]["product_text"].startswith("Geschnetzeltes Gyros Art")
    assert all(
        next(
            alt for alt in row["alternatives"]
            if alt["selection_state"] == "SELECTED"
        )["price_basis_state"] == "MATCH"
        for row in by_price.values()
    )


def test_price_text_candidates_leave_unit_price_range_unproven():
    words = [
        _native_row(
            "title",
            "Nestle Gold Mousse 4 x 57 g - 59 g (8.43 - 8.73 / kg)",
            [0.30, 0.30, 0.30, 0.04],
            1,
        ),
        _native_row("price", "1.99", [0.62, 0.36, 0.08, 0.05], 2),
    ]
    prices = [_native_price("price", "1.99", [0.62, 0.36, 0.08, 0.05])]

    row = _native_price_text_candidates(words, prices)[0]
    selected = next(
        alt for alt in row["alternatives"]
        if alt["selection_state"] == "SELECTED"
    )

    assert selected["price_basis_state"] == "UNAVAILABLE"
    assert selected["price_basis_expected_total"] is None


def test_product_card_v2_excludes_validity_dates_and_uses_text_image_price_union():
    words = [
        _native_row("date-a", "Donnerstag", [0.28, 0.01, 0.11, 0.02], 1, 0, 0),
        _native_row("date-b", "12.11", [0.40, 0.01, 0.06, 0.02], 1, 0, 1),
        _native_row("date-c", "Samstag", [0.48, 0.01, 0.08, 0.02], 1, 0, 2),
        _native_row("date-d", "14.11", [0.58, 0.01, 0.06, 0.02], 1, 0, 3),
        _native_row("title", "Hähnchen-Brustfilet", [0.522, 0.543, 0.136, 0.013], 2),
        _native_row("meta", "mager", [0.522, 0.557, 0.04, 0.011], 2, 1, 0),
        _native_row("price", "7.99*", [0.858, 0.500, 0.082, 0.051], 4),
    ]
    prices = [
        _native_price("date-b", "12.11", [0.40, 0.01, 0.06, 0.02]),
        _native_price("date-d", "14.11", [0.58, 0.01, 0.06, 0.02]),
        _native_price("price", "7.99*", [0.858, 0.500, 0.082, 0.051]),
    ]
    images = [{
        "region_id": "product-image",
        "bbox": [0.522, 0.298, 0.444, 0.231],
        "pixel_width": 525,
        "pixel_height": 383,
        "xref": 7820,
        "digest": "aa",
        "state": "REVIEW_ONLY",
    }]

    assert _date_price_region_ids(words, prices) == {"date-b", "date-d"}
    cards = _native_product_card_candidates(words, images, prices)
    assert len(cards) == 1
    card = cards[0]
    assert card["price_region_id"] == "price"
    assert card["product_text"] == "Hähnchen-Brustfilet mager"
    assert card["product_image_region_id"] == "product-image"
    assert card["basis"] == "native_pdf_product_text_image_price_card_v3"
    assert card["card_bbox"][0] <= 0.522
    assert card["card_bbox"][1] <= 0.298
    assert card["card_bbox"][0] + card["card_bbox"][2] >= 0.940
    assert card["card_bbox"][1] + card["card_bbox"][3] >= 0.568
    assert card["product_boundary_proven"] is False
    assert card["verified_product_identity"] is None
    assert card["hermes_offer_link"] is None


def test_product_card_v2_rejects_isolated_price_without_product_text_or_image():
    words = [_native_row("price", "1.99", [0.80, 0.70, 0.08, 0.05], 1)]
    prices = [_native_price("price", "1.99", [0.80, 0.70, 0.08, 0.05])]
    assert _native_product_card_candidates(words, [], prices) == []


def test_product_card_v2_rejects_nonproduct_discount_copy_and_local_online_only_context():
    price = _native_price("price", "0.99*", [0.82, 0.72, 0.08, 0.05])
    image = [{
        "region_id": "product-image",
        "bbox": [0.60, 0.58, 0.22, 0.20],
        "pixel_width": 260,
        "pixel_height": 300,
        "xref": 1,
        "digest": "aa",
        "state": "REVIEW_ONLY",
    }]

    discount_words = [
        _native_row("copy", "pro Liter gespart -80 -80%", [0.60, 0.70, 0.18, 0.04], 1),
        _native_row("price", "0.99*", [0.82, 0.72, 0.08, 0.05], 2),
    ]
    assert _native_product_card_candidates(discount_words, image, [price]) == []

    online_words = [
        _native_row("online", "nur online", [0.58, 0.52, 0.10, 0.03], 1),
        _native_row("title", "Carport 5 x 3 m", [0.60, 0.68, 0.18, 0.04], 2),
        _native_row("price", "0.99*", [0.82, 0.72, 0.08, 0.05], 3),
    ]
    assert _native_product_card_candidates(online_words, image, [price]) == []


def test_product_card_v2_filters_shared_text_ownership_and_overlap_conflicts():
    shared_a = {
        "candidate_id": "native-card-1",
        "product_text_region_ids": ["title-1", "title-2"],
        "card_bbox": [0.05, 0.05, 0.30, 0.20],
        "layout_region_bound": False,
    }
    shared_b = {
        "candidate_id": "native-card-2",
        "product_text_region_ids": ["title-1", "title-2"],
        "card_bbox": [0.40, 0.05, 0.30, 0.20],
        "layout_region_bound": False,
    }
    assert _filter_ambiguous_product_cards([shared_a, shared_b]) == []

    hard = {
        "candidate_id": "native-card-1",
        "product_text_region_ids": ["hard-title"],
        "card_bbox": [0.05, 0.05, 0.30, 0.30],
        "layout_region_bound": True,
    }
    fallback = {
        "candidate_id": "native-card-2",
        "product_text_region_ids": ["fallback-title"],
        "card_bbox": [0.20, 0.05, 0.30, 0.30],
        "layout_region_bound": False,
    }
    assert _filter_ambiguous_product_cards([hard, fallback]) == [hard]

    fallback_a = {
        "candidate_id": "native-card-1",
        "product_text_region_ids": ["a-title"],
        "card_bbox": [0.05, 0.05, 0.30, 0.30],
        "layout_region_bound": False,
    }
    fallback_b = {
        "candidate_id": "native-card-2",
        "product_text_region_ids": ["b-title"],
        "card_bbox": [0.20, 0.05, 0.30, 0.30],
        "layout_region_bound": False,
    }
    assert _filter_ambiguous_product_cards([fallback_a, fallback_b]) == []


def test_product_card_v2_skips_promo_copy_and_selects_real_product_title():
    words = [
        _native_row("promo", "+APP", [0.72, 0.64, 0.05, 0.03], 1),
        _native_row("title", "Bio Mozzarella", [0.58, 0.60, 0.13, 0.03], 2),
        _native_row("price", "1.29*", [0.82, 0.70, 0.08, 0.05], 3),
    ]
    prices = [_native_price("price", "1.29*", [0.82, 0.70, 0.08, 0.05])]
    images = [{
        "region_id": "product-image",
        "bbox": [0.60, 0.50, 0.20, 0.18],
        "pixel_width": 240,
        "pixel_height": 260,
        "xref": 1,
        "digest": "aa",
        "state": "REVIEW_ONLY",
    }]

    cards = _native_product_card_candidates(words, images, prices)
    assert len(cards) == 1
    assert cards[0]["product_text"] == "Bio Mozzarella"


def test_product_card_v2_skips_legal_and_attribute_copy_for_real_title():
    words = [
        _native_row(
            "legal",
            "Abgabe nur in haushaltsüblichen Mengen",
            [0.66, 0.63, 0.20, 0.03],
            1,
        ),
        _native_row("attribute", "mit LED-Licht", [0.68, 0.60, 0.10, 0.03], 2),
        _native_row(
            "title",
            "Akku-Handstaubsauger",
            [0.58, 0.56, 0.16, 0.03],
            3,
        ),
        _native_row("price", "39.99", [0.82, 0.70, 0.08, 0.05], 4),
    ]
    prices = [_native_price("price", "39.99", [0.82, 0.70, 0.08, 0.05])]
    images = [{
        "region_id": "product-image",
        "bbox": [0.60, 0.48, 0.20, 0.18],
        "pixel_width": 240,
        "pixel_height": 260,
        "xref": 1,
        "digest": "aa",
        "state": "REVIEW_ONLY",
    }]

    cards = _native_product_card_candidates(words, images, prices)
    assert len(cards) == 1
    assert cards[0]["product_text"] == "Akku-Handstaubsauger"


def test_product_card_v2_skips_loyalty_copy_and_lowercase_fragment():
    words = [
        _native_row("loyalty", "50FACH °P auf die Marke*:", [0.66, 0.62, 0.18, 0.03], 1),
        _native_row("fragment", "streifenfreie", [0.66, 0.59, 0.10, 0.03], 2),
        _native_row("title", "Fenstersauger", [0.58, 0.55, 0.14, 0.03], 3),
        _native_row("price", "29.99", [0.82, 0.70, 0.08, 0.05], 4),
    ]
    prices = [_native_price("price", "29.99", [0.82, 0.70, 0.08, 0.05])]
    images = [{
        "region_id": "product-image",
        "bbox": [0.60, 0.48, 0.20, 0.18],
        "pixel_width": 240,
        "pixel_height": 260,
        "xref": 1,
        "digest": "aa",
        "state": "REVIEW_ONLY",
    }]

    cards = _native_product_card_candidates(words, images, prices)
    assert len(cards) == 1
    assert cards[0]["product_text"] == "Fenstersauger"


def test_product_card_v2_rejects_kw_or_date_like_text_as_product_title():
    words = [
        _native_row("title", "KW 46 / KiErhHaBo", [0.50, 0.80, 0.20, 0.02], 2),
        _native_row("price", "5.99", [0.86, 0.88, 0.08, 0.05], 3),
    ]
    prices = [_native_price("price", "5.99", [0.86, 0.88, 0.08, 0.05])]
    images = [{
        "region_id": "product-image",
        "bbox": [0.66, 0.73, 0.22, 0.20],
        "pixel_width": 262,
        "pixel_height": 331,
        "xref": 1,
        "digest": "bb",
        "state": "REVIEW_ONLY",
    }]
    assert _native_product_card_candidates(words, images, prices) == []



def test_product_card_v2_uses_single_price_filled_region_for_neighbouring_products():
    words = [
        _native_row("butter-title", "Meggle Butter", [0.05, 0.50, 0.22, 0.04], 1),
        _native_row("butter-price", "0.99", [0.38, 0.52, 0.09, 0.05], 2),
        _native_row("wine-title", "Rotkäppchen Sekt", [0.05, 0.88, 0.12, 0.04], 3),
        _native_row("wine-price", "2.99*", [0.38, 0.87, 0.09, 0.05], 4),
        _native_row("water-title", "Rheinfels Mineralwasser", [0.53, 0.88, 0.18, 0.04], 5),
        _native_row("water-price", "4.49", [0.85, 0.90, 0.09, 0.05], 6),
    ]
    prices = [
        _native_price("butter-price", "0.99", [0.38, 0.52, 0.09, 0.05]),
        _native_price("wine-price", "2.99*", [0.38, 0.87, 0.09, 0.05]),
        _native_price("water-price", "4.49", [0.85, 0.90, 0.09, 0.05]),
    ]
    images = [
        {
            "region_id": "butter-image",
            "bbox": [0.08, 0.34, 0.29, 0.17],
            "pixel_width": 350, "pixel_height": 240, "xref": 1,
            "digest": "aa", "state": "REVIEW_ONLY",
        },
        {
            "region_id": "wine-image",
            "bbox": [0.27, 0.60, 0.14, 0.33],
            "pixel_width": 170, "pixel_height": 550, "xref": 2,
            "digest": "bb", "state": "REVIEW_ONLY",
        },
        {
            "region_id": "water-image",
            "bbox": [0.65, 0.62, 0.26, 0.25],
            "pixel_width": 300, "pixel_height": 420, "xref": 3,
            "digest": "cc", "state": "REVIEW_ONLY",
        },
    ]
    regions = [
        [0.035, 0.2179, 0.4625, 0.3679],
        [0.5125, 0.2179, 0.4525, 0.3679],
        [0.035, 0.5964, 0.4625, 0.3643],
        [0.5125, 0.5964, 0.4525, 0.3643],
    ]

    cards = _native_product_card_candidates(words, images, prices, regions)
    by_price = {row["price_text"]: row for row in cards}
    assert by_price["2.99*"]["product_text"] == "Rotkäppchen Sekt"
    assert by_price["2.99*"]["product_image_region_id"] == "wine-image"
    assert by_price["2.99*"]["card_bbox"] == [0.038, 0.588, 0.444, 0.354]
    assert by_price["2.99*"]["card_bbox"] != regions[2]
    assert by_price["2.99*"]["layout_region_bound"] is True
    assert "Meggle" not in by_price["2.99*"]["product_text"]
    assert "Rheinfels" not in by_price["2.99*"]["product_text"]




def test_product_card_v3_rejects_image_spilling_outside_single_price_region():
    words = [
        _native_row("title", "Leerdammer Scheiben XXL", [0.55, 0.08, 0.12, 0.03], 1),
        _native_row("price", "3.99", [0.60, 0.22, 0.08, 0.05], 2),
    ]
    prices = [_native_price("price", "3.99", [0.60, 0.22, 0.08, 0.05])]
    images = [{
        "region_id": "spillover-image",
        "bbox": [0.50, 0.08, 0.18, 0.34],
        "pixel_width": 320, "pixel_height": 560, "xref": 1,
        "digest": "aa", "state": "REVIEW_ONLY",
    }]
    regions = [[0.45, 0.05, 0.30, 0.30]]

    assert _native_product_card_candidates(words, images, prices, regions) == []


def test_product_card_v3_rejects_composite_image_that_envelops_text_and_price():
    words = [
        _native_row("title", "Leerdammer Scheiben XXL", [0.55, 0.08, 0.12, 0.03], 1),
        _native_row("price", "3.99", [0.60, 0.22, 0.08, 0.05], 2),
    ]
    prices = [_native_price("price", "3.99", [0.60, 0.22, 0.08, 0.05])]
    images = [
        {
            "region_id": "isolated-product-image",
            "bbox": [0.40, 0.08, 0.12, 0.12],
            "pixel_width": 260, "pixel_height": 260, "xref": 1,
            "digest": "aa", "state": "REVIEW_ONLY",
        },
        {
            "region_id": "composite-background-image",
            "bbox": [0.53, 0.06, 0.16, 0.22],
            "pixel_width": 480, "pixel_height": 660, "xref": 2,
            "digest": "bb", "state": "REVIEW_ONLY",
        },
    ]

    cards = _native_product_card_candidates(words, images, prices)
    assert len(cards) == 1
    card = cards[0]
    assert card["product_image_region_id"] == "isolated-product-image"
    assert card["card_bbox"] == [0.388, 0.068, 0.304, 0.214]


def test_product_card_v3_assigns_shared_image_by_price_text_image_triad():
    # The image is closer to Leerdammer's printed price, but touches
    # Mövenpick's title. Neither product card may contain the other price.
    words = [
        _native_row(
            "leerdammer-title", "Leerdammer Scheiben XXL",
            [0.72, 0.12, 0.12, 0.03], 1,
        ),
        _native_row(
            "leerdammer-price", "3.99", [0.72, 0.22, 0.08, 0.05], 2,
        ),
        _native_row(
            "moevenpick-title", "Mövenpick Feinjoghurt",
            [0.45, 0.32, 0.15, 0.03], 3,
        ),
        _native_row(
            "moevenpick-price", "0.69", [0.52, 0.55, 0.08, 0.05], 4,
        ),
    ]
    prices = [
        _native_price("leerdammer-price", "3.99", [0.72, 0.22, 0.08, 0.05]),
        _native_price("moevenpick-price", "0.69", [0.52, 0.55, 0.08, 0.05]),
    ]
    images = [{
        "region_id": "shared-nearer-to-leerdammer-price",
        "bbox": [0.49, 0.25, 0.12, 0.12],
        "pixel_width": 480,
        "pixel_height": 360,
        "xref": 21,
        "digest": "aa",
        "state": "REVIEW_ONLY",
    }]

    cards = _native_product_card_candidates(words, images, prices)

    assert len(cards) == 1
    card = cards[0]
    assert card["price_region_id"] == "moevenpick-price"
    assert card["product_text"] == "Mövenpick Feinjoghurt"
    assert (
        card["product_image_region_id"]
        == "shared-nearer-to-leerdammer-price"
    )
    assert card["product_boundary_proven"] is False
    assert card["verified_product_identity"] is None
    assert card["hermes_offer_link"] is None


def test_product_card_v3_page4_avoids_false_moevenpick_nestle_overlap():
    # Retained HZ46 page-4 source-native geometry. The lower adjacent raster
    # image-17 is slightly nearer to the Mövenpick title than its actual
    # above-title package image-23. Picking image-17 makes two otherwise
    # independent cards overlap and the existing safety filter rejects both.
    words = [
        _native_row(
            "moevenpick-title",
            "Mövenpick Feinjoghurt oder Sahnepudding gekühlt, versch. Sorten "
            "150 g (4.60 / kg)",
            [0.36, 0.429733, 0.152676, 0.06144], 1,
        ),
        _native_row(
            "nestle-title",
            "Nestle Gold Mousse gekühlt, versch. Sorten "
            "4 x 57 g – 59 g (8.43 – 8.73 / kg)",
            [0.36, 0.667332, 0.140421, 0.048841], 2,
        ),
        _native_row(
            "moevenpick-price", "0.69*",
            [0.541497, 0.437061, 0.103503, 0.051046], 3,
        ),
        _native_row(
            "nestle-price", "1.99",
            [0.559645, 0.662061, 0.068209, 0.051046], 4,
        ),
    ]
    prices = [
        _native_price(
            "moevenpick-price", "0.69*",
            [0.541497, 0.437061, 0.103503, 0.051046],
        ),
        _native_price(
            "nestle-price", "1.99",
            [0.559645, 0.662061, 0.068209, 0.051046],
        ),
    ]
    images = [
        {
            "region_id": "native-image-17",
            "bbox": [0.432879, 0.507143, 0.207121, 0.109133],
            "pixel_width": 260, "pixel_height": 320, "xref": 17,
            "digest": "lower-raster", "state": "REVIEW_ONLY",
        },
        {
            "region_id": "native-image-19",
            "bbox": [0.36, 0.551072, 0.207121, 0.109133],
            "pixel_width": 260, "pixel_height": 320, "xref": 19,
            "digest": "nestle-raster", "state": "REVIEW_ONLY",
        },
        {
            "region_id": "native-image-23",
            "bbox": [0.359832, 0.299917, 0.171721, 0.11089],
            "pixel_width": 203, "pixel_height": 184, "xref": 23,
            "digest": "moevenpick-raster", "state": "REVIEW_ONLY",
        },
    ]
    cards = _native_product_card_candidates(words, images, prices)
    by_price = {card["price_region_id"]: card for card in cards}
    assert set(by_price) == {"moevenpick-price", "nestle-price"}
    yoghurt = by_price["moevenpick-price"]
    mousse = by_price["nestle-price"]
    assert yoghurt["product_image_region_id"] == "native-image-23"
    assert mousse["product_image_region_id"] == "native-image-19"
    assert yoghurt["product_text"].startswith("Mövenpick")
    assert mousse["product_text"].startswith("Nestle")
    # The existing 15% IoU fail-closed filter is not relaxed.
    assert yoghurt["card_bbox"][1] + yoghurt["card_bbox"][3] < mousse["card_bbox"][1]
    assert all(card["state"] == "REVIEW_ONLY" for card in cards)
    assert all(card["product_boundary_proven"] is False for card in cards)
    assert all(card["verified_product_identity"] is None for card in cards)
    assert all(card["hermes_offer_link"] is None for card in cards)

    # An image below the title remains usable if it is the only native
    # image: vertical order ranks alternatives; it is not a hard exclusion.
    below_only = _native_product_card_candidates(
        words[:1] + words[2:3], images[:1], prices[:1]
    )
    assert len(below_only) == 1
    assert below_only[0]["product_image_region_id"] == "native-image-17"


def test_product_card_v3_preserves_chocomel_moevenpick_cross_column_ownership():
    # Source-native HZ46 page 4 geometry. Single-axis alignment previously
    # selected Mövenpick's text for Chocomel's 1.11 price, sharing title
    # ownership and removing both REVIEW_ONLY cards.
    words = [
        _native_row(
            "chocomel-title", "Chocomel gekühlt 300 ml zzgl. Pfand 0.25 (3.70 / l)",
            [0.258, 0.336457, 0.067839, 0.072611], 1,
        ),
        _native_row(
            "moevenpick-title",
            "Mövenpick Feinjoghurt oder Sahnepudding gekühlt, "
            "versch. Sorten 150 g (4.60 / kg)",
            [0.36, 0.429733, 0.152676, 0.06144], 2,
        ),
        _native_row(
            "chocomel-price", "1.11",
            [0.254275, 0.437061, 0.048957, 0.051046], 3,
        ),
        _native_row(
            "moevenpick-price", "0.69*",
            [0.541497, 0.437061, 0.103503, 0.051046], 4,
        ),
    ]
    prices = [
        _native_price("chocomel-price", "1.11", [0.254275, 0.437061, 0.048957, 0.051046]),
        _native_price("moevenpick-price", "0.69*", [0.541497, 0.437061, 0.103503, 0.051046]),
    ]
    images = [
        {
            "region_id": "chocomel-bottle",
            "bbox": [0.03175, 0.273403, 0.305153, 0.217966],
            "pixel_width": 360, "pixel_height": 320, "xref": 36,
            "digest": "chocomel", "state": "REVIEW_ONLY",
        },
        {
            "region_id": "moevenpick-yoghurt",
            "bbox": [0.359832, 0.299917, 0.171721, 0.11089],
            "pixel_width": 203, "pixel_height": 184, "xref": 23,
            "digest": "moevenpick", "state": "REVIEW_ONLY",
        },
    ]

    cards = _native_product_card_candidates(words, images, prices)
    by_price = {card["price_region_id"]: card for card in cards}
    assert set(by_price) == {"chocomel-price", "moevenpick-price"}
    assert by_price["chocomel-price"]["product_text"].startswith("Chocomel")
    assert by_price["chocomel-price"]["product_image_region_id"] == "chocomel-bottle"
    assert by_price["moevenpick-price"]["product_text"].startswith("Mövenpick")
    assert by_price["moevenpick-price"]["product_image_region_id"] == "moevenpick-yoghurt"
    assert all(card["state"] == "REVIEW_ONLY" for card in cards)
    assert all(card["product_boundary_proven"] is False for card in cards)
    assert all(card["verified_product_identity"] is None for card in cards)
    assert all(card["hermes_offer_link"] is None for card in cards)


def test_product_card_v3_hz46_p49_truncated_disclaimer_is_not_a_product():
    # Pinned HZ46 v3-r9 page 49 has a false REVIEW_ONLY card, source
    # price native-word-24 (1.49), whose title was only the truncated
    # publisher disclaimer. Its local text is missing netto-online.de.
    # PDF page 49 visually has several different candle-related offers,
    # so this footer must not be used as any product identity or title.
    disclaimer = (
        "Artikel mit diesem Hinweis sind im Aktionszeitraum auch "
        "bestellbar unter zzgl. Versandkosten. Konkrete Angaben "
        "finden Sie beim jeweiligen Artikel im"
    )
    price_bbox = [0.60, 0.83, 0.075, 0.05]
    words = [
        _native_row("footer-note", disclaimer, [0.52, 0.925, 0.44, 0.055], 1),
        _native_row("price", "1.49", price_bbox, 2),
    ]
    visual_bbox = [0.20, 0.72, 0.48, 0.21]
    assert _product_text_block(
        words, visual_bbox, price_bbox, "price", anchor_price_text="1.49",
    ) is None

    # The shared text filter must prevent a source-native card from
    # escaping through a plausible image and a printed price alone.
    images = [{
        "region_id": "product-artwork",
        "bbox": [0.22, 0.72, 0.25, 0.16],
        "pixel_width": 300, "pixel_height": 250, "xref": 23,
        "digest": "source-artwork", "state": "REVIEW_ONLY",
    }]
    prices = [_native_price("price", "1.49", price_bbox)]
    assert _native_product_card_candidates(words, images, prices) == []

    # Keep genuine physical-store consumer product labels available.
    ordinary_words = [
        _native_row(
            "real-title", "Duftstumpen mit hochwertigem Duftkonzentrat",
            [0.44, 0.813, 0.16, 0.055], 1,
        ),
        _native_row("price", "1.49", price_bbox, 2),
    ]
    selected = _product_text_block(
        ordinary_words, visual_bbox, price_bbox, "price",
        anchor_price_text="1.49",
    )
    assert selected is not None
    assert selected[1].startswith("Duftstumpen")


def test_product_card_v3_hz46_p63_adjacent_app_price_does_not_claim_cillit():
    # HZ46 p63: Cillit Bang 70 g x 31.71/kg proves printed 2.22.
    # Zewa's neighbouring APP price 2.19 differs by only 3 cents but is
    # to the LEFT of Cillit's label; it must never claim Cillit's text.
    # The image rectangles and price coordinates are source-native evidence.
    words = [
        _native_row(
            "cillit-title",
            "Cillit Bang WC Duft- und Farbspüler versch. Sorten "
            "2 x 35 g; 70 g (31.71 / kg)",
            [0.36, 0.879733, 0.135179, 0.06144], 1,
        ),
        _native_row(
            "zewa-title",
            "Zewa Wisch & Weg Küchentücher Original oder Sparblatt "
            "4 x 45 Blatt – 74 Blatt",
            [0.045, 0.857568, 0.13, 0.083], 2,
        ),
        _native_row(
            "cillit-price", "2.22",
            [0.552174, 0.887061, 0.083152, 0.051046], 3,
        ),
        _native_row(
            "zewa-app-price", "2.19",
            [0.255392, 0.88321, 0.052084, 0.03587], 4,
        ),
    ]
    prices = [
        _native_price(
            "cillit-price", "2.22",
            [0.552174, 0.887061, 0.083152, 0.051046],
        ),
        _native_price(
            "zewa-app-price", "2.19",
            [0.255392, 0.88321, 0.052084, 0.03587],
        ),
    ]
    image = {
        "region_id": "native-image-8",
        "bbox": [0.392725, 0.737641, 0.113177, 0.13476],
        "pixel_width": 134, "pixel_height": 223, "xref": 8401,
        "digest": "cillit-pack", "state": "REVIEW_ONLY",
    }

    zewa_selection = _product_text_block(
        words, [0.255392, 0.737641, 0.25051, 0.181439],
        prices[1]["bbox"], "zewa-app-price", anchor_price_text="2.19",
    )
    assert zewa_selection is not None
    assert zewa_selection[1].startswith("Zewa")
    exact_cillit = _product_text_block(
        words, [0.392725, 0.737641, 0.242601, 0.200466],
        prices[0]["bbox"], "cillit-price", anchor_price_text="2.22",
    )
    assert exact_cillit is not None
    assert exact_cillit[1].startswith("Cillit Bang")

    # The native Cillit raster belongs to the proved 2.22 title/price
    # triad, not the unrelated neighbouring Zewa APP anchor.
    cards = _native_product_card_candidates(words, [image], prices)
    assert len(cards) == 1
    card = cards[0]
    assert card["price_region_id"] == "cillit-price"
    assert card["price_text"] == "2.22"
    assert card["product_text"].startswith("Cillit Bang")
    assert card["product_image_region_id"] == "native-image-8"
    assert card["state"] == "REVIEW_ONLY"
    assert card["product_boundary_proven"] is False
    assert card["verified_product_identity"] is None
    assert card["hermes_offer_link"] is None


def test_product_card_v3_hz46_p3_local_price_mismatch_does_not_drop_spitzpaprika():
    # HZ46 p3 native source geometry: the visibly printed 1.89* contradicts
    # 500 g x 3.58/kg (1.79); the discrepancy is retained, not corrected.
    # Before this guard an unrelated Zwetschgen 1 kg label with no price
    # arithmetic won title ranking, causing a box containing the 2.22 price.
    words = [
        _native_row(
            "zwetschgen-title", "Zwetschgen Moldau, Kl. I 1 kg offene Schale",
            [0.36, 0.679185, 0.112217, 0.037047], 1,
        ),
        _native_row(
            "mini-tomatoes-title",
            "Mini-Rispentomaten Niederlande, Kl. I 400 g Schale (7.48 / kg)",
            [0.675, 0.892332, 0.135315, 0.048841], 2,
        ),
        _native_row(
            "spitzpaprika-title",
            "Spitzpaprika rot Marokko/Spanien, Kl. I 500 g Beutel (3.58 / kg)",
            [0.36, 0.892332, 0.137471, 0.048841], 3,
        ),
        _native_row(
            "spitzpaprika-price", "1.89*",
            [0.555539, 0.887061, 0.076424, 0.051046], 4,
        ),
        _native_row(
            "zwetschgen-price", "2.22*",
            [0.548374, 0.662061, 0.090754, 0.051046], 5,
        ),
        _native_row(
            "mini-tomatoes-price", "2.99*",
            [0.862726, 0.887061, 0.092049, 0.051046], 6,
        ),
    ]
    prices = [
        _native_price(
            "spitzpaprika-price", "1.89*",
            [0.555539, 0.887061, 0.076424, 0.051046],
        ),
        _native_price(
            "zwetschgen-price", "2.22*",
            [0.548374, 0.662061, 0.090754, 0.051046],
        ),
        _native_price(
            "mini-tomatoes-price", "2.99*",
            [0.862726, 0.887061, 0.092049, 0.051046],
        ),
    ]
    image = {
        "region_id": "native-image-4",
        "bbox": [0.367224, 0.725, 0.282776, 0.181572],
        "pixel_width": 320, "pixel_height": 260, "xref": 4,
        "digest": "spitzpaprika-geometry", "state": "REVIEW_ONLY",
    }
    visual_bbox = [0.367224, 0.725, 0.282776, 0.213107]
    selected = _product_text_block(
        words, visual_bbox, prices[0]["bbox"], "spitzpaprika-price",
        anchor_price_text="1.89*",
    )
    assert selected is not None
    assert selected[1].startswith("Spitzpaprika")
    cards = _native_product_card_candidates(words, [image], prices)
    assert len(cards) == 1
    card = cards[0]
    assert card["price_region_id"] == "spitzpaprika-price"
    assert card["price_text"] == "1.89*"
    assert card["product_text"].startswith("Spitzpaprika")
    assert "(3.58 / kg)" in card["product_text"]
    assert card["product_image_region_id"] == "native-image-4"
    assert card["card_bbox"] == [0.348, 0.713, 0.314, 0.240173]
    assert card["state"] == "REVIEW_ONLY"
    assert card["product_boundary_proven"] is False
    assert card["verified_product_identity"] is None
    assert card["hermes_offer_link"] is None

    # Only a small, geometrically supported mismatch can outrank UNAVAILABLE.
    # A 20-cent discrepancy is still not enough evidence to displace a
    # nearby generic title, even when image and row geometry otherwise match.
    larger_disagreement = _product_text_block(
        words, visual_bbox, prices[0]["bbox"], "spitzpaprika-price",
        anchor_price_text="1.99*",
    )
    assert larger_disagreement is not None
    assert larger_disagreement[1].startswith("Zwetschgen")


def test_product_card_v3_prefers_price_proof_over_adjacent_column_geometry():
    # HZ46 page 4: Nestlé title is geometrically closer to this composite
    # inspection area, but Popp 200 g x 6.45/kg proves the printed 1.29.
    words = [
        _native_row(
            "popp-title", "Popp Fleischsalat gekühlt, versch. Sorten "
            "200 g (6.45 / kg)",
            [0.045, 0.667332, 0.140369, 0.048841], 1,
        ),
        _native_row(
            "nestle-title", "Nestle Gold Mousse gekühlt, versch. Sorten "
            "4 x 57 g – 59 g (8.43 – 8.73 / kg)",
            [0.36, 0.667332, 0.140421, 0.048841], 2,
        ),
        _native_row(
            "popp-price", "1.29*", [0.240764, 0.662061, 0.075972, 0.051046], 3,
        ),
    ]
    selected = _product_text_block(
        words, [0.18, 0.54, 0.35, 0.18],
        [0.240764, 0.662061, 0.075972, 0.051046],
        "popp-price", anchor_price_text="1.29*",
    )
    assert selected is not None
    selected_words, selected_text = selected
    assert [row["region_id"] for row in selected_words] == ["popp-title"]
    assert selected_text.startswith("Popp Fleischsalat")


def test_product_card_v3_diagnostic_trace_is_opt_in_and_does_not_change_cards():
    words = [
        _native_row(
            "title", "Mövenpick Feinjoghurt 150 g (4.60 / kg)",
            [0.36, 0.429733, 0.152676, 0.06144], 1,
        ),
        _native_row("price", "0.69*", [0.541497, 0.437061, 0.103503, 0.051046], 2),
    ]
    prices = [
        _native_price("price", "0.69*", [0.541497, 0.437061, 0.103503, 0.051046]),
    ]
    images = [{
        "region_id": "moevenpick-cup",
        "bbox": [0.359832, 0.299917, 0.171721, 0.11089],
        "pixel_width": 204, "pixel_height": 190, "xref": 23,
        "digest": "moevenpick", "state": "REVIEW_ONLY",
    }]
    baseline = _native_product_card_candidates(words, images, prices)
    trace = {}
    traced = _native_product_card_candidates(
        words, images, prices, diagnostic_trace=trace
    )
    assert traced == baseline
    assert len(traced) == 1
    detail = trace["by_price"]["price"]
    assert detail["state"] == "EMITTED_REVIEW_ONLY"
    assert detail["viable_image_ids"] == ["moevenpick-cup"]
    assert detail["image_wins"] == ["moevenpick-cup"]
    assert detail["image_losses"] == []
    assert detail["skipped_image_counts"] == {}
    assert detail["selected_before_filter"]["image_region_id"] == "moevenpick-cup"
    assert detail["selected_after_filter"] == "moevenpick-cup"

    no_images = {}
    assert _native_product_card_candidates(
        words, [], prices, diagnostic_trace=no_images
    ) == []
    assert no_images["by_price"]["price"]["state"] == (
        "NO_VIABLE_IMAGE_TEXT_PRICE_TRIAD"
    )
    assert no_images["by_price"]["price"]["selected_after_filter"] is None


def test_product_card_v3_excludes_large_corner_bleed_lifestyle_image():
    # HZ46 page 4: the 430x643 editorial photograph covers the top-right
    # page corner. Its proximity to Leerdammer's 3.99 price is not evidence
    # that the person shown is the product image. Native geometry only.
    words = [
        _native_row("leerdammer-title", "Leerdammer Scheiben XXL", [0.55, 0.09, 0.14, 0.035], 1),
        _native_row("leerdammer-price", "3.99", [0.60, 0.22, 0.08, 0.05], 2),
    ]
    prices = [_native_price("leerdammer-price", "3.99", [0.60, 0.22, 0.08, 0.05])]
    lifestyle = {
        "region_id": "full-bleed-editorial-image",
        "bbox": [0.663, 0.0, 0.337, 0.36924],
        "pixel_width": 430, "pixel_height": 643, "xref": 1,
        "digest": "editorial", "state": "REVIEW_ONLY",
    }
    # A lifestyle photo alone must not create a clickable product card.
    assert _native_product_card_candidates(words, [lifestyle], prices) == []

    package = {
        "region_id": "isolated-leerdammer-package",
        "bbox": [0.33, 0.07, 0.18, 0.19],
        "pixel_width": 300, "pixel_height": 310, "xref": 2,
        "digest": "product", "state": "REVIEW_ONLY",
    }
    cards = _native_product_card_candidates(words, [lifestyle, package], prices)
    assert len(cards) == 1
    assert cards[0]["product_image_region_id"] == "isolated-leerdammer-package"
    assert cards[0]["price_region_id"] == "leerdammer-price"
    assert cards[0]["product_boundary_proven"] is False
    assert cards[0]["verified_product_identity"] is None
    assert cards[0]["hermes_offer_link"] is None


def test_product_card_v3_keeps_single_edge_product_image():
    words = [
        _native_row("title", "Chiquita Bananen", [0.60, 0.42, 0.14, 0.03], 1),
        _native_row("price", "1.99", [0.78, 0.47, 0.09, 0.05], 2),
    ]
    prices = [_native_price("price", "1.99", [0.78, 0.47, 0.09, 0.05])]
    images = [{
        "region_id": "single-edge-banana-image",
        "bbox": [0.55, 0.32, 0.45, 0.20],
        "pixel_width": 709, "pixel_height": 295, "xref": 1,
        "digest": "banana", "state": "REVIEW_ONLY",
    }]
    cards = _native_product_card_candidates(words, images, prices)
    assert len(cards) == 1
    assert cards[0]["product_image_region_id"] == "single-edge-banana-image"
    assert cards[0]["verified_product_identity"] is None
    assert cards[0]["hermes_offer_link"] is None


def test_product_card_v3_prefers_compact_evidence_over_nearer_lifestyle_image():
    words = [
        _native_row("title", "Leerdammer Scheiben XXL", [0.55, 0.55, 0.12, 0.03], 1),
        _native_row("price", "3.99", [0.70, 0.60, 0.08, 0.05], 2),
    ]
    prices = [_native_price("price", "3.99", [0.70, 0.60, 0.08, 0.05])]
    images = [
        {
            "region_id": "compact-product-image",
            "bbox": [0.50, 0.40, 0.18, 0.15],
            "pixel_width": 320, "pixel_height": 260, "xref": 1,
            "digest": "aa", "state": "REVIEW_ONLY",
        },
        {
            "region_id": "nearer-lifestyle-image",
            "bbox": [0.74, 0.30, 0.22, 0.28],
            "pixel_width": 420, "pixel_height": 520, "xref": 2,
            "digest": "bb", "state": "REVIEW_ONLY",
        },
    ]

    cards = _native_product_card_candidates(words, images, prices)
    assert len(cards) == 1
    card = cards[0]
    assert card["product_image_region_id"] == "compact-product-image"
    assert card["basis"] == "native_pdf_product_text_image_price_card_v3"
    assert card["card_bbox"] == [0.488, 0.388, 0.304, 0.274]


def test_native_layout_regions_keep_substantial_filled_card_rectangles_only():
    class PointRect:
        def __init__(self, x0, y0, x1, y1):
            self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1

    class FakePage:
        def get_drawings(self):
            return [
                {
                    "fill": (1.0, 0.9, 0.0),
                    "items": [("re", PointRect(10, 80, 150, 260), 1)],
                },
                {
                    "fill": (1.0, 0.0, 0.0),
                    "items": [("re", PointRect(250, 20, 285, 55), 1)],
                },
                {
                    "fill": (1.0, 1.0, 1.0),
                    "items": [("re", PointRect(0, 0, 300, 420), 1)],
                },
                {
                    "fill": None,
                    "items": [("re", PointRect(160, 80, 290, 260), 1)],
                },
            ]

    regions = _native_layout_regions(FakePage(), 300.0, 420.0)
    assert regions == [[0.033333, 0.190476, 0.466667, 0.428571]]



def test_native_page_structure_skips_zero_dimension_image_occurrences_when_pixel_dimension_matches():
    class Rect:
        width = 300.0
        height = 420.0

    class FakePage:
        rect = Rect()

        def get_text(self, mode, sort=False):
            assert mode == "words"
            return []

        def get_image_info(self, hashes=True, xrefs=True):
            assert hashes is True
            assert xrefs is True
            return [
                {
                    "bbox": [0.0, 100.0, 0.0, 116.0],
                    "width": 0,
                    "height": 16,
                    "xref": 0,
                    "digest": b"zero-width",
                },
                {
                    "bbox": [40.0, 200.0, 60.0, 200.0],
                    "width": 20,
                    "height": 0,
                    "xref": 0,
                    "digest": b"zero-height",
                },
                {
                    "bbox": [30.0, 100.0, 130.0, 200.0],
                    "width": 100,
                    "height": 100,
                    "xref": 7,
                    "digest": b"visible",
                },
            ]

        def get_drawings(self):
            return []

    native = native_page_structure(FakePage())
    assert native["image_region_count"] == 1
    assert native["image_regions"][0]["region_id"] == "native-image-3"
    assert native["image_regions"][0]["xref"] == 7

    class MismatchedDegeneratePage(FakePage):
        def get_image_info(self, hashes=True, xrefs=True):
            return [
                {
                    "bbox": [10.0, 10.0, 10.0, 50.0],
                    "width": 100,
                    "height": 40,
                    "xref": 9,
                    "digest": b"bad",
                }
            ]

    with pytest.raises(InferenceRunnerError, match="degenerate"):
        native_page_structure(MismatchedDegeneratePage())
