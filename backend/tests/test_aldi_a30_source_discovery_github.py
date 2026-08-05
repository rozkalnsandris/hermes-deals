from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "tools/aldi_a30_source_discovery.py"
RUNNER = ROOT / "tools/run-hermes-deals-aldi-a30-source-discovery-v04.sh"
DISPATCHER = ROOT / "tools/runner/aldi-a30-source-discovery-dispatcher.sh"
INSTALLER = ROOT / "tools/runner/install-aldi-a30-source-discovery-dispatcher.sh"
WORKFLOW = ROOT / ".github/workflows/aldi-a30-source-discovery-rpi5.yml"
RUNBOOK = ROOT / "docs/aldi-a30-source-discovery-runbook.md"


def load_module():
    spec = importlib.util.spec_from_file_location("aldi_a30_source_discovery", MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AldiA30SourceDiscoveryUrlTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def test_malformed_bracketed_url_is_rejected_without_exception(self) -> None:
        self.assertIsNone(
            self.module.safe_absolute_url(
                "https://www.aldi-nord.de/prospekte.html",
                "https://[invalid-ipv6/source",
            )
        )
        values: set[str] = set()
        rejected: list[dict[str, str]] = []
        self.module.add_urls(
            values,
            __import__("collections").defaultdict(set),
            ["https://[invalid-ipv6/source"],
            "regression",
            "https://www.aldi-nord.de/prospekte.html",
            rejected,
        )
        self.assertEqual(values, set())
        self.assertEqual(rejected[0]["reason"], "invalid_url")

    def test_source_path_accepts_only_official_magazine_and_ipaper_hosts(self) -> None:
        expected = "/aldi-nord/aldi-nord-angebote-03-08-2026-08-08-2026-kw32/"
        self.assertEqual(
            self.module.source_path(
                "https://magazine.aldi-nord.de/aldi-nord/aldi-nord-angebote-03-08-2026-08-08-2026-kw32/"
            ),
            expected,
        )
        self.assertEqual(
            self.module.source_path(
                "https://ipaper.ipapercms.dk/aldi-nord/aldi-nord-angebote-03-08-2026-08-08-2026-kw32/Image.ashx?PageNumber=2"
            ),
            expected,
        )
        self.assertIsNone(
            self.module.source_path(
                "https://example.invalid/aldi-nord/aldi-nord-angebote-03-08-2026-08-08-2026-kw32/"
            )
        )

    def test_extract_urls_keeps_valid_candidates_and_reports_invalid_ones(self) -> None:
        urls, rejected = self.module.extract_urls(
            'good="https://magazine.aldi-nord.de/aldi-nord/cycle/" bad="https://[broken"',
            "https://www.aldi-nord.de/prospekte/aldi-aktuell.html",
        )
        self.assertIn("https://magazine.aldi-nord.de/aldi-nord/cycle/", urls)
        self.assertTrue(rejected)


class AldiA30SourceDiscoveryGithubContractTest(unittest.TestCase):
    def test_shell_entrypoints_have_valid_syntax(self) -> None:
        for path in (RUNNER, DISPATCHER, INSTALLER):
            subprocess.run(["bash", "-n", str(path)], check=True, capture_output=True, text=True)

    def test_module_compiles_without_playwright_installed(self) -> None:
        subprocess.run(["python3", "-m", "py_compile", str(MODULE)], check=True, capture_output=True, text=True)
        text = MODULE.read_text(encoding="utf-8")
        self.assertNotIn("from playwright", text.split("def run_discovery", 1)[0])
        self.assertIn("from playwright.sync_api import sync_playwright", text)

    def test_runner_is_exact_sha_bound_and_read_only(self) -> None:
        text = RUNNER.read_text(encoding="utf-8")
        for required in (
            'RUNNER_VERSION="aldi-a30-source-discovery-v04-github"',
            'AUDIT_REPO="${AUDIT_REPO:-/home/andris/hermes-deals-audit-source}"',
            'PRIMARY_REPO="${PRIMARY_REPO:-/home/andris/hermes-deals}"',
            '[[ "$audit_head" == "$EXPECTED_SHA" ]]',
            'GIT_OPTIONAL_LOCKS=0 git -C',
            'PRIMARY_WORKTREE_MODIFIED=false',
            'PRIMARY_GIT_INDEX_UNCHANGED=true',
            'AUDIT_GIT_INDEX_UNCHANGED=true',
            'PAGE_ACQUISITION=false',
            'ROLLOVER_COMPARISON=false',
            'PRODUCTION_DATABASE_WRITE=false',
            'PRODUCTION_DEPLOYMENT=false',
        ):
            self.assertIn(required, text)
        for forbidden in (
            'git -C "$PRIMARY_REPO" checkout',
            'git -C "$PRIMARY_REPO" reset',
            'git -C "$PRIMARY_REPO" switch',
            'git -C "$PRIMARY_REPO" stash',
            "docker run",
            "docker compose",
            "psql ",
            "alembic ",
            "systemctl ",
        ):
            self.assertNotIn(forbidden, text)

    def test_dispatcher_and_installer_are_fixed_and_least_privilege(self) -> None:
        dispatcher = DISPATCHER.read_text(encoding="utf-8")
        installer = INSTALLER.read_text(encoding="utf-8")
        for required in (
            "/usr/local/libexec/hermes-deals-audits/aldi-a30-source-discovery.sh",
            "/etc/hermes-deals-audits.d/aldi-a30-source-discovery.conf",
            "/usr/local/sbin/hermes-deals-aldi-a30-source-discovery-dispatch",
            "github-runner ALL=(root) NOPASSWD:",
            "RUNNER_HAS_DOCKER_GROUP",
            "PRODUCTION_APPLY_AUTHORIZED=false",
        ):
            self.assertIn(required, installer)
        for required in (
            "hermes-deals-aldi-a30-source-discovery-*",
            'install -o andris -g andris -m 0600 /dev/null "$staging/audit-execution.log"',
            "page_acquisition_performed",
            "rollover_comparison_performed",
            "production_apply_authorized",
        ):
            self.assertIn(required, dispatcher)
        self.assertNotIn("NOPASSWD: ALL", installer)
        self.assertNotIn("github-runner ALL=(ALL)", installer)

    def test_workflow_is_manual_owner_only_and_uses_existing_audit_runner(self) -> None:
        workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        self.assertIn("workflow_dispatch", workflow[True])
        self.assertEqual(
            workflow["jobs"]["rpi5-audit"]["runs-on"],
            ["self-hosted", "Linux", "ARM64", "hermes-deals-audit"],
        )
        text = WORKFLOW.read_text(encoding="utf-8")
        for required in (
            'os.environ["ACTOR"] != "rozkalnsandris"',
            'os.environ["ACTOR_ID"] != "277435981"',
            "audit accepts only merged pull requests",
            "actions/upload-artifact@v6",
            "Production database write: **false**",
            "Production deployment: **not authorized**",
        ):
            self.assertIn(required, text)
        self.assertNotIn("actions/checkout", text)
        self.assertNotIn("pull_request:", text)

    def test_runbook_exists_and_keeps_install_merge_and_run_separate(self) -> None:
        text = RUNBOOK.read_text(encoding="utf-8")
        for required in (
            "merge does not install or execute the audit",
            "install-aldi-a30-source-discovery-dispatcher.sh",
            "workflow_dispatch",
            "source discovery only",
            "No production database write",
        ):
            self.assertIn(required, text)


if __name__ == "__main__":
    unittest.main()
