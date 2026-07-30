from __future__ import annotations

from datetime import date
import unittest

from app.structured_source_shadow import (
    extract_lidl_flyers,
    extract_lidl_store_id,
    extract_netto_direct_viewers,
    extract_netto_group_slug,
    select_lidl_period_variants,
    summarize_lidl_detail,
    summarize_publitas,
)


class StructuredSourceShadowTest(unittest.TestCase):
    def test_netto_direct_viewers_ignore_share_hosts(self) -> None:
        sample = (
            '<a href="https://wochenprospekt.netto-online.de/hz30_hasb_4/?storeid=5659">A</a>'
            '<a href="https://wa.me/?text=https%3A%2F%2Fwochenprospekt.netto-online.de%2Fhz31_hasb%2F%3Fstoreid%3D5659">B</a>'
        )
        self.assertEqual(
            extract_netto_direct_viewers(sample),
            {
                "hz30_hasb_4": "https://wochenprospekt.netto-online.de/hz30_hasb_4/?storeid=5659",
                "hz31_hasb": "https://wochenprospekt.netto-online.de/hz31_hasb/?storeid=5659",
            },
        )

    def test_netto_group_slug(self) -> None:
        self.assertEqual(
            extract_netto_group_slug('{"groupSlug":"regionale-hz"}'),
            "regionale-hz",
        )

    def test_publitas_summary_counts_pages_and_hotspots(self) -> None:
        payload = {
            "config": {"publicationId": 7, "slug": "hz30", "downloadPdfUrl": "/x.pdf"},
            "spreads": [
                {"pages": ["/p1"], "hotspots": [{"type": "externalLink"}]},
                {"pages": ["/p2"], "hotspots": [{"type": "video"}, {"type": "externalLink"}]},
            ],
        }
        summary = summarize_publitas(payload)
        self.assertEqual(summary["publication_id"], 7)
        self.assertEqual(summary["page_count"], 2)
        self.assertEqual(summary["hotspot_types"]["externalLink"], 2)

    def test_lidl_store_id_extracts_object_number(self) -> None:
        self.assertEqual(
            extract_lidl_store_id('{"objectNumber":198},"DE06664","Dortmund - Husener Straße"'),
            "DE06664",
        )

    def test_lidl_flyer_walk_deduplicates(self) -> None:
        flyer = {
            "id": "f1",
            "flyerJson": "https://example/f1",
            "offerStartDate": "2026-07-20",
            "offerEndDate": "2026-07-25",
        }
        self.assertEqual(len(extract_lidl_flyers({"a": [flyer], "b": flyer})), 1)

    def test_lidl_periods_follow_runtime_date_instead_of_fixed_weeks(self) -> None:
        def flyer(
            identifier: str,
            start: str,
            end: str,
            *,
            name: str = "Aktionsprospekt",
        ) -> dict[str, str]:
            return {
                "id": identifier,
                "name": name,
                "flyerJson": f"https://example/{identifier}",
                "offerStartDate": start,
                "offerEndDate": end,
            }

        current, upcoming = select_lidl_period_variants(
            [
                flyer("old", "2026-07-20", "2026-07-25"),
                flyer("current-a", "2026-07-27", "2026-08-01"),
                flyer("current-b", "2026-07-27", "2026-08-01"),
                flyer("next", "2026-08-03", "2026-08-08"),
                flyer("later", "2026-08-10", "2026-08-15"),
                flyer("other", "2026-07-27", "2026-08-01", name="Other"),
            ],
            date(2026, 7, 30),
        )

        self.assertEqual(
            [row["id"] for row in current],
            ["current-a", "current-b"],
        )
        self.assertEqual([row["id"] for row in upcoming], ["next"])

    def test_lidl_periods_fail_closed_without_active_window(self) -> None:
        current, upcoming = select_lidl_period_variants(
            [
                {
                    "name": "Aktionsprospekt",
                    "flyerJson": "https://example/future",
                    "offerStartDate": "2026-08-03",
                    "offerEndDate": "2026-08-08",
                }
            ],
            date(2026, 7, 30),
        )
        self.assertEqual(current, [])
        self.assertEqual(upcoming, [])

    def test_lidl_detail_makes_price_gap_explicit(self) -> None:
        payload = {
            "flyer": {
                "pages": [
                    {
                        "links": [
                            {
                                "position": {"left": 0.1, "top": 0.2},
                                "productDetails": {"productId": "123", "title": "Milch"},
                            }
                        ]
                    }
                ]
            }
        }
        summary = summarize_lidl_detail(payload)
        self.assertEqual(summary["linked_product_detail_count"], 1)
        self.assertEqual(summary["product_detail_price_field_hits"], 0)
        self.assertEqual(summary["link_geometry_hits"], 1)


if __name__ == "__main__":
    unittest.main()
