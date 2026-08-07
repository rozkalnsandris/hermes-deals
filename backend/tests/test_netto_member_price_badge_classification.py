from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "netto_visual_geometry_shadow.py"
SPEC = importlib.util.spec_from_file_location(
    "netto_visual_geometry_member_badge_tested",
    MODULE_PATH,
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def span(text: str, x0: float, y0: float, x1: float, y1: float, size: float = 20.0) -> dict[str, object]:
    return {
        "text": text,
        "bbox": [x0, y0, x1, y1],
        "size": size,
        "font": "Test",
        "color": 0,
        "flags": 0,
    }


def fill(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    rgb: tuple[int, int, int],
    *,
    seqno: int,
    opacity: float = 1.0,
) -> dict[str, object]:
    return {
        "x0": x0,
        "y0": y0,
        "x1": x1,
        "y1": y1,
        "fill_rgb": list(rgb),
        "fill_opacity": opacity,
        "seqno": seqno,
    }


def layout(
    normal: str,
    member: str,
    *,
    member_fill: tuple[int, int, int],
    extra_fills: list[dict[str, object]] | None = None,
    include_text_label: bool = False,
) -> dict[str, object]:
    spans = [
        span("Produkt", 85, 120, 165, 140, 14),
        span(normal.replace(".", ","), 100, 180, 145, 205, 22),
        span(member.replace(".", ","), 160, 190, 205, 214, 18),
    ]
    if include_text_label:
        spans.append(span("Netto+", 152, 168, 210, 184, 10))
    fills = [
        fill(95, 175, 150, 210, (220, 13, 21), seqno=10),
        fill(150, 181, 215, 220, member_fill, seqno=20),
    ]
    fills.extend(extra_fills or [])
    return {
        "page": {
            "width_points": 600.0,
            "height_points": 800.0,
            "page_number": 1,
            "rotation": 0,
        },
        "spans": spans,
        "vectors": {
            "horizontal_lines": [],
            "vertical_lines": [],
            "rectangles": [],
            "filled_rectangles": fills,
        },
    }


@pytest.mark.parametrize(
    ("normal", "member", "member_fill"),
    [
        ("10.49", "9.99", (130, 59, 134)),
        ("1.49", "1.29", (233, 65, 144)),
        ("5.99", "5.49", (130, 59, 134)),
        ("1.11", "1.00", (233, 65, 144)),
        ("3.99", "3.69", (233, 65, 144)),
        ("10.99", "9.99", (130, 59, 134)),
        ("3.99", "3.79", (130, 59, 134)),
    ],
)
def test_frozen_member_pairs_are_typed_from_local_badge_fill(
    normal: str,
    member: str,
    member_fill: tuple[int, int, int],
) -> None:
    result = MODULE.analyze_layout(layout(normal, member, member_fill=member_fill))
    matching = [
        group
        for group in result["groups"]
        if normal in group["normal_price_candidates"]
        and member in group["member_price_candidates"]
    ]
    assert len(matching) == 1
    group = matching[0]
    assert group["selected_normal_price"] == normal
    assert group["selected_member_price"] == member
    assert group["route"] == "review_required"


def test_large_red_background_does_not_override_local_member_badge() -> None:
    result = MODULE.analyze_layout(
        layout(
            "5.99",
            "5.49",
            member_fill=(130, 59, 134),
            extra_fills=[fill(0, 0, 600, 450, (220, 13, 21), seqno=1)],
        )
    )
    groups = [
        group for group in result["groups"]
        if "5.99" in group["normal_price_candidates"]
        and "5.49" in group["member_price_candidates"]
    ]
    assert len(groups) == 1


def test_overlapping_member_color_without_center_ownership_is_ignored() -> None:
    raw = layout("3.99", "3.79", member_fill=(130, 59, 134))
    raw["vectors"]["filled_rectangles"].append(
        fill(130, 175, 160, 210, (233, 65, 144), seqno=30)
    )
    result = MODULE.analyze_layout(raw)
    group = next(group for group in result["groups"] if "3.99" in group["normal_price_candidates"])
    assert group["selected_normal_price"] == "3.99"


def test_conflicting_equally_local_member_and_normal_badges_fail_closed() -> None:
    raw = {
        "page": {
            "width_points": 600.0,
            "height_points": 800.0,
            "page_number": 1,
            "rotation": 0,
        },
        "spans": [
            span("Produkt", 85, 120, 165, 140, 14),
            span("3,79", 160, 190, 205, 214, 18),
        ],
        "vectors": {
            "horizontal_lines": [],
            "vertical_lines": [],
            "rectangles": [],
            "filled_rectangles": [
                fill(150, 181, 215, 220, (130, 59, 134), seqno=20),
                fill(150, 181, 215, 220, (220, 13, 21), seqno=21),
            ],
        },
    }
    result = MODULE.analyze_layout(raw)
    anchor = next(value for value in result["price_anchors"] if value["value"] == "3.79")
    assert anchor["member_labeled"] is False
    assert anchor["member_badge_ambiguous"] is True
    group = result["groups"][0]
    assert group["selected_normal_price"] is None
    assert group["selected_member_price"] is None
    assert "member_price_badge_ambiguous" in group["reasons"]
    assert group["route"] == "review_required"


def test_existing_text_member_label_remains_supported_without_fill_evidence() -> None:
    raw = layout(
        "3.99",
        "3.79",
        member_fill=(130, 59, 134),
        include_text_label=True,
    )
    raw["vectors"]["filled_rectangles"] = [
        value
        for value in raw["vectors"]["filled_rectangles"]
        if value["fill_rgb"] == [220, 13, 21]
    ]
    result = MODULE.analyze_layout(raw)
    group = next(group for group in result["groups"] if "3.79" in group["member_price_candidates"])
    assert group["selected_member_price"] == "3.79"


def test_member_badge_area_limit_ignores_page_background() -> None:
    raw = {
        "page": {
            "width_points": 600.0,
            "height_points": 800.0,
            "page_number": 1,
            "rotation": 0,
        },
        "spans": [
            span("Produkt", 85, 120, 165, 140, 14),
            span("3,79", 160, 190, 205, 214, 18),
        ],
        "vectors": {
            "horizontal_lines": [],
            "vertical_lines": [],
            "rectangles": [],
            "filled_rectangles": [fill(0, 0, 600, 800, (233, 65, 144), seqno=1)],
        },
    }
    result = MODULE.analyze_layout(raw)
    group = result["groups"][0]
    assert group["member_price_candidates"] == []
    assert group["normal_price_candidates"] == ["3.79"]


def test_member_badge_opacity_must_be_opaque() -> None:
    raw = layout("3.99", "3.79", member_fill=(130, 59, 134))
    for value in raw["vectors"]["filled_rectangles"]:
        if value["fill_rgb"] == [130, 59, 134]:
            value["fill_opacity"] = 0.5
    result = MODULE.analyze_layout(raw)
    assert all("3.79" not in group["member_price_candidates"] for group in result["groups"])


def test_filled_rectangle_shape_is_deterministic() -> None:
    raw = layout("3.99", "3.79", member_fill=(130, 59, 134))
    first = MODULE.filled_rectangles_from_layout(raw)
    second = MODULE.filled_rectangles_from_layout(raw)
    assert first == second
    assert first[0].bbox.area <= first[-1].bbox.area
