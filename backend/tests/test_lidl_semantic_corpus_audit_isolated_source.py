from __future__ import annotations

from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "tools/run-hermes-deals-lidl-semantic-corpus-audit-v02.sh"
INSTALLER = (
    ROOT
    / "tools/runner/install-lidl-semantic-corpus-audit-dispatcher-v02.sh"
)


class LidlSemanticCorpusAuditIsolatedSourceTest(unittest.TestCase):
    def test_shell_entrypoints_have_valid_bash_syntax(self) -> None:
        for path in (AUDIT, INSTALLER):
            subprocess.run(
                ["bash", "-n", str(path)],
                check=True,
                capture_output=True,
                text=True,
            )

    def test_audit_uses_exact_clean_isolated_clone(self) -> None:
        text = AUDIT.read_text(encoding="utf-8")
        for required in (
            'AUDIT_VERSION="lidl-semantic-corpus-audit-v02.1-isolated-source"',
            'AUDIT_REPO="/home/andris/hermes-deals-audit-source"',
            'GIT_OPTIONAL_LOCKS=0 git -C "$AUDIT_REPO" "$@"',
            'GIT_INDEX="$AUDIT_REPO/.git/index"',
            'isolated audit repository index ownership is invalid',
            'branch="$(git_read branch --show-current)"',
            'status="$(git_read status --porcelain)"',
            'head_sha="$(git_read rev-parse HEAD)"',
            'git_read show "$EXPECTED_SHA:$V01_PATH"',
            "expected exactly one frozen V01 marker",
            'REPO="/home/andris/hermes-deals"',
            'hermes-deals-runner-evidence/hermes-deals-audit-*',
            'hermes-deals-lidl-semantic-audit-*',
            '/bin/bash --noprofile --norc "$patched_script"',
        ):
            self.assertIn(required, text)

        for forbidden in (
            "git checkout",
            "git reset",
            "git switch",
            "git stash",
            "docker ",
            "docker-compose",
            "psql ",
            "alembic ",
            "systemctl restart",
        ):
            self.assertNotIn(forbidden, text)

    def test_installer_uses_private_mount_namespace_without_index_drift(self) -> None:
        text = INSTALLER.read_text(encoding="utf-8")
        for required in (
            'AUDIT_REPO="/home/andris/hermes-deals-audit-source"',
            'PRIMARY_REPO="/home/andris/hermes-deals"',
            'GIT_INDEX="$AUDIT_REPO/.git/index"',
            'index_sha_before="$(sha256sum "$GIT_INDEX"',
            'index_stat_before="$(stat -c',
            'GIT_OPTIONAL_LOCKS=0 git -C "$AUDIT_REPO" "$@"',
            "unshare --mount --propagation private",
            'mount --bind "$source_repo" "$primary_repo"',
            'GIT_OPTIONAL_LOCKS=0 /bin/bash',
            "install-lidl-semantic-corpus-audit-dispatcher.sh",
            'isolated audit repository index content changed during installation',
            'isolated audit repository index metadata changed during installation',
            'git_read show "$EXPECTED_SHA:$V02_SCRIPT"',
            "script_sha256='$script_sha'",
            "PRIMARY_WORKTREE_MODIFIED=false",
            "AUDIT_GIT_INDEX_UNCHANGED=true",
            "RUNNER_HAS_DOCKER_GROUP=false",
            "PRODUCTION_APPLY_AUTHORIZED=false",
        ):
            self.assertIn(required, text)

        for forbidden in (
            'git -C "$PRIMARY_REPO" checkout',
            'git -C "$PRIMARY_REPO" reset',
            'git -C "$PRIMARY_REPO" switch',
            'git -C "$PRIMARY_REPO" stash',
            "github-runner ALL=(ALL) NOPASSWD: ALL",
            'chown andris:andris "$GIT_INDEX"',
        ):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
