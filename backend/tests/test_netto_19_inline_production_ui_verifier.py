from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
VERIFIER = ROOT / 'tools' / 'runner' / 'netto_19_production_readonly_verify.py'
UI_BUNDLER = ROOT / 'backend' / 'app' / 'ui_bundle.py'

SPEC = importlib.util.spec_from_file_location('netto_19_inline_verify', VERIFIER)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


INLINE_SCRIPT = (
    'const bootstrap="w3-behavior-preserving-bootstrap-v1";'
    'if(payload.source_contract!=="explicit_immutable_retailer_evidence_only")throw new Error("bad");'
    'const high=rows.filter((deal)=>deal.special_confidence==="high");'
    'countEl.textContent=String(rows.length);'
)
INLINE_HTML = (
    '<html><head>'
    '<meta name="hermes-production-bundle" content="inline-v1">'
    '</head><body>'
    f'<script data-hermes-production-bundle="app.js">{INLINE_SCRIPT}</script>'
    '</body></html>'
)


class Netto19InlineProductionUiVerifierTest(unittest.TestCase):
    def test_inline_production_bundle_is_verified_from_served_html_without_script_fetch(self) -> None:
        original_http = MODULE.http_text
        original_git = MODULE.owner_git
        calls: list[tuple[str, object]] = []

        def fake_http_text(path: str) -> str:
            calls.append(('http', path))
            self.assertEqual(path, '/ui')
            return INLINE_HTML

        def unexpected_owner_git(*args: str) -> str:
            calls.append(('git', args))
            self.fail('inline production verification must inspect served inline bytes, not Git source')

        MODULE.http_text = fake_http_text
        MODULE.owner_git = unexpected_owner_git
        try:
            self.assertEqual(
                MODULE.validate_daily_ui_contract('d' * 40),
                'inline-production',
            )
        finally:
            MODULE.http_text = original_http
            MODULE.owner_git = original_git

        self.assertEqual(calls, [('http', '/ui')])
        self.assertEqual(
            MODULE.daily_ui_script_path(INLINE_HTML),
            MODULE.INLINE_PRODUCTION_SCRIPT,
        )

    def test_inline_production_mode_matches_exact_immutable_ui_bundler_markers(self) -> None:
        bundler = UI_BUNDLER.read_text(encoding='utf-8')
        self.assertEqual(MODULE.PRODUCTION_BUNDLE_SCRIPT_ATTR, 'data-hermes-production-bundle')
        self.assertEqual(MODULE.PRODUCTION_BUNDLE_SCRIPT_VALUE, 'app.js')
        self.assertEqual(MODULE.PRODUCTION_BUNDLE_META_NAME, 'hermes-production-bundle')
        self.assertEqual(MODULE.PRODUCTION_BUNDLE_META_VALUE, 'inline-v1')
        self.assertIn('SCRIPT_MARKER = \'data-hermes-production-bundle="app.js"\'', bundler)
        self.assertIn('PRODUCTION_META = \'<meta name="hermes-production-bundle" content="inline-v1">\'', bundler)
        self.assertIn("f'<script {SCRIPT_MARKER}>\\n'", bundler)

    def test_inline_production_selection_fails_closed_on_ambiguous_or_malformed_modes(self) -> None:
        cases = {
            'missing meta': INLINE_HTML.replace(
                '<meta name="hermes-production-bundle" content="inline-v1">',
                '',
            ),
            'duplicate inline': INLINE_HTML.replace(
                '</body>',
                f'<script data-hermes-production-bundle="app.js">{INLINE_SCRIPT}</script></body>',
            ),
            'mixed legacy': INLINE_HTML.replace(
                '</body>',
                '<script src="/ui/app.js"></script></body>',
            ),
            'inline marker with src': (
                '<meta name="hermes-production-bundle" content="inline-v1">'
                f'<script data-hermes-production-bundle="app.js" src="/ui/app.js">{INLINE_SCRIPT}</script>'
            ),
            'wrong marker value': (
                '<meta name="hermes-production-bundle" content="inline-v1">'
                f'<script data-hermes-production-bundle="other.js">{INLINE_SCRIPT}</script>'
            ),
            'duplicate meta': INLINE_HTML.replace(
                '</head>',
                '<meta name="hermes-production-bundle" content="inline-v1"></head>',
            ),
        }
        for label, html in cases.items():
            with self.subTest(label=label):
                with self.assertRaises(MODULE.VerifyError):
                    MODULE.daily_ui_script_path(html)

    def test_existing_legacy_and_hashed_modes_remain_supported(self) -> None:
        hashed = '/ui/assets/index.abcdefgh1234.js'
        self.assertEqual(
            MODULE.daily_ui_script_path(f'<script type="module" src="{hashed}"></script>'),
            hashed,
        )
        self.assertEqual(
            MODULE.daily_ui_script_path('<script src="/ui/app.js"></script>'),
            '/ui/app.js',
        )


if __name__ == '__main__':
    unittest.main()
