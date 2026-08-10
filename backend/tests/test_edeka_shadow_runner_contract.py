from __future__ import annotations

from pathlib import Path
import subprocess
import unittest
import yaml


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "tools/run-hermes-deals-edeka-shadow-cycle-v01.sh"
DISPATCHER = ROOT / "tools/runner/edeka-shadow-cycle-dispatcher.sh"
INSTALLER = ROOT / "tools/runner/install-edeka-shadow-cycle-dispatcher.sh"
WORKFLOW = ROOT / ".github/workflows/edeka-shadow-cycle-rpi5.yml"
RUNBOOK = ROOT / "docs/edeka-shadow-cycle-runbook.md"
UPLOAD_ARTIFACT_SHA = "b7c566a772e6b6bfb58ed0dc250532a479d7789f"


class EdekaShadowRunnerContractTest(unittest.TestCase):
    def test_shell_entrypoints_have_valid_bash_syntax(self) -> None:
        for path in (RUNNER, DISPATCHER, INSTALLER):
            subprocess.run(["bash", "-n", str(path)], check=True, capture_output=True, text=True)

    def test_runner_is_exact_clone_and_git_index_safe(self) -> None:
        text = RUNNER.read_text(encoding="utf-8")
        for required in (
            'RUNNER_VERSION="edeka-shadow-cycle-v01"',
            'RUNTIME_BOUNDARY_VERSION="edeka-shadow-cycle-index-safe-v01"',
            'AUDIT_REPO="/home/andris/hermes-deals-audit-source-edeka"',
            'PRIMARY_REPO="/home/andris/hermes-deals"',
            'GIT_OPTIONAL_LOCKS=0 git -C "$AUDIT_REPO"',
            'GIT_OPTIONAL_LOCKS=0 git -C "$PRIMARY_REPO"',
            'AUDIT_INDEX="$AUDIT_REPO/.git/index"',
            'PRIMARY_INDEX="$PRIMARY_REPO/.git/index"',
            'AUDIT_GIT_INDEX_UNCHANGED=true',
            'PRIMARY_GIT_INDEX_UNCHANGED=true',
            'python" -m app.edeka_shadow_capture',
            '--min-offers 150',
            "tar --sort=name --mtime='UTC 1970-01-01'",
            "PRODUCTION_DATABASE_WRITE=false",
            "PRODUCTION_DEPLOYMENT=false",
            "SCHEDULER_ACTIVATION=false",
        ):
            self.assertIn(required, text)
        for forbidden in (
            'AUDIT_REPO="/home/andris/hermes-deals-audit-source"',
            'git -C "$PRIMARY_REPO" switch',
            'git -C "$PRIMARY_REPO" reset',
            'git -C "$PRIMARY_REPO" clean',
            "docker run",
            "docker compose",
            "systemctl ",
            "edeka-scheduler-armed",
        ):
            self.assertNotIn(forbidden, text)

    def test_installer_registers_only_fixed_root_owned_dispatcher(self) -> None:
        text = INSTALLER.read_text(encoding="utf-8")
        for required in (
            "AUDIT_REPO='/home/andris/hermes-deals-audit-source-edeka'",
            "DISPATCHER_SCRIPT='tools/runner/edeka-shadow-cycle-dispatcher.sh'",
            "GIT_OPTIONAL_LOCKS=0 git -C \"$AUDIT_REPO\"",
            "index_sha_before=",
            "index_stat_before=",
            "github-runner ALL=(root) NOPASSWD: /usr/local/sbin/hermes-deals-edeka-shadow-cycle-dispatch",
            "RUNNER_HAS_DOCKER_GROUP=false",
            "AUDIT_GIT_INDEX_UNCHANGED=true",
        ):
            self.assertIn(required, text)
        for forbidden in (
            "AUDIT_REPO='/home/andris/hermes-deals-audit-source'",
            "/home/andris/hermes-deals'",
            "github-runner ALL=(ALL) NOPASSWD: ALL",
            'chown andris:andris "$GIT_INDEX"',
            "docker run",
            "docker compose",
        ):
            self.assertNotIn(forbidden, text)

    def test_dispatcher_sanitizes_and_validates_real_evidence(self) -> None:
        text = DISPATCHER.read_text(encoding="utf-8")
        for required in (
            "EXPORT_DIR" ,
            "/home/github-runner/_work/_temp/hermes-deals-edeka-shadow-cycle-*",
            "runuser -u andris",
            "tarfile.open(archive, \"r:gz\")",
            "unsafe archive member",
            "sensitive archive content",
            '"public_market_id": "071897"',
            '"internal_market_id": "587881"',
            '"store_name": "EDEKA Patzer"',
            "same_snapshot_replay_offer_delta",
            "dispatcher-evidence-manifest.json",
            "PRODUCTION_DATABASE_WRITE=false",
        ):
            self.assertIn(required, text)
        self.assertNotIn("docker ", text)
        self.assertNotIn("psql ", text)

    def test_workflow_is_manual_owner_authorized_and_self_hosted(self) -> None:
        raw = WORKFLOW.read_text(encoding="utf-8")
        parsed = yaml.safe_load(raw)
        self.assertIsInstance(parsed, dict)
        for required in (
            "workflow_dispatch:",
            "ACTOR_ID: ${{ github.actor_id }}",
            'os.environ["ACTOR"] != "rozkalnsandris"',
            'os.environ["ACTOR_ID"] != "277435981"',
            "audit accepts only merged pull requests",
            "hermes-deals-audit",
            "sudo --non-interactive /usr/local/sbin/hermes-deals-edeka-shadow-cycle-dispatch",
            f"actions/upload-artifact@{UPLOAD_ARTIFACT_SHA} # v6.0.0",
            "retention-days: 30",
            "Production database write: **false**",
        ):
            self.assertIn(required, raw)
        self.assertNotIn("actions/upload-artifact@v6", raw)
        self.assertNotIn("schedule:", raw)
        self.assertNotIn("pull_request:", raw)

    def test_runbook_keeps_install_run_and_production_apply_separate(self) -> None:
        text = RUNBOOK.read_text(encoding="utf-8")
        for required in (
            "two real consecutive weekly campaigns",
            "/home/andris/hermes-deals-audit-source-edeka",
            "GIT_OPTIONAL_LOCKS=0",
            "install-edeka-shadow-cycle-dispatcher.sh",
            "workflow_dispatch",
            "Production canary preparation and apply remain separate",
            "production database writes",
        ):
            self.assertIn(required, text)
        self.assertNotIn("/home/andris/hermes-deals-audit-source\n", text)


if __name__ == "__main__":
    unittest.main()
