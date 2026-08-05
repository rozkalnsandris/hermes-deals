from __future__ import annotations

from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "tools/run-hermes-deals-edeka-shadow-cycle-v01.sh"
RUNBOOK = ROOT / "docs/edeka-shadow-cycle-runbook.md"


class EdekaShadowRunnerContractTest(unittest.TestCase):
    def test_runner_has_valid_bash_syntax(self) -> None:
        subprocess.run(
            ["bash", "-n", str(RUNNER)],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_runner_is_bound_to_isolated_clone_and_exact_commit(self) -> None:
        text = RUNNER.read_text(encoding="utf-8")
        for required in (
            'RUNNER_VERSION="edeka-shadow-cycle-v01"',
            'AUDIT_REPO="/home/andris/hermes-deals-audit-source"',
            'PRIMARY_REPO="/home/andris/hermes-deals"',
            'EVIDENCE_ROOT="/home/andris/hermes-deals-shadow-evidence/edeka"',
            '[[ "$(git -C "$AUDIT_REPO" branch --show-current)" == "main" ]]',
            '[[ -z "$(git -C "$AUDIT_REPO" status --porcelain)" ]]',
            '[[ "$(git -C "$AUDIT_REPO" rev-parse HEAD)" == "$EXPECTED_SHA" ]]',
            'git -C "$AUDIT_REPO" cat-file -e "$EXPECTED_SHA^{commit}"',
            'git -C "$AUDIT_REPO" merge-base --is-ancestor "$EXPECTED_SHA" main',
            'backend/app/edeka_shadow_capture.py',
            'backend/app/edeka_shadow_ledger.py',
        ):
            self.assertIn(required, text)

    def test_runner_uses_isolated_capture_and_sha_bound_evidence(self) -> None:
        text = RUNNER.read_text(encoding="utf-8")
        for required in (
            'requirements_sha="$(sha256sum "$AUDIT_REPO/backend/requirements.txt"',
            'venv="$CACHE_ROOT/venv-$requirements_sha"',
            'python" -m app.edeka_shadow_capture',
            '--sources-config "$AUDIT_REPO/config/sources.json"',
            "--min-offers 150",
            "sha256sum --check --strict SHA256SUMS",
            "tar --sort=name --mtime='UTC 1970-01-01'",
            "gzip -n",
            "PRIMARY_WORKTREE_MODIFIED=false",
            "PRODUCTION_DATABASE_WRITE=false",
            "PRODUCTION_DEPLOYMENT=false",
            "SCHEDULER_ACTIVATION=false",
        ):
            self.assertIn(required, text)

    def test_runner_proves_primary_worktree_is_unchanged(self) -> None:
        text = RUNNER.read_text(encoding="utf-8")
        for required in (
            'primary_branch_before="$(git -C "$PRIMARY_REPO" branch --show-current)"',
            'primary_head_before="$(git -C "$PRIMARY_REPO" rev-parse HEAD)"',
            'primary_status_before="$(git -C "$PRIMARY_REPO" status --porcelain=v1 -z',
            'primary_branch_after="$(git -C "$PRIMARY_REPO" branch --show-current)"',
            'primary_head_after="$(git -C "$PRIMARY_REPO" rev-parse HEAD)"',
            'primary_status_after="$(git -C "$PRIMARY_REPO" status --porcelain=v1 -z',
            '[[ "$primary_branch_after" == "$primary_branch_before" ]]',
            '[[ "$primary_head_after" == "$primary_head_before" ]]',
            '[[ "$primary_status_after" == "$primary_status_before" ]]',
        ):
            self.assertIn(required, text)

        for forbidden in (
            'git -C "$PRIMARY_REPO" checkout',
            'git -C "$PRIMARY_REPO" reset',
            'git -C "$PRIMARY_REPO" switch',
            'git -C "$PRIMARY_REPO" stash',
            'git -C "$PRIMARY_REPO" clean',
            "docker ",
            "docker-compose",
            "psql ",
            "alembic ",
            "systemctl ",
            "edeka-scheduler-armed",
        ):
            self.assertNotIn(forbidden, text)

    def test_runbook_keeps_real_cycles_and_apply_separate(self) -> None:
        text = RUNBOOK.read_text(encoding="utf-8")
        for required in (
            "two real consecutive weekly campaigns",
            "Do not represent two captures of the same campaign as two cycles",
            "production database writes",
            "systemd timer installation or activation",
            "Production canary preparation and apply remain separate",
        ):
            self.assertIn(required, text)


if __name__ == "__main__":
    unittest.main()
