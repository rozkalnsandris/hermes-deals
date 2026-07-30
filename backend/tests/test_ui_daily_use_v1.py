from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FAMILY = ROOT / "app" / "ui" / "index.html"
REVIEW = ROOT / "app" / "ui" / "review.html"


class UiDailyUseV1Test(unittest.TestCase):
    def test_review_actions_advance_and_expose_busy_feedback(self) -> None:
        html = REVIEW.read_text(encoding="utf-8")
        for marker in (
            'id="queueCount"',
            'id="toast"',
            'function statusLabel(status)',
            'function setBusy(next)',
            'function preferredNextRowId(itemId)',
            'options.advance',
            '{advance:true,successMessage:"Piedāvājums publicēts."}',
            'renderEmptyDetail("Šajā filtrā vairs nav rindu pārbaudei.")',
        ):
            self.assertIn(marker, html)

    def test_review_publish_notifies_open_family_ui(self) -> None:
        review = REVIEW.read_text(encoding="utf-8")
        family = FAMILY.read_text(encoding="utf-8")
        for html in (review, family):
            self.assertIn('hermesDealsReviewRefresh', html)
            self.assertIn('BroadcastChannel', html)
            self.assertIn('hermes-deals-review', html)
        self.assertIn('function notifyDealsRefresh(item)', review)
        self.assertIn('function scheduleReviewRefresh()', family)
        self.assertIn('loadGrid(false)', family)

    def test_review_statuses_are_human_readable_and_closed_rows_are_read_only(self) -> None:
        html = REVIEW.read_text(encoding="utf-8")
        for marker in (
            'pending:"Gaida pārbaudi"',
            'draft:"Labots"',
            'needs_followup:"Jāpārbauda vēl"',
            'approved:"Publicēts"',
            'rejected:"Noraidīts"',
            'const e=selected.effective_payload||{},p=selected.provenance||{},open=OPEN_STATUSES.has(selected.status);',
            '${open?`<button class="primary" id="save">',
            'function detailMessage(detail,fallback)',
            'form?.classList.add("readonly-form")',
            'form?.querySelectorAll("input,select,textarea,button").forEach(node=>node.disabled=true)',
            '{advance:true,successMessage:"Lapas pārbaude pabeigta."}',
        ):
            self.assertIn(marker, html)
        self.assertNotIn('alert("Fast approval neizdevās:', html)


if __name__ == "__main__":
    unittest.main()
