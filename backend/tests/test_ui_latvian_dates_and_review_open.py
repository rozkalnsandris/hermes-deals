from tests.ui_contract import read_family_ui_contract, ui_response_contract
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FAMILY = ROOT / "app" / "ui" / "index.html"
REVIEW = ROOT / "app" / "ui" / "review.html"


class UiLatvianDateAndReviewOpenTest(unittest.TestCase):
    def test_family_ui_uses_deterministic_latvian_date_display(self) -> None:
        html = read_family_ui_contract()
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
        for marker in (
            'id="asOfPickerButton"',
            'id="asOfPicker"',
            'class="native-date-proxy" type="date"',
            "asOfPicker.showPicker()",
            'asOfPicker.addEventListener("change"',
        ):
            self.assertIn(marker, html)
        self.assertNotIn("${d.as_of}", html)
        self.assertNotIn("${esc(d.valid_from)}", html)

    def test_review_ui_supports_page_alert_manual_completion(self) -> None:
        html = REVIEW.read_text(encoding="utf-8")
        for marker in (
            "lapas pārbaude",
            "Lapas progress",
            "Izveidot Review produktu",
            "Atvērt Review produktu",
            "Atzīmēt lapu pārbaudītu",
            "function pageAlertAggregate(alert)",
            "/page-alert/hints/",
        ):
            self.assertIn(marker, html)
        for marker in (
            'function previewUrl(id,mode="page",hintIndex=null)',
            'Bukleta lapas priekšskatījums',
            'Atvērt pilnā izmērā',
            'Atvērt produkta apkārtni',
            '/page-preview?',
            'wirePreviewErrors()',
        ):
            self.assertIn(marker, html)

    def test_review_ui_defaults_to_all_open_states_and_keeps_drafts_visible(self) -> None:
        html = REVIEW.read_text(encoding="utf-8")
        for marker in (
            'value="open" selected',
            'Atvērtie (gaida + laboti + jāpārbauda)',
            'status==="open"?allItems.filter',
            '"pending","draft","needs_followup"',
            'placeholder="DD.MM.GGGG"',
            "function parseLvDate(v)",
            'dateValue("f_from")',
            'dateValue("f_until")',
        ):
            self.assertIn(marker, html)
        self.assertNotIn('<option value="pending" selected>', html)
        for marker in (
            'data-date-target="${id}"',
            'id="${id}_picker"',
            'class="native-date-proxy" type="date"',
            "picker.showPicker()",
            "textInput.value=fmtDate(picker.value)",
        ):
            self.assertIn(marker, html)

    def test_family_and_review_keep_visible_latvian_date_with_native_picker(self) -> None:
        family = read_family_ui_contract()
        review = REVIEW.read_text(encoding="utf-8")
        self.assertIn('placeholder="DD.MM.GGGG"', family)
        self.assertIn('placeholder="DD.MM.GGGG"', review)
        self.assertIn('type="date"', family)
        self.assertIn('type="date"', review)
        self.assertIn("showPicker()", family)
        self.assertIn("showPicker()", review)

    def test_native_date_picker_anchor_stays_on_calendar_button(self) -> None:
        family = read_family_ui_contract()
        review = REVIEW.read_text(encoding="utf-8")
        for html in (family, review):
            self.assertIn(".date-entry{position:relative;", html)
            self.assertIn(".native-date-proxy{position:absolute;right:0;top:0;", html)
            self.assertNotIn("left:-100px", html)
            self.assertNotIn("top:-100px", html)
        self.assertIn("width:46px;height:46px", family)
        self.assertIn("width:44px;height:42px", review)

    def test_normal_review_approval_confirms_scope_before_publish(self) -> None:
        html = REVIEW.read_text(encoding="utf-8")
        for marker in (
            'if(scope==="excluded"){showToast("Izslēgtu piedāvājumu nevar publicēt.",true);return;}',
            'if(scope==="review")$("f_scope").value="in_scope";',
            'if(await save(false)===false)return;',
            '"/api/v1/review-items/"+selected.id+"/approve"',
        ):
            self.assertIn(marker, html)

    def test_empty_family_search_explains_matching_review_state(self) -> None:
        html = read_family_ui_contract()
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
