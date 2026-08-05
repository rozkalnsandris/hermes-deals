from __future__ import annotations

from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "tools/run-hermes-deals-lidl-semantic-corpus-audit-v01.sh"
INSTALLER = ROOT / "tools/runner/install-lidl-semantic-corpus-audit-dispatcher.sh"
WORKFLOW = ROOT / ".github/workflows/lidl-semantic-corpus-rpi5-audit.yml"


class LidlSemanticCorpusAuditContractTest(unittest.TestCase):
    def test_shell_entrypoints_have_valid_bash_syntax(self) -> None:
        for path in (AUDIT, INSTALLER):
            subprocess.run(
                ["bash", "-n", str(path)],
                check=True,
                capture_output=True,
                text=True,
            )

    def test_audit_is_exact_commit_read_only_and_fail_closed(self) -> None:
        text = AUDIT.read_text(encoding="utf-8")
        for required in (
            'HERMES_AUDIT_TRIGGER:-}" == "github-actions"',
            'HERMES_AUDIT_EXPECTED_BRANCH:-}" == "main"',
            'git -C "$REPO" merge-base --is-ancestor "$EXPECTED_SHA" main',
            'git -C "$REPO" archive --format=tar "$EXPECTED_SHA"',
            'tools/lidl_parser_provenance/v631/manifest.json',
            'tools/lidl_weekly_semantic_view.py',
            'sha256sum "$flyer_dir/source.pdf"',
            'sha256sum "$flyer_dir/source.json"',
            'diff -qr "$output_dir" "$replay_dir"',
            'coverage.get("unexplained_count") != 0',
            '"database_write": False',
            '"production_deploy": False',
            'PRODUCTION_APPLY_AUTHORIZED=false',
        ):
            self.assertIn(required, text)

        for forbidden in (
            "docker ",
            "docker-compose",
            "psql ",
            "alembic ",
            "git checkout",
            "git reset",
            "git switch",
            "systemctl restart",
            "auto_publish\": True",
            "database_write\": True",
        ):
            self.assertNotIn(forbidden, text)

    def test_installer_binds_root_owned_script_to_merged_sha(self) -> None:
        text = INSTALLER.read_text(encoding="utf-8")
        for required in (
            'git -C "$REPO" merge-base --is-ancestor "$EXPECTED_SHA" main',
            'git -C "$REPO" show "$EXPECTED_SHA:$RELATIVE_SCRIPT"',
            "audit_name='lidl-semantic-corpus'",
            "script_sha256='$script_sha'",
            "/usr/local/sbin/hermes-deals-lidl-semantic-corpus-audit-dispatch",
            "github-runner ALL=(root) NOPASSWD:",
            "RUNNER_HAS_DOCKER_GROUP=false",
            "production_apply_authorized\": False",
        ):
            self.assertIn(required, text)
        self.assertNotIn("github-runner ALL=(ALL) NOPASSWD: ALL", text)
        self.assertNotIn("docker ", text)

    def test_workflow_requires_owner_merged_pr_and_fixed_dispatcher(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        for required in (
            "audit:lidl-semantic-corpus",
            'EXPECTED_OWNER_LOGIN: rozkalnsandris',
            'EXPECTED_OWNER_ID: "277435981"',
            'os.environ["GITHUB_EVENT_PATH"]',
            'if not pr.get("merged") or not pr.get("merged_at")',
            'pr["base"]["ref"] != "main"',
            "/usr/local/sbin/hermes-deals-lidl-semantic-corpus-audit-dispatch",
            "actions/upload-artifact@v6",
            "Production deployment: **not authorized**",
        ):
            self.assertIn(required, text)
        self.assertNotIn("actions/checkout@", text)
        self.assertNotIn("docker", text.casefold())
        self.assertNotIn("pull_request_target", text)


if __name__ == "__main__":
    unittest.main()
