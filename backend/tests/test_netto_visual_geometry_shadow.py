from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "netto_visual_geometry_shadow.py"
N10_FIXTURE = (
    ROOT
    / "backend"
    / "tests"
    / "fixtures"
    / "netto"
    / "n10_full_visual_review_v1.json"
)

SPEC = importlib.util.spec_from_file_location(
    "netto_visual_geometry_shadow_tested", MODULE_PATH
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _layout(*, spans, horizontal=(), vertical=(), rectangles=()):
    return {
        "page": {
            "width_points": 600.0,
            "height_points": 800.0,
            "page_number": 1,
            "rotation": 0,
        },
        "spans": spans,
        "vectors": {
            "horizontal_lines": list(horizontal),
            "vertical_lines": list(vertical),
            "rectangles": list(rectangles),
        },
    }


def _span(text, x0, y0, x1, y1, size=12):
    return {
        "text": text,
        "bbox": [x0, y0, x1, y1],
        "size": size,
        "font": "Test",
        "color": 0,
        "flags": 0,
    }


class NettoVisualGeometryShadowTest(unittest.TestCase):
    def test_authoritative_n10_has_exact_nine_card_price_repairs(self) -> None:
        fixture = json.loads(N10_FIXTURE.read_text(encoding="utf-8"))
        repairs = [
            row
            for row in fixture["cell_reviews"]
            if row["visual_verdict"]
            == "card_binding_or_primary_price_correction_required"
        ]
        self.assertEqual(len(repairs), 9)
        self.assertEqual(
            {(row["publication_slug"], row["page_number"]) for row in repairs},
            {
                ("hz31_hasb_4", 14),
                ("hz31_hasb_4", 18),
                ("hz32_hasb", 1),
                ("hz32_hasb", 37),
                ("hz32_hasb", 38),
            },
        )
        self.assertTrue(all(row["expected_primary_price_eur"] for row in repairs))
        self.assertTrue(all(row["expected_title"] for row in repairs))
        self.assertTrue(
            all(row["automatic_approval_allowed"] is False for row in repairs)
        )
        self.assertTrue(
            all(row["automatic_publish_allowed"] is False for row in repairs)
        )

    def test_separator_blocks_neighbor_cross_binding(self) -> None:
        layout = _layout(
            spans=[
                _span("Hohes C Vitamin Water", 80, 120, 220, 140, 14),
                _span("1,19", 120, 180, 160, 205, 22),
                _span("Tyskie Pils", 360, 120, 450, 140, 14),
                _span("0,79", 390, 180, 430, 205, 22),
            ],
            vertical=[
                {"x1": 300, "y1": 50, "x2": 300, "y2": 350, "length": 300}
            ],
        )
        result = MODULE.analyze_layout(layout)
        groups = result["groups"]
        self.assertEqual(len(groups), 2)
        by_price = {group["selected_normal_price"]: group for group in groups}
        self.assertIn("1.19", by_price)
        self.assertIn("0.79", by_price)
        self.assertIn("Hohes", by_price["1.19"]["selected_title"])
        self.assertNotIn("Tyskie", by_price["1.19"]["selected_title"])

    def test_member_price_is_typed_separately(self) -> None:
        layout = _layout(
            spans=[
                _span("Freixenet", 80, 120, 170, 140, 14),
                _span("3,99", 100, 180, 145, 205, 22),
                _span("Netto+", 155, 170, 210, 186, 10),
                _span("3,79", 160, 190, 205, 214, 18),
            ]
        )
        result = MODULE.analyze_layout(layout)
        groups = result["groups"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["selected_normal_price"], "3.99")
        self.assertEqual(groups[0]["selected_member_price"], "3.79")

    def test_multiple_normal_prices_fail_closed(self) -> None:
        layout = _layout(
            spans=[
                _span("Produkt", 80, 120, 150, 140, 14),
                _span("1,49", 100, 180, 145, 205, 20),
                _span("1,59", 135, 190, 180, 215, 20),
            ]
        )
        result = MODULE.analyze_layout(layout)
        self.assertEqual(len(result["groups"]), 1)
        self.assertEqual(result["groups"][0]["route"], "review_required")
        self.assertIsNone(result["groups"][0]["selected_normal_price"])

    def test_promotional_title_is_not_selected(self) -> None:
        layout = _layout(
            spans=[
                _span("KRACHER", 80, 90, 160, 110, 18),
                _span("Bananen", 80, 125, 150, 145, 14),
                _span("1,00", 100, 180, 145, 205, 22),
            ]
        )
        result = MODULE.analyze_layout(layout)
        self.assertEqual(len(result["groups"]), 1)
        self.assertIn("Bananen", result["groups"][0]["selected_title"])
        self.assertNotIn("KRACHER", result["groups"][0]["selected_title"])

    def test_split_major_and_cents_are_reconstructed(self) -> None:
        layout = _layout(
            spans=[
                _span("Hohes C Vitamin Water", 80, 120, 220, 140, 14),
                _span("1.", 100, 180, 125, 225, 40),
                _span("19", 120, 184, 145, 210, 23),
            ]
        )
        result = MODULE.analyze_layout(layout)
        values = {anchor["value"]: anchor for anchor in result["price_anchors"]}
        self.assertIn("1.19", values)
        self.assertEqual(values["1.19"]["source_kind"], "split_major_cents")
        self.assertEqual(values["1.19"]["component_span_indexes"], (1, 2))

    def test_large_unpaired_major_reconstructs_whole_euro(self) -> None:
        layout = _layout(
            spans=[
                _span("Bananen", 80, 120, 150, 140, 14),
                _span("1.", 100, 180, 125, 225, 43),
                _span("UVP 1.29", 110, 226, 165, 238, 9.2),
            ]
        )
        result = MODULE.analyze_layout(layout)
        whole = [
            anchor
            for anchor in result["price_anchors"]
            if anchor["value"] == "1.00"
        ]
        self.assertEqual(len(whole), 1)
        self.assertEqual(whole[0]["source_kind"], "whole_euro_major")

    def test_split_price_components_are_not_title_text(self) -> None:
        layout = _layout(
            spans=[
                _span("Hohes C Vitamin Water", 80, 120, 220, 140, 14),
                _span("1.", 100, 180, 125, 225, 40),
                _span("19", 120, 184, 145, 210, 23),
            ]
        )
        result = MODULE.analyze_layout(layout)
        groups = [
            group
            for group in result["groups"]
            if group["selected_normal_price"] == "1.19"
        ]
        self.assertEqual(len(groups), 1)
        self.assertIn("Hohes", groups[0]["selected_title"])
        self.assertNotIn("1.", groups[0]["selected_title"])
        self.assertNotIn("19", groups[0]["selected_title"])

    def test_split_member_price_remains_separate_from_normal(self) -> None:
        layout = _layout(
            spans=[
                _span("Freixenet", 80, 120, 170, 140, 14),
                _span("3.", 100, 180, 125, 225, 38),
                _span("99", 120, 184, 145, 210, 22),
                _span("Netto+", 165, 170, 210, 185, 10),
                _span("3.", 150, 190, 170, 218, 25),
                _span("79", 165, 193, 190, 211, 15),
            ]
        )
        result = MODULE.analyze_layout(layout)
        candidate_groups = [
            group
            for group in result["groups"]
            if "3.99" in group["normal_price_candidates"]
            and "3.79" in group["member_price_candidates"]
        ]
        self.assertEqual(len(candidate_groups), 1)
        self.assertEqual(candidate_groups[0]["selected_normal_price"], "3.99")
        self.assertEqual(candidate_groups[0]["selected_member_price"], "3.79")

    def test_split_price_analysis_is_deterministic(self) -> None:
        layout = _layout(
            spans=[
                _span("Produkt", 80, 120, 150, 140, 14),
                _span("6.", 100, 180, 125, 225, 40),
                _span("49", 120, 184, 145, 210, 23),
            ]
        )
        self.assertEqual(
            MODULE.analyze_layout(layout),
            MODULE.analyze_layout(layout),
        )

    def test_all_routes_remain_shadow_only(self) -> None:
        layout = _layout(
            spans=[
                _span("Produkt", 80, 120, 150, 140, 14),
                _span("1,49", 100, 180, 145, 205, 22),
            ]
        )
        result = MODULE.analyze_layout(layout)
        self.assertFalse(result["production_eligible"])
        self.assertFalse(result["promotion_ready"])
        for group in result["groups"]:
            self.assertFalse(group["production_eligible"])
            self.assertFalse(group["promotion_ready"])


if __name__ == "__main__":
    unittest.main()
