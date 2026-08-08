from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "netto-card-region-topology-rpi5-audit.yml"
INSTALLER = ROOT / "tools" / "runner" / "install-netto-card-region-topology-rpi5-audit.sh"


class NettoCardRegionTopologyRpi5AuditControlTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.installer = INSTALLER.read_text(encoding="utf-8")

    def test_workflow_is_owner_gated_and_has_no_self_hosted_checkout(self) -> None:
        self.assertIn("pull_request_target:", self.workflow)
        self.assertIn("EXPECTED_OWNER_LOGIN: rozkalnsandris", self.workflow)
        self.assertIn('EXPECTED_OWNER_ID: "277435981"', self.workflow)
        self.assertIn("topology audits are accepted only on merged pull requests", self.workflow)
        self.assertIn("exact merged SHA has no successful main-push Hermes Deals CI checks run", self.workflow)
        audit_job = self.workflow.split("  rpi5-audit:", 1)[1].split("  report:", 1)[0]
        self.assertNotIn("actions/checkout", audit_job)
        self.assertIn("permissions: {}", audit_job)
        self.assertIn("sudo --non-interactive /usr/local/sbin/hermes-deals-netto-card-region-topology-audit-dispatch", audit_job)

    def test_reporter_has_required_pr_metadata_write_scope(self) -> None:
        report = self.workflow.split("  report:", 1)[1]
        self.assertIn("issues: write", report)
        self.assertIn("pull-requests: write", report)
        self.assertIn("audit:netto-card-region-topology-v1", report)

    def test_installer_pins_exact_runtime_and_immutable_n9_binding(self) -> None:
        self.assertIn("netto-card-region-topology-audit-v1", self.installer)
        self.assertIn("netto_card_region_topology_audit.py", self.installer)
        self.assertIn("netto_ownership_separator_audit.py", self.installer)
        self.assertIn("netto_visual_geometry_corpus_replay.py", self.installer)
        self.assertIn("netto_visual_geometry_shadow.py", self.installer)
        self.assertIn("n2_independent_ownership_summary_v1.json", self.installer)
        self.assertIn("2b180d67af4c5d1e586704088e3d685cff21ae2e12f3052254daf4553dd4e147", self.installer)
        self.assertIn("PyMuPDF 1.28.0 required", self.installer)
        self.assertIn("github-runner must not belong to the Docker group", self.installer)

    def test_dispatcher_enforces_read_only_non_promotable_contract(self) -> None:
        for marker in (
            'payload.get("classification_performed") is not False',
            'payload.get("parser_behavior_changed") is not False',
            'payload.get("review_only") is not True',
            'payload.get("promotion_ready") is not False',
            '"automatic_approval_enabled"',
            '"automatic_publish_enabled"',
            '"database_write_performed"',
            '"deployment_performed"',
            '"production_deploy": False',
            '"database_write": False',
            '"review_write": False',
            '"approval_publish": False',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.installer)

    def test_installer_does_not_execute_audit(self) -> None:
        self.assertIn('echo "AUDIT_EXECUTED=false"', self.installer)
        self.assertIn('echo "INSTALL_RESULT=PASS"', self.installer)


if __name__ == "__main__":
    unittest.main()
