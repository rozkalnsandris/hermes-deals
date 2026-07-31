from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FAMILY = ROOT / "app" / "ui" / "index.html"


class UiDailyUseV4Test(unittest.TestCase):
    def test_compact_home_mode_is_persistent_and_accessible(self) -> None:
        html = FAMILY.read_text(encoding="utf-8")
        for marker in (
            'id="toggleCompact"',
            'UI_PREFS_KEY="hermesDeals.uiPreferences.v4"',
            'function toggleCompactMode()',
            'document.body.classList.toggle("compact-home",uiPrefs.compactHome)',
            'toggleCompact.setAttribute("aria-pressed",String(uiPrefs.compactHome))',
            'body.compact-home .hero .eyebrow',
        ):
            self.assertIn(marker, html)

    def test_card_density_mode_is_persistent_and_responsive(self) -> None:
        html = FAMILY.read_text(encoding="utf-8")
        for marker in (
            'id="toggleDensity"',
            'function toggleCardDensity()',
            'cardDensity:raw.cardDensity==="compact"?"compact":"comfortable"',
            'document.body.classList.toggle("compact-cards"',
            'body.compact-cards .grid{grid-template-columns:repeat(4',
            '.grid,body.compact-cards .grid{grid-template-columns:1fr}',
        ):
            self.assertIn(marker, html)

    def test_daily_action_header_stays_available_on_desktop(self) -> None:
        html = FAMILY.read_text(encoding="utf-8")
        for marker in (
            '@media(min-width:621px){.topbar{position:sticky',
            'top:8px;z-index:35',
            'backdrop-filter:blur(16px)',
            'box-shadow:var(--shadow)',
        ):
            self.assertIn(marker, html)

    def test_active_filters_are_summarized_and_resettable(self) -> None:
        html = FAMILY.read_text(encoding="utf-8")
        for marker in (
            'id="filterSummary"',
            'function activeFilterLabels()',
            'function renderFilterSummary()',
            'function resetFilters()',
            'id="resetFilters"',
            'Notīrīt filtrus',
            'Nav papildu filtru.',
        ):
            self.assertIn(marker, html)

    def test_family_list_supports_notes_and_known_total(self) -> None:
        html = FAMILY.read_text(encoding="utf-8")
        for marker in (
            'note=String(item.note||"").slice(0,160)',
            'function setNote(id,value)',
            'class="list-note"',
            'placeholder="Piezīme ģimenei…"',
            'Zināmā summa ${euro.format(knownTotal)}',
            '${unknownPrice} bez cenas',
            '— Piezīme: ${i.note}',
        ):
            self.assertIn(marker, html)

    def test_desktop_scale_matches_eighty_percent_reference(self) -> None:
        html = FAMILY.read_text(encoding="utf-8")
        self.assertIn(
            "@media(min-width:1000px){body{zoom:.8}}",
            html,
        )
        self.assertNotIn(
            "@media(max-width:999px){body{zoom:.8}}",
            html,
        )

if __name__ == "__main__":
    unittest.main()
