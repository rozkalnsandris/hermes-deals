from __future__ import annotations

import json
from pathlib import Path
import subprocess
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "tools/aldi_a30_authoritative_cycle.py"
PLAN = ROOT / "config/aldi-a30-authoritative-cycle-2026cw32-cw33.json"
RUNNER = ROOT / "tools/run-hermes-deals-aldi-a30-authoritative-cycle-v01.sh"
INSTALLER = ROOT / "tools/runner/install-aldi-a30-authoritative-cycle-dispatcher.sh"
WORKFLOW = ROOT / ".github/workflows/aldi-a30-authoritative-cycle-rpi5.yml"


class AldiA30AuthoritativeCycleContractTest(unittest.TestCase):
    def test_python_and_shell_syntax(self) -> None:
        compile(MODULE.read_text(encoding="utf-8"), str(MODULE), "exec")
        for path in (RUNNER, INSTALLER):
            subprocess.run(["bash", "-n", str(path)], check=True, capture_output=True, text=True)

    def test_plan_is_frozen_and_distinct(self) -> None:
        plan = json.loads(PLAN.read_text(encoding="utf-8"))
        self.assertEqual(
            plan["source_discovery_commit"],
            "24d1a44df06751fe9107e568ceb12c9f2c5cea79",
        )
        self.assertEqual(plan["source_discovery_run_id"], 31010778804)
        self.assertEqual(plan["old_preview_page_count"], 41)
        self.assertEqual(plan["rollover"]["required_pages"], 41)
        self.assertNotEqual(
            plan["sources"]["current"]["source_path"],
            plan["sources"]["preview"]["source_path"],
        )

    def test_workflow_is_owner_only_and_manual(self) -> None:
        document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        self.assertIn("workflow_dispatch", document[True])
        text = WORKFLOW.read_text(encoding="utf-8")
        for required in (
            "rozkalnsandris",
            "277435981",
            "self-hosted",
            "hermes-deals-audit",
            "actions/upload-artifact@v6",
        ):
            self.assertIn(required, text)

    def test_safety_boundaries(self) -> None:
        text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (MODULE, RUNNER, INSTALLER, WORKFLOW)
        )
        for required in (
            "PRODUCTION_DATABASE_WRITE=false",
            "PRODUCTION_DEPLOYMENT=false",
            "B15M2_V08_ACTION=false",
        ):
            self.assertIn(required, text)
        for forbidden in (
            "docker run",
            "docker compose",
            "psql ",
            "alembic upgrade",
            "systemctl restart",
        ):
            self.assertNotIn(forbidden, text)

    def test_dynamic_terminal_and_rollover_contract(self) -> None:
        text = MODULE.read_text(encoding="utf-8")
        for required in (
            "consecutive_terminal_failures",
            "terminal boundary not proven",
            "ROLLOVER_MATCH_41_OF_41",
            "visual_match",
            "source_roots_distinct",
        ):
            self.assertIn(required, text)


if __name__ == "__main__":
    unittest.main()
