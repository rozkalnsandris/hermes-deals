from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from app.lidl.r61_shadow import (
    PageEvidence,
    PageMeta,
    TextLine,
    _card_local_validity_override,
    _decorative_title,
    _explicit_reference_price,
    _ownership_span_text,
    _parse_validity,
    _promote_page_consensus_scope,
    _same_online_column,
    _scope,
    _strict_card_roi,
    _strict_lines,
    _variable_weight_evidence,
)


def _line(text: str, bbox: tuple[float, float, float, float]) -> TextLine:
    return TextLine(text=text, bbox=bbox, spans=())


class _Price:
    def __init__(self, bbox: tuple[float, float, float, float]) -> None:
        self.bbox = bbox


class LidlR61ShadowV62ContractTests(unittest.TestCase):
    def test_decorative_promo_labels_are_not_product_titles(self) -> None:
        self.assertTrue(_decorative_title("Im Aufsteller"))
        self.assertTrue(_decorative_title("Jetzt"))
        self.assertFalse(_decorative_title("JETZT Kaffee"))
        self.assertFalse(_decorative_title("FRITT Kaustreifen"))

    def test_maxi_king_product_phrase_gets_ownership_disambiguator(self) -> None:
        adjusted = _ownership_span_text("Maxi King")
        self.assertIsNotNone(adjusted)
        self.assertNotEqual(adjusted, "Maxi King")
        self.assertEqual(_ownership_span_text("King Size"), "King Size")
        self.assertEqual(_ownership_span_text("FRITT Kaustreifen"), "FRITT Kaustreifen")

    def test_online_category_cta_may_be_wider_than_product_hotspot(self) -> None:
        self.assertTrue(_same_online_column(
            {"left_pct": 67.95, "width_pct": 10.90},
            {"left_pct": 67.95, "width_pct": 16.45},
        ))
        self.assertFalse(_same_online_column(
            {"left_pct": 50.0, "width_pct": 10.90},
            {"left_pct": 67.95, "width_pct": 16.45},
        ))

    def test_full_range(self) -> None:
        self.assertEqual(
            _parse_validity("Ab Do. 30.7. bis Sa. 1.8.", 2026, date(2026, 8, 1)),
            (date(2026, 7, 30), date(2026, 8, 1), "explicit_range"),
        )

    def test_strict_roi_clips_neighbor_normalpreis_but_keeps_own_uvp(self) -> None:
        # Geometry mirrors the verified Zott / Coppenrath row on Lidl page 15.
        page = PageEvidence(
            page=15,
            width=466.0,
            height=793.0,
            lines=(),
            links=(),
            page_valid_from=date(2026, 7, 27),
            page_valid_until=date(2026, 8, 1),
            page_validity_source="page_explicit_range",
        )
        roi = _strict_card_roi(
            page=page,
            title_bbox=(167.24, 162.25, 216.02, 185.71),
            anchor_rows=[(Decimal("1.69"), (227.16, 177.46, 281.04, 220.38))],
            all_page_prices=(
                _Price((76.0, 177.5, 132.2, 220.4)),
                _Price((227.16, 177.46, 281.04, 220.38)),
                _Price((370.21, 177.45, 423.33, 220.37)),
            ),
        )
        lines = [
            _line("UVP", (282.81, 158.99, 302.14, 169.39)),
            _line("2.99", (282.81, 167.99, 299.77, 178.39)),
            _line("Normalpreis:", (320.3, 186.5, 362.1, 195.7)),
            _line("2.29", (320.3, 195.5, 334.6, 204.7)),
        ]
        kept = _strict_lines(
            PageEvidence(
                page=15,
                width=466.0,
                height=793.0,
                lines=tuple(lines),
                links=(),
                page_valid_from=None,
                page_valid_until=None,
                page_validity_source=None,
            ),
            roi,
        )
        self.assertEqual([row.text for row in kept], ["UVP", "2.99"])
        regular, source = _explicit_reference_price(
            lines=kept,
            anchor_rows=[(Decimal("1.69"), (227.16, 177.46, 281.04, 220.38))],
        )
        self.assertEqual((regular, source), (Decimal("2.99"), "uvp"))

    def test_normalpreis_split_line_is_supported(self) -> None:
        regular, source = _explicit_reference_price(
            lines=[
                _line("Normal-", (320.3, 711.6, 346.3, 720.8)),
                _line("preis: 16.99", (320.3, 720.6, 356.1, 729.8)),
            ],
            anchor_rows=[(Decimal("14.99"), (355.4, 702.6, 422.8, 745.5))],
        )
        self.assertEqual((regular, source), (Decimal("16.99"), "normalpreis"))


    def test_normalpreis_label_then_value_line_is_supported(self) -> None:
        regular, source = _explicit_reference_price(
            lines=[
                _line("Normalpreis:", (320.32, 186.50, 362.14, 195.72)),
                _line("2.29", (320.32, 195.50, 334.64, 204.72)),
            ],
            anchor_rows=[(Decimal("1.59"), (370.21, 177.45, 423.33, 220.37))],
        )
        self.assertEqual((regular, source), (Decimal("2.29"), "normalpreis"))

    def test_normalpreis_value_can_share_unit_price_tail(self) -> None:
        regular, source = _explicit_reference_price(
            lines=[
                _line("Normalpreis:", (320.32, 720.62, 362.14, 729.84)),
                _line("1.49; 1 l = 2.98", (320.32, 729.62, 361.76, 738.84)),
            ],
            anchor_rows=[(Decimal("0.89"), (365.45, 702.57, 424.93, 745.49))],
        )
        self.assertEqual((regular, source), (Decimal("1.49"), "normalpreis"))

    def test_normalpreis_inline_can_share_kg_unit_tail(self) -> None:
        regular, source = _explicit_reference_price(
            lines=[_line("Normalpreis: 1.39; 1 kg = 3.48", (14.17, 379.54, 100.71, 388.76))],
            anchor_rows=[(Decimal("0.99"), (64.27, 352.49, 120.22, 395.41))],
        )
        self.assertEqual((regular, source), (Decimal("1.39"), "normalpreis"))

    def test_normalpreis_stacked_value_can_share_kg_unit_tail(self) -> None:
        regular, source = _explicit_reference_price(
            lines=[
                _line("Normalpreis:", (320.31, 545.61, 361.76, 554.76)),
                _line("5.99; 1 kg = 18.72", (320.31, 554.61, 369.79, 563.76)),
            ],
            anchor_rows=[(Decimal("5.29"), (372.48, 527.59, 424.86, 570.51))],
        )
        self.assertEqual((regular, source), (Decimal("5.99"), "normalpreis"))

    def test_card_local_validity_can_live_just_above_card_bbox(self) -> None:
        page = PageEvidence(
            page=1,
            width=466.0,
            height=793.0,
            lines=(
                _line("Ab Do. 30.7.", (356.73, 576.59, 421.67, 591.16)),
                _line("Ab Mo. 27.7.", (201.48, 576.59, 266.52, 591.16)),
            ),
            links=(),
            page_valid_from=date(2026, 7, 27),
            page_valid_until=date(2026, 8, 1),
            page_validity_source="page_explicit_range",
        )
        self.assertEqual(
            _card_local_validity_override(
                page=page,
                strict_roi=(296.31, 639.37, 455.49, 759.49),
                card_bbox=(292.31, 586.37, 451.49, 793.70),
                flyer_valid_until=date(2026, 8, 1),
            ),
            (date(2026, 7, 30), date(2026, 8, 1), "card_extended_explicit_start"),
        )

    def test_page_consensus_promotes_review_only_after_two_targets(self) -> None:
        rows = [
            {"page": 62, "channel": "physical_store", "scope": "in_scope",
             "rejection_reasons": [], "warnings": [], "production_ready_shadow": True},
            {"page": 62, "channel": "physical_store", "scope": "in_scope",
             "rejection_reasons": [], "warnings": [], "production_ready_shadow": True},
            {"page": 62, "channel": "physical_store", "scope": "excluded",
             "rejection_reasons": ["outside_hermes_deals_scope"], "warnings": [],
             "production_ready_shadow": False},
            {"page": 62, "channel": "physical_store", "scope": "review",
             "rejection_reasons": [], "warnings": ["scope_requires_review"],
             "production_ready_shadow": False},
        ]
        self.assertEqual(_promote_page_consensus_scope(rows), 1)
        self.assertEqual(rows[-1]["scope"], "in_scope")
        self.assertEqual(rows[-1]["scope_source"], "page_consensus_target_after_owned_evidence")
        self.assertTrue(rows[-1]["production_ready_shadow"])

    def test_page_consensus_fails_closed_with_only_one_target(self) -> None:
        rows = [
            {"page": 99, "channel": "physical_store", "scope": "in_scope",
             "rejection_reasons": [], "warnings": [], "production_ready_shadow": True},
            {"page": 99, "channel": "physical_store", "scope": "review",
             "rejection_reasons": [], "warnings": ["scope_requires_review"],
             "production_ready_shadow": False},
        ]
        self.assertEqual(_promote_page_consensus_scope(rows), 0)
        self.assertEqual(rows[-1]["scope"], "review")

    def test_right_reference_column_is_inside_roi_without_neighbor_leak(self) -> None:
        page = PageEvidence(
            page=15,
            width=466.0,
            height=793.0,
            lines=(),
            links=(),
            page_valid_from=date(2026, 7, 27),
            page_valid_until=date(2026, 8, 1),
            page_validity_source="page_explicit_range",
        )
        roi = _strict_card_roi(
            page=page,
            title_bbox=(320.32, 491.83, 363.91, 526.79),
            anchor_rows=[(Decimal("2.95"), (372.54, 527.46, 425.38, 570.38))],
            all_page_prices=(
                _Price((372.54, 527.46, 425.38, 570.38)),
                _Price((365.45, 702.57, 424.93, 745.49)),
            ),
        )
        lines = [
            _line("UVP", (437.55, 532.36, 455.75, 542.76)),
            _line("3.49", (437.55, 541.36, 453.09, 551.76)),
        ]
        kept = _strict_lines(
            PageEvidence(
                page=15,
                width=466.0,
                height=793.0,
                lines=tuple(lines),
                links=(),
                page_valid_from=None,
                page_valid_until=None,
                page_validity_source=None,
            ),
            roi,
        )
        self.assertEqual([row.text for row in kept], ["UVP", "3.49"])
        regular, source = _explicit_reference_price(
            lines=kept,
            anchor_rows=[(Decimal("2.95"), (372.54, 527.46, 425.38, 570.38))],
        )
        self.assertEqual((regular, source), (Decimal("3.49"), "uvp"))

    def test_unit_basis_normalpreis_is_not_package_reference(self) -> None:
        regular, source = _explicit_reference_price(
            lines=[
                _line("Normalpreis: 7.97/kg", (100.0, 100.0, 180.0, 112.0)),
                _line("kg-Preis = 5.30", (100.0, 114.0, 180.0, 126.0)),
            ],
            anchor_rows=[(Decimal("1.99"), (110.0, 130.0, 160.0, 170.0))],
        )
        self.assertIsNone(regular)
        self.assertIsNone(source)

    def test_variable_weight_is_fail_closed_signal(self) -> None:
        variable, units = _variable_weight_evidence(
            "nach Gewicht",
            "Preis nach Gewicht an der Kasse kg-Preis = 5.30 Normalpreis: 7.97/kg",
        )
        self.assertTrue(variable)
        self.assertEqual(units, ["5.30", "7.97"])

    def test_scope_edible_herb_wins_over_pot_word(self) -> None:
        scope, source = _scope(
            title="XXL Basilikum im Topf",
            structured_category_text="",
            page_meta=PageMeta(55, "", "Lebensmittel Grillen Sommer", True),
        )
        self.assertEqual(scope, "in_scope")
        self.assertEqual(source, "title_edible_herb")

    def test_scope_durable_tableware_is_excluded(self) -> None:
        scope, _ = _scope(
            title="SILVERCREST Kombiservice",
            structured_category_text="Kategorien/Haushalt & Küche/Geschirr & Besteck/Porzellan",
            page_meta=PageMeta(1, "", "Lebensmittel und Haushaltsartikel", True),
        )
        self.assertEqual(scope, "excluded")

    def test_scope_target_page_can_resolve_unknown_grocery_title(self) -> None:
        scope, source = _scope(
            title="WEIHENSTEPHAN Die Extrazarte",
            structured_category_text="",
            page_meta=PageMeta(64, "", "Lebensmittel Getränke Wochenende", True),
        )
        self.assertEqual(scope, "in_scope")
        self.assertEqual(source, "official_page_target_hint_title_not_excluded")


if __name__ == "__main__":
    unittest.main()

