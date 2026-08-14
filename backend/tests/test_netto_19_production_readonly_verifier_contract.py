from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
VERIFIER = ROOT / 'tools' / 'runner' / 'netto_19_production_readonly_verify.py'
INSTALLER = ROOT / 'tools' / 'runner' / 'install-netto-19-production-readonly-verifier.sh'
WORKFLOW = ROOT / '.github' / 'workflows' / 'netto-19-production-readonly-verify.yml'

SPEC = importlib.util.spec_from_file_location('netto_19_verify', VERIFIER)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class Netto19ProductionReadonlyVerifierContractTest(unittest.TestCase):
    def test_workflow_is_owner_issue_comment_only_and_self_hosted_job_is_tokenless(self) -> None:
        text = WORKFLOW.read_text(encoding='utf-8')
        self.assertIn('issue_comment:', text)
        self.assertIn('github.event.issue.number == 19', text)
        self.assertIn("github.actor == 'rozkalnsandris'", text)
        self.assertIn('github.event.sender.id == 277435981', text)
        self.assertIn("github.event.comment.author_association == 'OWNER'", text)
        self.assertIn(r'/hermes-netto-19 verify sha=([0-9a-f]{40})', text)
        self.assertIn('runs-on: [self-hosted, Linux, ARM64, hermes-deals-audit]', text)
        self.assertIn('permissions: {}', text)
        self.assertNotIn('actions/checkout', text)
        self.assertNotIn('pull_request_target:', text)

    def test_verifier_contains_no_mutating_runtime_operations_and_forces_read_only_db_sessions(self) -> None:
        text = VERIFIER.read_text(encoding='utf-8').lower()
        forbidden = (
            ' compose up ', 'docker build', 'docker restart', 'docker stop',
            'docker rm', 'systemctl', 'alembic upgrade', 'insert into',
            'update source_snapshots', 'update offer_candidates', 'delete from',
            'approve_review',
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, text)
        self.assertIn('default_transaction_read_only=on', text)
        self.assertIn("'deployment_performed': false", text)
        self.assertIn("'database_write_performed': false", text)
        self.assertIn("'review_write_performed': false", text)

    def test_required_fix_commits_are_exact(self) -> None:
        self.assertEqual(
            MODULE.REQUIRED_FIX_COMMITS,
            (
                '0eb83f47658560ff733199399475771dc966008f',
                '52a3127c940dc36177846812932a08f49d913692',
            ),
        )

    def test_select_snapshot_prefers_newest_matching_collection(self) -> None:
        from datetime import date, datetime, timezone
        old = MODULE.Snapshot(
            id='00000000-0000-0000-0000-000000000001', sha256='a' * 64,
            collected_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
            valid_from=date(2026, 8, 3), valid_until=date(2026, 8, 8),
        )
        newer = MODULE.Snapshot(
            id='00000000-0000-0000-0000-000000000002', sha256='b' * 64,
            collected_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
            valid_from=date(2026, 8, 3), valid_until=date(2026, 8, 8),
        )
        self.assertIs(MODULE.select_snapshot([old, newer], date(2026, 8, 5)), newer)
        self.assertIsNone(MODULE.select_snapshot([old, newer], date(2026, 8, 10)))

    def test_daily_payload_enforces_snapshot_binding_and_safe_out_of_window(self) -> None:
        from datetime import date, datetime, timezone
        snap = MODULE.Snapshot(
            id='00000000-0000-0000-0000-000000000003', sha256='c' * 64,
            collected_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
            valid_from=date(2026, 8, 3), valid_until=date(2026, 8, 8),
        )
        payload = {
            'as_of': '2026-08-06', 'timezone': 'Europe/Berlin',
            'source_contract': MODULE.DAILY_CONTRACT,
            'retailer_counts': {'netto': 1},
            'deals': [{
                'offer_candidate_id': '00000000-0000-0000-0000-000000000099',
                'source_chain': 'netto', 'source_store_external_id': '5659',
                'source_snapshot_id': snap.id, 'source_snapshot_sha256': snap.sha256,
                'special_valid_on': '2026-08-06', 'is_daily_special': True,
                'special_confidence': 'high', 'shadow_only': True,
            }],
        }
        rows = MODULE.validate_daily_payload(payload, day=date(2026, 8, 6), selected=snap)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(MODULE.daily_ui_high_confidence_ids(date(2026, 8, 6), rows)), 1)
        empty = {
            'as_of': '2026-08-20', 'timezone': 'Europe/Berlin',
            'source_contract': MODULE.DAILY_CONTRACT, 'retailer_counts': {}, 'deals': [],
        }
        self.assertEqual(MODULE.validate_daily_payload(empty, day=date(2026, 8, 20), selected=None), [])

    def test_container_raw_snapshot_path_is_mapped_to_bounded_host_raw_root(self) -> None:
        original = MODULE.HOST_RAW_ROOT
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'data' / 'raw'
            root.mkdir(parents=True)
            manifest = root / 'netto' / 'manifest.json'
            manifest.parent.mkdir()
            manifest.write_text('{}', encoding='utf-8')
            MODULE.HOST_RAW_ROOT = root
            try:
                self.assertEqual(
                    MODULE.host_snapshot_path('/data/raw/netto/manifest.json'),
                    manifest.resolve(),
                )
                with self.assertRaises(MODULE.VerifyError):
                    MODULE.host_snapshot_path('/etc/passwd')
                with self.assertRaises(MODULE.VerifyError):
                    MODULE.host_snapshot_path('/data/raw/../escape.json')
            finally:
                MODULE.HOST_RAW_ROOT = original

    def test_review_queue_and_revision_tables_are_both_covered_by_digest(self) -> None:
        text = VERIFIER.read_text(encoding='utf-8')
        self.assertIn("table_digest(db, 'offer_review_items')", text)
        self.assertIn("table_digest(db, 'offer_review_revisions')", text)
        self.assertNotIn("table_digest(db, 'review_items')", text)

    def test_daily_ui_contract_reads_active_hashed_w4_bundle(self) -> None:
        original = MODULE.http_text
        calls: list[str] = []
        html = '<html><script type="module" src="/ui/assets/index.abcdEFGH1234.js"></script></html>'
        script = (
            'payload.source_contract!=="explicit_immutable_retailer_evidence_only";'
            'deal.special_confidence==="high";'
            'countEl.textContent=String(rows.length);'
        )
        responses = {
            '/ui': html,
            '/ui/assets/index.abcdEFGH1234.js': script,
        }

        def fake_http_text(path: str) -> str:
            calls.append(path)
            return responses[path]

        MODULE.http_text = fake_http_text
        try:
            MODULE.validate_daily_ui_contract()
        finally:
            MODULE.http_text = original

        self.assertEqual(calls, ['/ui', '/ui/assets/index.abcdEFGH1234.js'])

    def test_daily_ui_script_resolution_is_fail_closed_and_keeps_legacy_rollback_compatible(self) -> None:
        legacy = '<script src="/ui/app.js"></script>'
        self.assertEqual(MODULE.daily_ui_script_path(legacy), '/ui/app.js')

        mixed = (
            '<script src="/ui/app.js"></script>'
            '<script type="module" src="/ui/assets/index.abcdefgh1234.js"></script>'
        )
        with self.assertRaises(MODULE.VerifyError):
            MODULE.daily_ui_script_path(mixed)

        ambiguous = (
            '<script type="module" src="/ui/assets/index.abcdefgh1234.js"></script>'
            '<script type="module" src="/ui/assets/vendor.ijklmnop5678.js"></script>'
        )
        with self.assertRaises(MODULE.VerifyError):
            MODULE.daily_ui_script_path(ambiguous)

    def test_daily_and_weekly_ui_count_contracts_are_explicit(self) -> None:
        text = VERIFIER.read_text(encoding='utf-8')
        self.assertIn("html = http_text('/ui')", text)
        self.assertIn('HASHED_UI_JS_SRC_RE', text)
        self.assertIn('countEl.textContent=String(rows.length)', text)
        self.assertIn('deal.special_confidence===\"high\"', text)
        self.assertIn('payload.source_contract!==\"explicit_immutable_retailer_evidence_only\"', text)
        self.assertIn('/api/v1/deals/weekly-specials/ui?week_start=', text)
        self.assertIn("ui.get('ui_contract') == WEEKLY_UI_CONTRACT", text)
        self.assertIn("'daily_ui_count_contract': 'PASS'", text)
        self.assertIn("'weekly_ui_count_contract': 'PASS'", text)

    def test_installer_requires_exact_self_binding_detached_main_source_and_narrow_sudo(self) -> None:
        text = INSTALLER.read_text(encoding='utf-8')
        self.assertIn('netto-19-production-readonly-v1', text)
        self.assertIn("INSTALLER_SOURCE=\"$(readlink -f -- \"${BASH_SOURCE[0]}\")\"", text)
        self.assertIn('installer must execute from the reviewed detached source worktree', text)
        self.assertIn('running installer bytes differ from registered commit', text)
        self.assertIn('source worktree must be detached', text)
        self.assertIn('merge-base --is-ancestor', text)
        self.assertIn('must not belong to the Docker group', text)
        self.assertIn("printf '%s ALL=(root) %s%s: HERMES_DEALS_NETTO_19_READONLY_VERIFY\\n'", text)
        self.assertIn("'NO' 'PASSWD'", text)
        self.assertNotIn('NO' + 'PASS' + 'WD: HERMES_DEALS_NETTO_19_READONLY_VERIFY', text)
        self.assertNotIn('systemctl', text)
        self.assertNotIn('docker compose up', text)
        self.assertNotIn('docker build', text)


if __name__ == '__main__':
    unittest.main()
