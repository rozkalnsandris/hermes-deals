from __future__ import annotations

import unittest

from app.lidl_ocr_inspector import _refine_zone_classification, _dry_run_candidates, attach_semantic_pairings, attach_unit_price_consistency, merge_credible_price_zones, parse_tsv, price_candidates, select_grocery_pages, select_sample_pages


HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"


class LidlOcrInspectorTest(unittest.TestCase):
    def test_price_candidates_cover_decimal_and_split_cent_formats(self) -> None:
        self.assertEqual(price_candidates("Paprika 1,29 € Milch 2 49 EUR"), ["1,29", "2,49"])

    def test_hyphenated_product_count_is_not_a_price(self) -> None:
        self.assertEqual(price_candidates("9-teilig 10-teilig Set"), [])

    def test_parse_tsv_reconstructs_lines_and_prices(self) -> None:
        tsv = HEADER + """5\t1\t1\t1\t1\t1\t10\t20\t100\t20\t95\tPaprika
5\t1\t1\t1\t1\t2\t120\t20\t50\t20\t93\t1,29
5\t1\t1\t1\t1\t3\t180\t20\t20\t20\t90\t€
"""
        parsed = parse_tsv(tsv)
        self.assertEqual(parsed["word_count"], 3)
        self.assertEqual(parsed["price_candidates"], ["1,29"])
        self.assertEqual(parsed["malformed_tsv_rows"], 0)
        self.assertIn("Paprika 1,29 €", parsed["plain_text"])

    def test_literal_quote_does_not_swallow_following_tsv_rows(self) -> None:
        # Tesseract TSV is not CSV quoted. A literal quote in OCR text must stay
        # a normal text character and must not consume subsequent physical rows.
        tsv = HEADER + """5\t1\t1\t1\t1\t1\t10\t20\t70\t20\t90\t\"AEG
5\t1\t1\t1\t1\t2\t90\t20\t50\t20\t91\t2,29
5\t1\t1\t1\t2\t1\t10\t50\t80\t20\t92\tMilch
"""
        parsed = parse_tsv(tsv)
        self.assertEqual(parsed["word_count"], 3)
        self.assertEqual(parsed["malformed_tsv_rows"], 0)
        self.assertLess(parsed["text_chars"], 100)
        self.assertEqual(parsed["price_candidates"], ["2,29"])

    def test_unit_price_is_filtered_from_credible_sale_zones(self) -> None:
        tsv = HEADER + """5\t1\t1\t1\t1\t1\t10\t20\t30\t20\t95\t1kg
5\t1\t1\t1\t1\t2\t45\t20\t20\t20\t95\t=
5\t1\t1\t1\t1\t3\t70\t20\t50\t20\t94\t7,16
"""
        parsed = parse_tsv(tsv)
        self.assertTrue(parsed["price_zones"])
        self.assertEqual(parsed["price_zones"][0]["classification"], "unit_price")
        self.assertEqual(parsed["credible_price_zones"], [])

    def test_large_split_euro_cent_geometry_becomes_candidate(self) -> None:
        tsv = HEADER + """5\t1\t1\t1\t1\t1\t10\t20\t80\t20\t92\tPaprika
5\t1\t2\t1\t1\t1\t200\t100\t70\t70\t95\t1
5\t1\t2\t1\t1\t2\t272\t95\t34\t36\t93\t29
5\t1\t3\t1\t1\t1\t180\t180\t100\t20\t90\tAktion
"""
        parsed = parse_tsv(tsv)
        zones = [z for z in parsed["credible_price_zones"] if z["token"] == "1,29"]
        self.assertTrue(zones)
        self.assertEqual(zones[0]["source"], "split_geometry")
        self.assertGreaterEqual(zones[0]["score"], 3.0)


    def test_zero_token_is_not_a_price(self) -> None:
        self.assertEqual(price_candidates("Lidl Reisen je 3:000€"), [])

    def test_nearby_shipping_context_downgrades_large_number(self) -> None:
        tsv = HEADER + """5\t1\t1\t1\t1\t1\t100\t100\t120\t70\t95\t5,95
5\t1\t2\t1\t1\t1\t90\t190\t260\t24\t94\tVersandkostenpauschale
"""
        parsed = parse_tsv(tsv)
        zones = [z for z in parsed["price_zones"] if z["token"] == "5,95"]
        self.assertTrue(zones)
        self.assertEqual(zones[0]["classification"], "shipping")
        self.assertEqual(parsed["credible_price_zones"], [])

    def test_nearby_installment_context_is_filtered(self) -> None:
        tsv = HEADER + """5\t1\t1\t1\t1\t1\t100\t100\t120\t70\t95\t18,73
5\t1\t2\t1\t1\t1\t90\t180\t220\t24\t94\tRatenzahlung
5\t1\t2\t1\t1\t2\t320\t180\t120\t24\t94\tpro Monat
"""
        parsed = parse_tsv(tsv)
        zones = [z for z in parsed["price_zones"] if z["token"] == "18,73"]
        self.assertTrue(zones)
        self.assertEqual(zones[0]["classification"], "installment")
        self.assertEqual(parsed["credible_price_zones"], [])

    def test_small_bare_decimal_is_not_credible_sale_price(self) -> None:
        tsv = HEADER + """5\t1\t1\t1\t1\t1\t100\t100\t100\t20\t95\t0,75
5\t1\t2\t1\t1\t1\t90\t160\t220\t20\t94\tToskana Italien
"""
        parsed = parse_tsv(tsv)
        self.assertTrue(parsed["price_zones"])
        self.assertEqual(parsed["credible_price_zones"], [])

    def test_large_price_gets_nearby_product_pairing_candidate(self) -> None:
        tsv = HEADER + """5\t1\t1\t1\t1\t1\t100\t100\t260\t24\t95\tMetzgerfrisch
5\t1\t1\t1\t1\t2\t370\t100\t160\t24\t95\tHähnchen
5\t1\t2\t1\t1\t1\t160\t180\t120\t90\t96\t4,29
"""
        parsed = parse_tsv(tsv)
        zones = [z for z in parsed["credible_price_zones"] if z["token"] == "4,29"]
        self.assertTrue(zones)
        self.assertIsNotNone(zones[0]["best_pairing"])
        self.assertIn("Metzgerfrisch", zones[0]["best_pairing"]["text"])

    def test_multi_psm_merge_deduplicates_same_price_and_tracks_support(self) -> None:
        zone_a = {"token": "1,29", "bbox": {"left": 100, "top": 200, "right": 200, "bottom": 280}, "score": 5.0, "best_pairing": None}
        zone_b = {"token": "1,29", "bbox": {"left": 110, "top": 205, "right": 210, "bottom": 285}, "score": 5.5, "best_pairing": None}
        merged = merge_credible_price_zones({6: {"credible_price_zones": [zone_a]}, 11: {"credible_price_zones": [zone_b]}})
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["psm_modes"], [6, 11])
        self.assertEqual(merged[0]["psm_support"], 2)
        self.assertGreater(merged[0]["ensemble_score"], merged[0]["score"])

    def test_multi_psm_merge_keeps_conflicting_tokens_separate(self) -> None:
        a = {"token": "1,29", "bbox": {"left": 100, "top": 200, "right": 200, "bottom": 280}, "score": 5.0}
        b = {"token": "7,29", "bbox": {"left": 105, "top": 202, "right": 205, "bottom": 282}, "score": 5.0}
        merged = merge_credible_price_zones({6: {"credible_price_zones": [a]}, 12: {"credible_price_zones": [b]}})
        self.assertEqual({item["token"] for item in merged}, {"1,29", "7,29"})

    def test_multi_psm_merge_does_not_collapse_same_token_far_apart(self) -> None:
        a = {"token": "0,99", "bbox": {"left": 100, "top": 200, "right": 200, "bottom": 280}, "score": 5.0}
        b = {"token": "0,99", "bbox": {"left": 1000, "top": 1500, "right": 1100, "bottom": 1580}, "score": 5.0}
        merged = merge_credible_price_zones({6: {"credible_price_zones": [a]}, 11: {"credible_price_zones": [b]}})
        self.assertEqual(len(merged), 2)


    def test_semantic_pairing_rejects_url_dimension_noise(self) -> None:
        zones = [{
            "token": "9,49",
            "source": "split_geometry",
            "score": 7.5,
            "ensemble_score": 8.0,
            "psm_support": 2,
            "pairing_candidates": [
                {"text": "www.herkunft-", "score": 4.8, "grocery_hits": []},
                {"text": "x B 40 x H 42 cm", "score": 4.6, "grocery_hits": []},
            ],
        }]
        page = {"keywords_grocery_hits": ["milch"], "keywords_text": "Metzgerfrisch Milch Hackfleisch"}
        attach_semantic_pairings(zones, page)
        self.assertIsNone(zones[0]["best_semantic_pairing"])
        self.assertFalse(zones[0]["automatic_candidate"])
        self.assertEqual(zones[0]["automatic_reason"], "pairing_not_semantic")

    def test_semantic_pairing_accepts_keyword_backed_grocery_label(self) -> None:
        zones = [{
            "token": "1,99",
            "source": "split_geometry",
            "score": 7.5,
            "ensemble_score": 7.5,
            "psm_support": 1,
            "pairing_candidates": [
                {"text": "Rote Apfel", "score": 4.52, "grocery_hits": ["apfel"]},
            ],
        }]
        page = {
            "keywords_grocery_hits": ["äpfel"],
            "keywords_text": "Rote Äpfel Fruchtig-Süß Aktion",
            "alt_text": "Angebot für rote Äpfel",
        }
        attach_semantic_pairings(zones, page)
        best = zones[0]["best_semantic_pairing"]
        self.assertIsNotNone(best)
        self.assertIn("apfel", best["keyword_overlap"])
        self.assertTrue(zones[0]["automatic_candidate"])

    def test_semantic_pairing_rejects_generic_or_package_only_label(self) -> None:
        zones = [
            {
                "token": "0,99", "source": "line_text", "score": 5.0, "ensemble_score": 5.5, "psm_support": 2,
                "pairing_candidates": [{"text": "500g", "score": 6.3, "grocery_hits": []}],
            },
            {
                "token": "0,99", "source": "line_text", "score": 5.0, "ensemble_score": 5.5, "psm_support": 2,
                "pairing_candidates": [{"text": "Gemüse", "score": 6.3, "grocery_hits": ["gemüse"]}],
            },
        ]
        page = {"keywords_grocery_hits": ["gemüse"], "keywords_text": "Gemüse Pesto Tomaten"}
        attach_semantic_pairings(zones, page)
        self.assertFalse(zones[0]["automatic_candidate"])
        self.assertFalse(zones[1]["automatic_candidate"])

    def test_semantic_pairing_requires_price_support_for_plain_line_text(self) -> None:
        zones = [{
            "token": "0,75",
            "source": "line_text",
            "score": 4.5,
            "ensemble_score": 4.5,
            "psm_support": 1,
            "pairing_candidates": [{"text": "Rotwein trocken", "score": 6.6, "grocery_hits": ["wein"]}],
        }]
        page = {"keywords_grocery_hits": ["wein"], "keywords_text": "Rotwein trocken Italien"}
        attach_semantic_pairings(zones, page)
        self.assertIsNotNone(zones[0]["best_semantic_pairing"])
        self.assertFalse(zones[0]["automatic_candidate"])
        self.assertEqual(zones[0]["automatic_reason"], "price_support_too_weak")


    def test_unit_price_math_verifies_hackfleisch_800g(self) -> None:
        zones = [{
            "token": "9,49",
            "bbox": {"left": 300, "top": 1600, "right": 880, "bottom": 1700},
            "automatic_candidate": True,
            "best_semantic_pairing": {"text": "Hackfleisch"},
        }]
        unit_zone = {
            "token": "11,86",
            "classification": "unit_price",
            "bbox": {"left": 330, "top": 1450, "right": 650, "bottom": 1480},
            "line_text": "1kg = 11.86",
            "nearby_text": ["Je 800 g", "Hackfleisch"],
        }
        attach_unit_price_consistency(zones, {11: {"price_zones": [unit_zone]}})
        self.assertTrue(zones[0]["unit_price_math_verified"])
        check = zones[0]["unit_price_crosschecks"][0]
        self.assertAlmostEqual(check["expected_sale_price"], 9.49, places=2)
        self.assertIn("hackfleisch", check["label_overlap"])

    def test_unit_price_math_verifies_tomaten_400g(self) -> None:
        zones = [{
            "token": "0,59",
            "bbox": {"left": 700, "top": 1600, "right": 900, "bottom": 1700},
            "automatic_candidate": True,
            "best_semantic_pairing": {"text": "Tomaten"},
        }]
        unit_zone = {
            "token": "1,48",
            "classification": "unit_price",
            "bbox": {"left": 720, "top": 1450, "right": 900, "bottom": 1480},
            "line_text": "1kg = 1.48",
            "nearby_text": ["Je 400g", "Tomaten"],
        }
        attach_unit_price_consistency(zones, {12: {"price_zones": [unit_zone]}})
        self.assertTrue(zones[0]["unit_price_math_verified"])
        self.assertAlmostEqual(zones[0]["unit_price_crosschecks"][0]["expected_sale_price"], 0.59, places=2)

    def test_unit_price_math_marks_strong_mismatch_as_conflict(self) -> None:
        zones = [{
            "token": "4,99",
            "bbox": {"left": 700, "top": 1600, "right": 900, "bottom": 1700},
            "automatic_candidate": True,
            "best_semantic_pairing": {"text": "Pesto"},
        }]
        unit_zone = {
            "token": "5,21",
            "classification": "unit_price",
            "bbox": {"left": 720, "top": 1450, "right": 900, "bottom": 1480},
            "line_text": "1kg = 5.21",
            "nearby_text": ["Je 190 g", "Pesto"],
        }
        attach_unit_price_consistency(zones, {11: {"price_zones": [unit_zone]}})
        self.assertFalse(zones[0]["unit_price_math_verified"])
        self.assertTrue(zones[0]["unit_price_math_conflict"])

    def test_unit_price_math_ignores_nonautomatic_zone(self) -> None:
        zones = [{
            "token": "0,99",
            "bbox": {"left": 100, "top": 100, "right": 200, "bottom": 180},
            "automatic_candidate": False,
            "best_semantic_pairing": {"text": "Pesto"},
        }]
        unit_zone = {
            "token": "5,21",
            "classification": "unit_price",
            "bbox": {"left": 110, "top": 200, "right": 220, "bottom": 230},
            "line_text": "1kg = 5.21",
            "nearby_text": ["Je 190 g", "Pesto"],
        }
        attach_unit_price_consistency(zones, {11: {"price_zones": [unit_zone]}})
        self.assertEqual(zones[0]["unit_price_crosschecks"], [])
        self.assertFalse(zones[0]["unit_price_math_verified"])

    def test_sample_selection_prioritizes_unstructured_grocery_pages(self) -> None:
        report = {
            "pages": [
                {"number": 1, "zoom": "z1", "keywords_grocery_hits": ["milch"], "all_scalar_price_tokens": [], "links_with_product_details": 0},
                {"number": 2, "zoom": "z2", "keywords_grocery_hits": ["brot"], "all_scalar_price_tokens": [], "links_with_product_details": 0},
                {"number": 3, "zoom": "z3", "keywords_grocery_hits": ["wasser"], "all_scalar_price_tokens": ["1,29"], "links_with_product_details": 0},
                {"number": 4, "zoom": "z4", "keywords_grocery_hits": ["reis"], "all_scalar_price_tokens": [], "links_with_product_details": 2},
            ]
        }
        selected = select_sample_pages(report, max_pages=4)
        self.assertEqual([p["number"] for p in selected[:2]], [1, 2])
        self.assertEqual({p["number"] for p in selected}, {1, 2, 3, 4})


    def test_unit_price_math_reads_package_from_same_line(self) -> None:
        zones = [{
            "token": "0,99",
            "bbox": {"left": 1100, "top": 1040, "right": 1370, "bottom": 1170},
            "automatic_candidate": True,
            "best_semantic_pairing": {"text": "Pesto"},
        }]
        unit_zone = {
            "token": "5,21",
            "classification": "unit_price",
            "bbox": {"left": 1110, "top": 1200, "right": 1360, "bottom": 1230},
            "line_text": "Je 190 g; 1kg = 5.21",
            "nearby_text": ["Versch. Sorten.", "Pesto"],
        }
        attach_unit_price_consistency(zones, {11: {"price_zones": [unit_zone]}})
        self.assertTrue(zones[0]["unit_price_math_verified"])
        check = zones[0]["unit_price_crosschecks"][0]
        self.assertTrue(check["package_text"].replace(" ", "").lower().endswith("190g"))
        self.assertAlmostEqual(check["expected_sale_price"], 0.99, places=2)

    def test_unit_price_basis_is_not_mistaken_for_package(self) -> None:
        zones = [{
            "token": "9,49",
            "bbox": {"left": 300, "top": 1600, "right": 880, "bottom": 1700},
            "automatic_candidate": True,
            "best_semantic_pairing": {"text": "Hackfleisch"},
        }]
        unit_zone = {
            "token": "11,86",
            "classification": "unit_price",
            "bbox": {"left": 330, "top": 1450, "right": 650, "bottom": 1480},
            "line_text": "1kg = 11.86",
            "nearby_text": ["Je 800 g", "Hackfleisch"],
        }
        attach_unit_price_consistency(zones, {11: {"price_zones": [unit_zone]}})
        check = zones[0]["unit_price_crosschecks"][0]
        self.assertTrue(check["package_text"].replace(" ", "").lower().endswith("800g"))
        self.assertTrue(zones[0]["unit_price_math_verified"])

    def test_single_digit_math_conflict_becomes_correction_candidate(self) -> None:
        zones = [{
            "token": "0,59",
            "bbox": {"left": 1195, "top": 2145, "right": 1370, "bottom": 2231},
            "automatic_candidate": True,
            "psm_support": 2,
            "best_semantic_pairing": {"text": "Penne Rigate"},
        }]
        # Deliberately farther than the old 260px correction threshold, but
        # still within the same dense Lidl card.  Dual PSM consensus + semantic
        # overlap + one-digit unit-price arithmetic should make this auditable.
        unit_zone = {
            "token": "1,38",
            "classification": "unit_price",
            "bbox": {"left": 1110, "top": 1720, "right": 1360, "bottom": 1750},
            "line_text": "1kg = 1.38",
            "nearby_text": ["Je 500g", "Penne Rigate"],
        }
        attach_unit_price_consistency(zones, {11: {"price_zones": [unit_zone]}})
        self.assertTrue(zones[0]["unit_price_math_conflict"])
        self.assertTrue(zones[0]["unit_price_math_correction_candidate"])
        self.assertEqual(zones[0]["unit_price_math_correction_expected_price"], 0.69)
        self.assertTrue(zones[0]["unit_price_math_correction_dual_psm"])
        self.assertGreater(zones[0]["unit_price_math_correction_distance"], 260)
        self.assertLessEqual(zones[0]["unit_price_math_correction_distance"], 650)
        self.assertEqual(zones[0]["unit_price_math_correction_reason"], "single_digit_ocr_error_supported_by_unit_math")

    def test_wide_single_digit_conflict_without_dual_psm_is_not_correctable(self) -> None:
        zones = [{
            "token": "0,59",
            "bbox": {"left": 1195, "top": 2145, "right": 1370, "bottom": 2231},
            "automatic_candidate": True,
            "psm_support": 1,
            "best_semantic_pairing": {"text": "Penne Rigate"},
        }]
        unit_zone = {
            "token": "1,38",
            "classification": "unit_price",
            "bbox": {"left": 1110, "top": 1720, "right": 1360, "bottom": 1750},
            "line_text": "1kg = 1.38",
            "nearby_text": ["Je 500g", "Penne Rigate"],
        }
        attach_unit_price_consistency(zones, {11: {"price_zones": [unit_zone]}})
        self.assertTrue(zones[0]["unit_price_math_conflict"])
        self.assertFalse(zones[0]["unit_price_math_correction_candidate"])

    def test_zero_distance_math_conflict_is_treated_as_close(self) -> None:
        zones = [{
            "token": "0,59",
            "bbox": {"left": 100, "top": 100, "right": 200, "bottom": 200},
            "automatic_candidate": True,
            "psm_support": 2,
            "best_semantic_pairing": {"text": "Penne Rigate"},
        }]
        unit_zone = {
            "token": "1,38",
            "classification": "unit_price",
            "bbox": {"left": 100, "top": 100, "right": 200, "bottom": 200},
            "line_text": "1kg = 1.38",
            "nearby_text": ["Je 500g", "Penne Rigate"],
        }
        attach_unit_price_consistency(zones, {11: {"price_zones": [unit_zone]}})
        self.assertTrue(zones[0]["unit_price_math_conflict"])
        self.assertTrue(zones[0]["unit_price_math_correction_candidate"])
        self.assertEqual(zones[0]["unit_price_math_correction_distance"], 0.0)

    def test_large_math_conflict_is_not_auto_correctable(self) -> None:
        zones = [{
            "token": "0,59",
            "bbox": {"left": 700, "top": 1600, "right": 900, "bottom": 1700},
            "automatic_candidate": True,
            "best_semantic_pairing": {"text": "Pesto"},
        }]
        unit_zone = {
            "token": "5,21",
            "classification": "unit_price",
            "bbox": {"left": 720, "top": 1450, "right": 900, "bottom": 1480},
            "line_text": "Je 190 g; 1kg = 5.21",
            "nearby_text": ["Pesto"],
        }
        attach_unit_price_consistency(zones, {11: {"price_zones": [unit_zone]}})
        self.assertTrue(zones[0]["unit_price_math_conflict"])
        self.assertFalse(zones[0]["unit_price_math_correction_candidate"])



    def test_select_grocery_pages_returns_all_metadata_grocery_pages(self) -> None:
        report = {"pages": [
            {"number": 3, "zoom": "z3", "keywords_grocery_hits": ["milch"]},
            {"number": 1, "zoom": "z1", "keywords_grocery_hits": ["apfel"]},
            {"number": 2, "zoom": "z2", "keywords_grocery_hits": []},
            {"number": 4, "keywords_grocery_hits": ["brot"]},
        ]}
        selected = select_grocery_pages(report)
        self.assertEqual([p["number"] for p in selected], [1, 3])

    def test_dry_run_candidates_never_mark_db_write_eligible(self) -> None:
        results = [{
            "page": 10, "success": True,
            "ensemble_credible_price_zones": [{
                "token": "9,49", "automatic_candidate": True, "unit_price_math_verified": True,
                "psm_modes": [11, 12], "psm_support": 2,
                "best_semantic_pairing": {"text": "Hackfleisch", "semantic_score": 6.6, "keyword_overlap": ["hackfleisch"]},
                "unit_price_crosschecks": [{"expected_sale_price": 9.49, "package_text": "Je 800 g", "unit_price": 11.86, "unit_kind": "kg"}],
                "bbox": {"left": 1, "top": 2, "right": 3, "bottom": 4},
            }],
        }]
        candidates = _dry_run_candidates(results)
        self.assertEqual(candidates[0]["evidence_tier"], "math_verified")
        self.assertFalse(candidates[0]["db_write_eligible"])

    def test_dry_run_candidate_keeps_correction_as_review_only(self) -> None:
        results = [{
            "page": 23, "success": True,
            "ensemble_credible_price_zones": [{
                "token": "0,59", "automatic_candidate": True, "unit_price_math_conflict": True,
                "unit_price_math_correction_candidate": True, "unit_price_math_correction_expected_price": 0.69,
                "psm_modes": [11, 12], "psm_support": 2,
                "best_semantic_pairing": {"text": "Penne Rigate", "semantic_score": 8.6, "keyword_overlap": ["rigate"]},
                "unit_price_crosschecks": [{"expected_sale_price": 0.69, "package_text": "Je 500g", "unit_price": 1.38, "unit_kind": "kg"}],
                "bbox": {"left": 1, "top": 2, "right": 3, "bottom": 4},
            }],
        }]
        candidate = _dry_run_candidates(results)[0]
        self.assertEqual(candidate["evidence_tier"], "math_correction_review")
        self.assertEqual(candidate["ocr_price_eur"], 0.59)
        self.assertEqual(candidate["proposed_corrected_price_eur"], 0.69)
        self.assertFalse(candidate["db_write_eligible"])

    def test_dry_run_candidate_marks_unresolved_conflict(self) -> None:
        results = [{
            "page": 5, "success": True,
            "ensemble_credible_price_zones": [{
                "token": "2,49", "automatic_candidate": True, "unit_price_math_conflict": True,
                "unit_price_math_correction_candidate": False,
                "psm_modes": [11, 12], "psm_support": 2,
                "best_semantic_pairing": {"text": "Joghurt", "semantic_score": 7.0, "keyword_overlap": ["joghurt"]},
                "unit_price_crosschecks": [{"expected_sale_price": 1.99, "package_text": "Je 500g", "unit_price": 3.98, "unit_kind": "kg"}],
                "bbox": {"left": 1, "top": 2, "right": 3, "bottom": 4},
            }],
        }]
        self.assertEqual(_dry_run_candidates(results)[0]["evidence_tier"], "unresolved_math_conflict")



    def test_real_lidl_liter_amount_is_not_sale_price(self) -> None:
        zone = {"token": "1,75", "line_text": "ER 1.75 Liter", "nearby_text": []}
        self.assertEqual(_refine_zone_classification(zone), "package_amount")

    def test_real_lidl_gebinde_multipack_amount_is_not_sale_price(self) -> None:
        zone = {"token": "0,33", "line_text": "Je Gebinde 18x 0,33 |", "nearby_text": []}
        self.assertEqual(_refine_zone_classification(zone), "package_amount")

    def test_real_lidl_standardpackung_amount_is_not_sale_price(self) -> None:
        zone = {"token": "0,33", "line_text": "Standardpackung: 0,33 |", "nearby_text": []}
        self.assertEqual(_refine_zone_classification(zone), "package_amount")

    def test_package_amount_filter_is_token_specific_on_mixed_line(self) -> None:
        sale = {"token": "2,99", "line_text": "2,99 Je 0,75 l", "nearby_text": []}
        package = {"token": "0,75", "line_text": "2,99 Je 0,75 l", "nearby_text": []}
        self.assertEqual(_refine_zone_classification(sale), "sale_candidate")
        self.assertEqual(_refine_zone_classification(package), "package_amount")

    def test_pfand_filter_is_token_specific_on_mixed_line(self) -> None:
        sale = {"token": "9,99", "line_text": "9,99 zzgl. 0.25 Pfand", "nearby_text": []}
        deposit = {"token": "0,25", "line_text": "9,99 zzgl. 0.25 Pfand", "nearby_text": []}
        self.assertEqual(_refine_zone_classification(sale), "sale_candidate")
        self.assertEqual(_refine_zone_classification(deposit), "deposit")

if __name__ == "__main__":
    unittest.main()
