from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/netto-shadow-rpi5-audit.yml"


class NettoRpi5ShadowAuditWorkflowEventPathTest(unittest.TestCase):
    def test_authorizer_uses_builtin_github_event_path(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn('os.environ["GITHUB_EVENT_PATH"]', text)
        self.assertIn('event_path.is_file()', text)
        self.assertIn('event_path.read_text(encoding="utf-8")', text)
        self.assertNotIn('EVENT_PATH: ${{ github.event_path }}', text)
        self.assertNotIn('os.environ["EVENT_PATH"]', text)


if __name__ == "__main__":
    unittest.main()
