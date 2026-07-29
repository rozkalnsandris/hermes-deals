from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FAMILY = ROOT / "app" / "ui" / "index.html"
REVIEW = ROOT / "app" / "ui" / "review.html"


class UiLatvianDateAndReviewOpenTest(unittest.TestCase):
    def test_family_ui_uses_deterministic_latvian_date_display(self) -> None:
        html = FAMILY.read_text(encoding="utf-8")
        for marker in (
            'id="asOf" type="hidden"',
            'id="asOfDisplay"',
            'placeholder="DD.MM.GGGG"',
            "function fmtDate(v)",
            "function parseLvDate(v)",
            "function commitDisplayDate()",
            "setAsOfIso(todayLocal())",
            "setAsOfIso(dateFromOffset",
        ):
            self.assertIn(marker, html)
        self.assertNotIn(
            '<input id="asOf" class="control" type="date">',
            html,
        )
        self.assertNotIn("${d.as_of}", html)
        self.assertNotIn("${esc(d.valid_from)}", html)

    def test_review_ui_defaults_to_all_open_states_and_keeps_drafts_visible(self) -> None:
        html = REVIEW.read_text(encoding="utf-8")
        for marker in (
            'value="open" selected',
            'Atvērtie (gaida + laboti + jāpārbauda)',
            'status==="open"?rawItems.filter',
            '"pending","draft","needs_followup"',
            'placeholder="DD.MM.GGGG"',
            "function parseLvDate(v)",
            'dateValue("f_from")',
            'dateValue("f_until")',
        ):
            self.assertIn(marker, html)
        self.assertNotIn('<option value="pending" selected>', html)
        self.assertNotIn('type="date"', html)

    def test_empty_family_search_explains_matching_review_state(self) -> None:
        html = FAMILY.read_text(encoding="utf-8")
        for marker in (
            'id="reviewSearchHint"',
            "async function updateReviewSearchHint(d)",
            "/api/v1/review-items?source_chain=lidl&limit=500",
            'draft:"labots, vēl nav publicēts"',
            'pending:"gaida pārbaudi"',
            'approved:"publicēts"',
            'href="/ui/review"',
        ):
            self.assertIn(marker, html)


if __name__ == "__main__":
    unittest.main()
