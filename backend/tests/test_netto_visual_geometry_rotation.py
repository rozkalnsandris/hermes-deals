from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import fitz
import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "netto_visual_geometry_shadow.py"
SPEC = importlib.util.spec_from_file_location(
    "netto_visual_geometry_rotation_tested", MODULE_PATH
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


@pytest.mark.parametrize("rotation", [90, 270])
def test_rotated_pdf_keeps_unrotated_geometry_dimensions(
    tmp_path: Path, rotation: int
) -> None:
    pdf_path = tmp_path / f"rotated-{rotation}.pdf"
    document = fitz.open()
    page = document.new_page(width=200, height=400)
    page.draw_line(fitz.Point(20, 100), fitz.Point(50, 100))
    page.set_rotation(rotation)
    document.save(pdf_path)
    document.close()

    layout = MODULE.extract_layout_from_pdf(pdf_path, 1)

    assert layout["page"] == {
        "width_points": 200.0,
        "height_points": 400.0,
        "rotation": rotation,
        "page_number": 1,
    }

    separators = MODULE.separators_from_layout(layout)
    horizontal = [row for row in separators if row.orientation == "horizontal"]
    assert len(horizontal) == 1
    assert horizontal[0].length == pytest.approx(30.0)


def test_geometry_parser_identity_records_coordinate_space_change() -> None:
    assert MODULE.PARSER_IDENTITY == (
        "netto-visual-geometry-shadow-v3-unrotated-page-space"
    )
