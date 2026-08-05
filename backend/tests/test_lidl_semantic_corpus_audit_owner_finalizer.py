from __future__ import annotations

from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]
FINALIZER = (
    ROOT
    / "tools/runner/run-lidl-semantic-corpus-audit-owner-finalizer-v01.sh"
)


class LidlSemanticCorpusOwnerFinalizerTest(unittest.TestCase):
    def test_shell_entrypoint_has_valid_bash_syntax(self) -> None:
        subprocess.run(
            ["bash", "-n", str(FINALIZER)],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_requires_exact_merged_sha_and_pr_number(self) -> None:
        result = subprocess.run(
            ["bash", str(FINALIZER)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("usage:", result.stderr)

        result = subprocess.run(
            ["bash", str(FINALIZER), "not-a-sha", "93"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("merged commit SHA is invalid", result.stderr)

        result = subprocess.run(
            ["bash", str(FINALIZER), "0" * 40, "not-a-pr"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("merged PR number is invalid", result.stderr)

    def test_preserves_primary_and_uses_only_isolated_audit_clone(self) -> None:
        text = FINALIZER.read_text(encoding="utf-8")
        for required in (
            'OWNER_FINALIZER_VERSION="lidl-semantic-corpus-owner-finalizer-v01"',
            'EXPECTED_AUDIT_VERSION="lidl-semantic-corpus-audit-v02.3-partition-contract"',
            'EXPECTED_DISPATCHER_VERSION="lidl-semantic-corpus-dispatcher-v03-owned-log"',
            'PRIMARY="/home/andris/hermes-deals"',
            'PRIMARY_EXPECTED_BRANCH="audit/b15m2-v08-preparation"',
            'PRIMARY_EXPECTED_HEAD="a2d9e20039275832286b229984b8261f9394554f"',
            'AUDIT_REPO="/home/andris/hermes-deals-audit-source"',
            'CORPUS_ROOT="/home/andris/hermes-deals-lidl-corpus/flyers"',
            'GIT_OPTIONAL_LOCKS=0 git -C "$1"',
            'git -C "$AUDIT_REPO" fetch --prune origin main',
            'git -C "$AUDIT_REPO" switch -C main "$TARGET_SHA"',
            'install-lidl-semantic-corpus-audit-dispatcher-v03.sh',
            'sudo bash "$INSTALLER" "$TARGET_SHA"',
            'PRIMARY_WORKTREE_VERIFIED_UNCHANGED=true',
            'PRIMARY_V08_VERIFIED_UNCHANGED=true',
            'PRIMARY_WORKTREE_VERIFIED_UNCHANGED_AFTER_WORKFLOW=true',
            'PRIMARY_V08_VERIFIED_UNCHANGED_AFTER_WORKFLOW=true',
            'OWNER_FINALIZER_RESULT=PASS',
        ):
            self.assertIn(required, text)

        for forbidden in (
            'git -C "$PRIMARY" checkout',
            'git -C "$PRIMARY" reset',
            'git -C "$PRIMARY" switch',
            'git -C "$PRIMARY" stash',
            'git -C "$PRIMARY" clean',
            'git -C "/home/andris/hermes-deals" checkout',
            'git -C "/home/andris/hermes-deals" reset',
            'git -C "/home/andris/hermes-deals" switch',
            'git -C "/home/andris/hermes-deals" stash',
            'git -C "/home/andris/hermes-deals" clean',
            "docker run",
            "docker compose",
            "docker-compose",
            "psql ",
            "alembic ",
            "systemctl restart",
            "rm -rf",
            "git add ",
            "git commit",
            "git push",
        ):
            self.assertNotIn(forbidden, text)

    def test_dispatches_exact_owner_authorized_workflow_and_rechecks_boundaries(
        self,
    ) -> None:
        text = FINALIZER.read_text(encoding="utf-8")
        for required in (
            'WORKFLOW="lidl-semantic-corpus-rpi5-audit.yml"',
            "--ref main",
            '-f "pr_number=$PR_NUMBER"',
            'gh run watch "$run_id"',
            "--exit-status",
            'grep -Fxq "AUDIT_VERSION=$EXPECTED_AUDIT_VERSION"',
            'grep -Fxq "DISPATCHER_VERSION=$EXPECTED_DISPATCHER_VERSION"',
            'grep -Fxq "REGISTERED_COMMIT=$TARGET_SHA"',
            'grep -Fxq "PRIMARY_WORKTREE_MODIFIED=false"',
            'grep -Fxq "AUDIT_GIT_INDEX_UNCHANGED=true"',
            'grep -Fxq "RUNNER_HAS_DOCKER_GROUP=false"',
            'grep -Fxq "PRODUCTION_APPLY_AUTHORIZED=false"',
        ):
            self.assertIn(required, text)

        watch = text.index('gh run watch "$run_id"')
        checks = [
            pos
            for pos in (
                text.find("verify_primary_unchanged", watch),
                text.find(
                    'git_read "$AUDIT_REPO" rev-parse HEAD',
                    watch,
                ),
                text.find(
                    'git_read "$AUDIT_REPO" status --porcelain=v1',
                    watch,
                ),
            )
            if pos != -1
        ]
        self.assertEqual(len(checks), 3)
        self.assertTrue(all(position > watch for position in checks))


if __name__ == "__main__":
    unittest.main()
