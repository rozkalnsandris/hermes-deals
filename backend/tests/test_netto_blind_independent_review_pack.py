from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pymupdf
import pytest


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools/netto_blind_independent_review_pack.py"
SPEC = importlib.util.spec_from_file_location(
    "netto_blind_independent_review_pack_tested",
    TOOL,
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def make_cell(
    cell_id: str,
    campaign: str,
    page: int,
    x0: float,
    x1: float,
) -> dict[str, object]:
    return {
        "cell_id": cell_id,
        "publication_slug": campaign,
        "page_number": page,
        "review_state": "pending_visual_validation",
        "automatic_approval_allowed": False,
        "automatic_publish_allowed": False,
        "scope_state": "target_or_review_card",
        "region_x0": x0,
        "region_y0": 0.0,
        "region_x1": x1,
        "region_y1": 1.0,
    }


def make_fixture(
    campaign: str,
    page: int,
    cells: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "strategy": "netto_n9_n8_v2_visual_cell_fixture_v1",
        "review_state": "pending_visual_validation",
        "automatic_approval_count": 0,
        "automatic_publish_count": 0,
        "production_write_performed": False,
        "page": {
            "publication_slug": campaign,
            "page_number": page,
            "raw_cell_count": len(cells),
        },
        "cells": cells,
    }


def exact_shape_fixtures() -> list[dict[str, object]]:
    fixtures: list[dict[str, object]] = []
    active = [
        ("hz31_hasb_4", 14, 7),
        ("hz31_hasb_4", 18, 9),
        ("hz31_hasb_4", 43, 10),
        ("hz32_hasb", 1, 10),
        ("hz32_hasb", 37, 10),
        ("hz32_hasb", 38, 10),
        ("hz32_hasb", 40, 10),
        ("hz32_hasb", 41, 10),
        ("hz32_hasb", 42, 10),
        ("hz32_hasb", 43, 10),
        ("hz32_hasb", 44, 4),
    ]
    serial = 0
    for campaign, page, count in active:
        cells = []
        for index in range(count):
            x0 = index / count
            x1 = (index + 1) / count
            cells.append(
                make_cell(
                    f"cell-{serial:03d}",
                    campaign,
                    page,
                    x0,
                    x1,
                )
            )
            serial += 1
        fixtures.append(make_fixture(campaign, page, cells))

    for campaign, page in [
        ("hz31_hasb_4", 10),
        ("hz31_hasb_4", 12),
        ("hz31_hasb_4", 20),
        ("hz32_hasb", 10),
        ("hz32_hasb", 12),
        ("hz32_hasb", 20),
    ]:
        fixtures.append(make_fixture(campaign, page, []))

    assert serial == 100
    return fixtures


def write_pdf(path: Path, page_count: int) -> None:
    document = pymupdf.open()
    try:
        for _ in range(page_count):
            document.new_page(width=200.0, height=100.0)
        document.save(path)
    finally:
        document.close()


def test_generator_source_has_no_first_pass_truth_or_parser_dependency() -> None:
    source = TOOL.read_text(encoding="utf-8").casefold()
    assert "n10" not in source
    assert "netto_visual_geometry_shadow" not in source
    assert "netto_visual_geometry_corpus_replay" not in source
    assert "expected_title" not in source
    assert "selected_title" not in source
    assert "selected_normal_price" not in source
    assert "--n10" not in source


def test_n9_contract_requires_exact_17_pages_100_cells_and_six_zero_controls() -> None:
    fixtures = MODULE.validate_n9_manifest(exact_shape_fixtures())
    assert len(fixtures) == 17
    assert sum(len(row["cells"]) for row in fixtures) == 100
    assert sum(not row["cells"] for row in fixtures) == 6


def test_cell_rect_uses_unrotated_page_dimensions() -> None:
    cell = make_cell("cell", "hz31_hasb_4", 14, 0.25, 0.75)
    assert MODULE.cell_rect(cell, 200.0, 400.0) == (
        50.0,
        0.0,
        150.0,
        400.0,
    )


def test_text_evidence_is_limited_to_intersecting_source_spans() -> None:
    document = pymupdf.open()
    try:
        page = document.new_page(width=200.0, height=100.0)
        page.insert_text((20.0, 30.0), "LEFT SOURCE")
        page.insert_text((140.0, 30.0), "RIGHT SOURCE")
        rows = MODULE.text_spans_for_rect(page, (0.0, 0.0, 100.0, 100.0))
    finally:
        document.close()

    texts = [row["text"] for row in rows]
    assert any("LEFT SOURCE" in value for value in texts)
    assert all("RIGHT SOURCE" not in value for value in texts)
    assert all(len(row["bbox"]) == 4 for row in rows)


def test_blank_review_ledger_contains_only_source_identity_and_empty_review_fields() -> None:
    fixtures = MODULE.validate_n9_manifest(exact_shape_fixtures())
    ledger = MODULE.blank_review_ledger(fixtures)

    assert ledger["cell_count"] == 100
    assert ledger["review_state"] == "blank_independent_review"
    assert len(ledger["rows"]) == 100

    forbidden = {
        "expected_title",
        "expected_normal_price",
        "selected_title",
        "selected_normal_price",
        "parser_route",
        "promotion_ready",
        "scope_state",
    }
    for row in ledger["rows"]:
        assert forbidden.isdisjoint(row)
        for key in (
            "observed_product_title",
            "observed_normal_price",
            "observed_member_price",
            "card_ownership_state",
            "scope_classification",
            "reviewer_confidence",
            "reviewer_note",
        ):
            assert row[key] is None


def test_create_only_writer_refuses_existing_member(tmp_path: Path) -> None:
    path = tmp_path / "member.json"
    first_sha = MODULE._write_create_only(path, b"first")
    assert first_sha == MODULE.sha_bytes(b"first")
    with pytest.raises(MODULE.BlindReviewPackError, match="already exists"):
        MODULE._write_create_only(path, b"second")
    assert path.read_bytes() == b"first"


def test_full_pack_is_blind_create_only_and_sha_manifested(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixtures = MODULE.validate_n9_manifest(exact_shape_fixtures())

    pdf31 = tmp_path / "kw31.pdf"
    pdf32 = tmp_path / "kw32.pdf"
    write_pdf(pdf31, MODULE.CAMPAIGN_PDFS["hz31_hasb_4"]["page_count"])
    write_pdf(pdf32, MODULE.CAMPAIGN_PDFS["hz32_hasb"]["page_count"])

    monkeypatch.setattr(
        MODULE,
        "load_exact_n9_manifest",
        lambda _path: fixtures,
    )
    monkeypatch.setattr(
        MODULE,
        "locate_exact_pdfs",
        lambda _root: {
            "hz31_hasb_4": pdf31,
            "hz32_hasb": pdf32,
        },
    )
    monkeypatch.setattr(
        MODULE,
        "_render_png",
        lambda _page, _rect=None: b"\x89PNG\r\nblind-source",
    )
    monkeypatch.setattr(
        MODULE,
        "text_spans_for_rect",
        lambda _page, rect: [
            {
                "text": "SOURCE TEXT",
                "bbox": [round(float(value), 3) for value in rect],
                "size": 10.0,
                "font": "Test",
                "color": 0,
                "flags": 0,
            }
        ],
    )

    output = tmp_path / "pack"
    manifest = MODULE.generate_pack(
        tmp_path / "fixture-manifest.json",
        tmp_path / "corpus",
        output,
    )

    assert manifest["fixture_page_count"] == 17
    assert manifest["cell_count"] == 100
    assert manifest["blind_review_contract"] == {
        "expected_truth_included": False,
        "parser_predictions_included": False,
        "automatic_approval_enabled": False,
        "automatic_publish_enabled": False,
        "production_write_performed": False,
    }
    assert len(manifest["pages"]) == 17
    assert len(manifest["cells"]) == 100
    assert len(manifest["members"]) == 218

    ledger_path = output / "independent-review-ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert ledger["cell_count"] == 100
    assert all(row["observed_product_title"] is None for row in ledger["rows"])

    for member in manifest["members"]:
        path = output / member["path"]
        assert path.is_file()
        assert MODULE.sha_file(path) == member["sha256"]
        assert path.stat().st_size == member["bytes"]

    for cell in manifest["cells"]:
        assert "expected_title" not in cell
        assert "selected_title" not in cell
        assert "scope_state" not in cell
        text_evidence = json.loads(
            (output / cell["text_evidence"]).read_text(encoding="utf-8")
        )
        assert text_evidence["text_spans"][0]["text"] == "SOURCE TEXT"

    with pytest.raises(MODULE.BlindReviewPackError, match="already exists"):
        MODULE.generate_pack(
            tmp_path / "fixture-manifest.json",
            tmp_path / "corpus",
            output,
        )


def test_cell_member_names_are_stable_and_do_not_expose_cell_id() -> None:
    first = MODULE.stable_cell_member_name(1, "campaign/page/cell")
    second = MODULE.stable_cell_member_name(1, "campaign/page/cell")
    assert first == second
    assert "campaign" not in first
    assert first.startswith("001-")
