"""Netto PDF local Review marker gate: geometry without product identity."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from netto_pdf_review_export import _relative_box, review_page


def analysis():
    return {
        "shadow_only": True, "production_eligible": False, "promotion_ready": False,
        "page": {"page_number": 44, "width_points": 600, "height_points": 800, "rotation": 0},
        "groups": [{
            "group_id": "p44-g8",
            "bbox": {"x0": 480, "y0": 600, "x1": 540, "y1": 640},
            "selected_title": "5 in 1 Spieltisch",
            "normal_price_candidates": ["129.99"],
            "reasons": ["title_independent_evidence_required"],
            "route": "review_required", "shadow_only": True,
            "production_eligible": False, "promotion_ready": False,
        }],
    }


class PdfMarkerReviewTest(unittest.TestCase):
    def test_review_only_with_bounded_geometry(self):
        row = review_page(analysis(), 44)["candidates"][0]
        self.assertEqual(row["marker_bbox"], [0.8, 0.75, 0.1, 0.05])
        self.assertEqual(row["state"], "REVIEW_ONLY")
        self.assertEqual(row["marker_basis"], "observed_pdf_price_group_only")
        self.assertIsNone(row["hermes_offer_link"])
        self.assertIsNone(row["verified_product_identity"])

    def test_bad_page_identity_fails_closed(self):
        for key, bad in (("shadow_only", False), ("production_eligible", True), ("promotion_ready", True)):
            source = analysis()
            source[key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError):
                review_page(source, 44)
        source = analysis()
        source["page"]["rotation"] = 90
        with self.assertRaises(ValueError):
            review_page(source, 44)
        with self.assertRaises(ValueError):
            review_page(analysis(), 45)

    def test_forged_and_ambiguous_coordinates(self):
        box = {"x0": 0, "y0": 0, "x1": 600, "y1": 800}
        self.assertEqual(_relative_box(box, 600, 800), [0, 0, 1, 1])
        for bad in ({**box, "x1": 601}, {**box, "x1": 0},
                    {**box, "y1": float("nan")}, {**box, "x0": True}):
            with self.assertRaises(ValueError):
                _relative_box(bad, 600, 800)

    def test_duplicate_group_or_promotion_fails_closed(self):
        src = analysis()
        src["groups"] *= 2
        with self.assertRaises(ValueError):
            review_page(src, 44)
        for key, bad in (("route", "automatic_candidate"), ("reasons", []),
                         ("shadow_only", False), ("promotion_ready", True)):
            src = analysis()
            src["groups"][0][key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError):
                review_page(src, 44)


if __name__ == "__main__":
    unittest.main()
