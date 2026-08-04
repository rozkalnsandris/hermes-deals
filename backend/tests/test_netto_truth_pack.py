from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


TOOL = Path(__file__).resolve().parents[2] / "tools" / "netto_truth_pack.py"
SPEC = importlib.util.spec_from_file_location("netto_truth_pack", TOOL)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class NettoTruthPackTest(unittest.TestCase):
    def test_viewer_share_urls_collapse_to_one_canonical_url(self):
        text = (
            'https://wochenprospekt.netto-online.de/hz31_hasb_4/?storeid=1 '
            'https://wochenprospekt.netto-online.de/hz31_hasb_4/'
            '?share=&utm_campaign=whatsapp&utm_medium=social '
            'https%3A%2F%2Fwochenprospekt.netto-online.de%2Fhz32_hasb%2F'
            '%3Futm_campaign%3Demail'
        )
        self.assertEqual(
            MODULE.extract_viewer_urls(text, "5659"),
            [
                "https://wochenprospekt.netto-online.de/hz31_hasb_4/?storeid=5659",
                "https://wochenprospekt.netto-online.de/hz32_hasb/?storeid=5659",
            ],
        )

    def test_reader_bootstrap_is_extracted_exactly(self):
        html = """
        <script>
        var data = {"id":3264661,"groupSlug":"regionale-hz",
        "slug":"hz31_hasb_4","cacheToken":"abc==","numPages":76,
        "accountName":"Netto Marken-Discount","config":{}};
        Reader.Bootstrap.init(el, env, data);
        </script>
        """
        data = MODULE.extract_reader_bootstrap(html)
        self.assertEqual(data["id"], 3264661)
        self.assertEqual(data["groupSlug"], "regionale-hz")
        self.assertEqual(data["numPages"], 76)

    def test_reader_bootstrap_rejects_ambiguity(self):
        one = (
            'var data={"id":1,"slug":"a","cacheToken":"x","numPages":1};'
            'Reader.Bootstrap.init(el,env,data);'
        )
        with self.assertRaises(ValueError):
            MODULE.extract_reader_bootstrap(one + one.replace('"id":1', '"id":2'))

    def test_short_start_long_end_date_range(self):
        self.assertEqual(
            MODULE.extract_date_ranges("Gültig 27.07. - 01.08.2026"),
            [{
                "valid_from": "2026-07-27",
                "valid_until": "2026-08-01",
                "matched_text": "27.07. - 01.08.2026",
            }],
        )

    def test_conflicting_ranges_remain_multiple(self):
        rows = MODULE.extract_date_ranges(
            "27.07. - 01.08.2026 und 30.07. - 01.08.2026"
        )
        self.assertEqual(
            {(x["valid_from"], x["valid_until"]) for x in rows},
            {
                ("2026-07-27", "2026-08-01"),
                ("2026-07-30", "2026-08-01"),
            },
        )

    def test_spread_page_numbers_prefer_explicit_numbers(self):
        spread = {"pages": [{"number": 7}, {"number": 8}]}
        self.assertEqual(MODULE.spread_page_numbers(spread, 1), ([7, 8], 9))

    def test_spread_page_numbers_fall_back_sequentially(self):
        spread = {"pages": [{"id": "a"}, {"id": "b"}]}
        self.assertEqual(MODULE.spread_page_numbers(spread, 3), ([3, 4], 5))

    def test_page_image_prefers_at1600(self):
        page = {"images": {"at800": "/a.jpg", "at1600": "/b.jpg"}}
        self.assertEqual(MODULE.choose_page_image(page), ("/b.jpg", "images.at1600"))

    def test_query_pagination_preserves_existing_cache_token(self):
        self.assertEqual(
            MODULE.with_query(
                "https://example.test/pub/spreads.json?version=abc%3D%3D",
                {"page": "2"},
            ),
            "https://example.test/pub/spreads.json?version=abc%3D%3D&page=2",
        )

    def test_two_page_hotspot_uses_spread_coordinate(self):
        self.assertEqual(
            MODULE.assign_hotspot_page([2, 3], {"left": 0.25}),
            (2, "two_page_spread_left_coordinate"),
        )
        self.assertEqual(
            MODULE.assign_hotspot_page([2, 3], {"left": 0.75}),
            (3, "two_page_spread_left_coordinate"),
        )

    def test_corpus_key_uses_selected_store_id(self):
        self.assertEqual(
            MODULE.build_corpus_key(
                store_id="8681",
                publication="hz32_thsb",
                source_sha=(
                    "83693edca4cfbc864784ce2ca71102e513c93798b230007af0bb62351cefa1f9"
                ),
                selected_range={
                    "valid_from": "2026-08-03",
                    "valid_until": "2026-08-08",
                },
            ),
            "20260803-20260808-store8681-hz32_thsb-83693edca4cf",
        )

    def test_corpus_key_preserves_family_store_id(self):
        self.assertEqual(
            MODULE.build_corpus_key(
                store_id="5659",
                publication="hz32_hasb",
                source_sha="f" * 64,
                selected_range=None,
            ),
            "unknown-unknown-store5659-hz32_hasb-ffffffffffff",
        )

    def test_corpus_key_rejects_unsafe_store_id(self):
        for store_id in ("", "8681/../5659", "store8681", "8681 5659"):
            with self.subTest(store_id=store_id):
                with self.assertRaises(ValueError):
                    MODULE.build_corpus_key(
                        store_id=store_id,
                        publication="hz32_thsb",
                        source_sha="a" * 64,
                        selected_range=None,
                    )

    def test_corpus_key_rejects_invalid_source_sha(self):
        with self.assertRaises(ValueError):
            MODULE.build_corpus_key(
                store_id="8681",
                publication="hz32_thsb",
                source_sha="abc",
                selected_range=None,
            )

    def test_reader_product_endpoint_matches_first_party_reader_contract(self):
        self.assertEqual(
            MODULE.product_detail_url(
                "https://wochenprospekt.netto-online.de/hz31_hasb_4",
                123,
            ),
            "https://wochenprospekt.netto-online.de/hz31_hasb_4/product/123.json",
        )


if __name__ == "__main__":
    unittest.main()
