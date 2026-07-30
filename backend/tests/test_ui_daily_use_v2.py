from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "app" / "ui" / "review.html"


class UiDailyUseV2Test(unittest.TestCase):
    def test_review_queue_has_search_status_counts_and_url_state(self) -> None:
        html = REVIEW.read_text(encoding="utf-8")
        for marker in (
            'id="reviewSearch"',
            'id="statusCounts"',
            'function statusFilteredItems()',
            'function filteredItems()',
            'function renderStatusCounts()',
            'function syncReviewUrl(itemId=selected?.id||"")',
            'const initialParams=new URLSearchParams(location.search)',
        ):
            self.assertIn(marker, html)

    def test_review_queue_supports_fast_navigation(self) -> None:
        html = REVIEW.read_text(encoding="utf-8")
        for marker in (
            'id="prevItem"',
            'id="nextItem"',
            'id="detailPosition"',
            'function moveSelection(delta)',
            'event.key==="ArrowDown"',
            'event.key==="ArrowUp"',
            'event.key==="/"',
            'event.key.toLocaleLowerCase()==="s"',
        ):
            self.assertIn(marker, html)

    def test_review_queue_protects_unsaved_edits(self) -> None:
        html = REVIEW.read_text(encoding="utf-8")
        for marker in (
            'id="dirtyState"',
            'function editableFormState()',
            'function captureFormState()',
            'function confirmDiscard()',
            'window.confirm("Ir nesaglabātas izmaiņas.',
            'window.addEventListener("beforeunload"',
            'Noraidot, nesaglabātie labojumi tiks atmesti.',
        ):
            self.assertIn(marker, html)

    def test_review_actions_are_sticky_and_mobile_safe(self) -> None:
        html = REVIEW.read_text(encoding="utf-8")
        self.assertIn('class="actions sticky-actions"', html)
        self.assertIn('.actions.sticky-actions{position:sticky;bottom:0;', html)
        self.assertIn('Ctrl+S saglabāt · ↑/↓ pārvietoties · / meklēt', html)

    def test_date_picker_marks_form_dirty_and_busy_state_keeps_navigation_truthful(self) -> None:
        html = REVIEW.read_text(encoding="utf-8")
        for marker in (
            'textInput.dispatchEvent(new Event("input",{bubbles:true}))',
            'document.querySelectorAll("#detail button,#reload,#status,#reviewSearch,#statusCounts button")',
            'updateDetailNav();',
            '${busy?"disabled":""}',
        ):
            self.assertIn(marker, html)


if __name__ == "__main__":
    unittest.main()
