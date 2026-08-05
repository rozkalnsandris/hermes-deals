from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "tools/runner/install-netto-shadow-rpi5-audit.sh"


class NettoAuditExecutionLogOwnershipTest(unittest.TestCase):
    def test_dispatcher_keeps_live_log_outside_audit_output(self) -> None:
        text = INSTALLER.read_text(encoding="utf-8")

        log_path = (
            'LOG_FILE="$STAGING_ROOT/'
            '.${RUN_KEY}.audit-execution.log"'
        )
        root_create = (
            'install -o root -g root -m 0600 '
            '/dev/null "$LOG_FILE"'
        )
        redirect = '> "$LOG_FILE" 2>&1'
        export = (
            'install -o andris -g andris -m 0600 \\\n'
            '  "$LOG_FILE" \\\n'
            '  "$STAGING_DIR/audit-execution.log"'
        )

        self.assertEqual(text.count(log_path), 1)
        self.assertEqual(text.count(root_create), 1)
        self.assertEqual(text.count(redirect), 1)
        self.assertEqual(text.count(export), 1)

        self.assertNotIn(
            '> "$STAGING_DIR/audit-execution.log" 2>&1',
            text,
        )

        self.assertLess(text.index(root_create), text.index(redirect))
        self.assertLess(text.index("AUDIT_RC=$?"), text.index(export))
        self.assertIn('rm -f -- "$LOG_FILE"', text)

    def test_exported_log_remains_inside_fixed_sanitizer_allowlist(
        self,
    ) -> None:
        text = INSTALLER.read_text(encoding="utf-8")

        self.assertIn('"audit-execution.log",', text)
        self.assertIn(
            '"$STAGING_DIR/audit-execution.log"',
            text,
        )


if __name__ == "__main__":
    unittest.main()
