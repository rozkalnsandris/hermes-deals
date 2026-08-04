from tests.ui_contract import read_family_ui_contract, ui_response_contract
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FAMILY = ROOT / "app" / "ui" / "index.html"


class UiDailyUseV3Test(unittest.TestCase):
    def test_raw_retailer_deals_can_join_family_list(self) -> None:
        html = read_family_ui_contract()
        for marker in (
            'function dealListId(d)',
            'function addDealToList(d)',
            'class="btn primary deal-list-add',
            'card.querySelector(".deal-list-add")',
            'class="btn primary deal-detail-add"',
        ):
            self.assertIn(marker, html)

    def test_legacy_list_entries_are_migrated_without_data_loss(self) -> None:
        html = read_family_ui_contract()
        for marker in (
            'function normalizeListItem(key,item)',
            'kind=item.kind==="deal"?"deal":"canonical"',
            'completed:Boolean(item.completed)',
            'for(const [key,item] of Object.entries(raw))',
        ):
            self.assertIn(marker, html)

    def test_family_list_supports_done_copy_and_cleanup_actions(self) -> None:
        html = read_family_ui_contract()
        for marker in (
            'id="copyList"',
            'id="clearDone"',
            'function toggleDone(id)',
            'function listCopyText()',
            'async function copyShoppingList()',
            'function clearCompleted()',
            'function clearAllList()',
        ):
            self.assertIn(marker, html)

    def test_basket_compare_uses_only_active_canonical_entries(self) -> None:
        html = read_family_ui_contract()
        for marker in (
            'function activeCanonicalEntries()',
            'const entries=activeCanonicalEntries()',
            'i=>!i.completed&&i.kind==="canonical"',
            'konkrēti veikala piedāvājumi nav iekļauti canonical salīdzinājumā',
        ):
            self.assertIn(marker, html)

    def test_list_badge_and_summary_count_remaining_items(self) -> None:
        html = read_family_ui_contract()
        for marker in (
            'id="listSummary"',
            '$("listCount").textContent=remaining',
            '${remaining} atlikušas',
            '${done} nopirktas',
            'class="list-row ${i.completed?"completed":""}"',
        ):
            self.assertIn(marker, html)

    def test_clear_all_uses_hermes_confirmation_dialog(self) -> None:
        html = read_family_ui_contract()
        for marker in (
            'id="clearListConfirm"',
            'role="alertdialog"',
            'function openClearListConfirm()',
            'function closeClearListConfirm()',
            'function confirmClearAll()',
            'clearListConfirm.setAttribute("aria-hidden","false")',
            'clearListReturnFocus=document.activeElement',
        ):
            self.assertIn(marker, html)
        self.assertNotIn('window.confirm(', html)

    def test_mobile_drawer_actions_are_safe_and_readable(self) -> None:
        html = read_family_ui_contract()
        for marker in (
            'padding:14px 18px max(18px,calc(env(safe-area-inset-bottom) + 12px))',
            '@media(max-width:420px){.drawer-footer{grid-template-columns:1fr}',
            '.drawer-footer .btn{min-height:44px;white-space:normal}',
            '.confirm-actions{grid-template-columns:1fr}',
        ):
            self.assertIn(marker, html)

    def test_danger_action_uses_theme_aware_contrast(self) -> None:
        html = read_family_ui_contract()
        self.assertIn(
            '.btn.danger{background:var(--danger);color:var(--surface);border-color:var(--danger)}',
            html,
        )
        self.assertNotIn(
            '.btn.danger{background:var(--danger);color:#fff;border-color:var(--danger)}',
            html,
        )


if __name__ == "__main__":
    unittest.main()
