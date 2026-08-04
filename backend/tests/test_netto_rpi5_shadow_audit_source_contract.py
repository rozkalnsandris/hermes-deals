from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class NettoRpi5ShadowAuditSourceContractTest(unittest.TestCase):
    def test_audit_has_no_database_or_deployment_command(self) -> None:
        text = (ROOT / "tools/netto_rpi5_shadow_audit.py").read_text(encoding="utf-8")
        for forbidden in ("docker exec", "docker compose", "psql ", "systemctl enable", "alembic upgrade"):
            self.assertNotIn(forbidden, text)
        self.assertIn('"production_apply_authorized": False', text)
        self.assertIn('"database_write_performed": False', text)
        self.assertIn('"deployment_performed": False', text)

    def test_audit_inputs_are_bounded(self) -> None:
        runner = (ROOT / "tools/run-hermes-deals-netto-shadow-evidence-v01.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("/home/andris/hermes-deals-audits", runner)
        self.assertIn("/home/andris/hermes-deals/data/raw", runner)
        self.assertIn("/var/lib/hermes-deals/netto-weekly-shadow", runner)
        self.assertNotIn("find /home", runner)

    def test_only_sanitized_directory_is_uploaded(self) -> None:
        workflow = (ROOT / ".github/workflows/netto-shadow-rpi5-audit.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn('artifact_dir=$export_dir/audit-evidence', workflow)
        self.assertNotIn('tee "$export_dir/runner-dispatch.log"', workflow)
        self.assertIn("if-no-files-found: error", workflow)


if __name__ == "__main__":
    unittest.main()
