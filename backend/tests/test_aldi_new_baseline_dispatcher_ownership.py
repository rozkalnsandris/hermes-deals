from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]

DISPATCHERS = (
    ROOT / "tools/runner/aldi-new-baseline-weekly-shadow-producer-dispatcher.sh",
    ROOT / "tools/runner/aldi-new-baseline-weekly-shadow-dispatcher.sh",
)
INSTALLERS = (
    ROOT / "tools/runner/install-aldi-new-baseline-weekly-shadow-producer-dispatcher.sh",
    ROOT / "tools/runner/install-aldi-new-baseline-weekly-shadow-dispatcher.sh",
)


class AldiNewBaselineDispatcherOwnershipTest(unittest.TestCase):
    def test_dispatchers_read_primary_repo_as_owner(self) -> None:
        for path in DISPATCHERS:
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertIn("git_read() {", text)
                self.assertIn("runuser -u andris -- env -i", text)
                self.assertIn("HOME=/home/andris USER=andris LOGNAME=andris", text)
                self.assertIn("GIT_OPTIONAL_LOCKS=0", text)
                self.assertIn('git -C "$PRIMARY_REPO" "$@"', text)
                self.assertNotIn("safe.directory", text)
                self.assertNotIn(
                    'git_read() { GIT_OPTIONAL_LOCKS=0 git -C "$PRIMARY_REPO"',
                    text,
                )

    def test_installers_read_primary_repo_as_owner_and_require_runuser(self) -> None:
        for path in INSTALLERS:
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertIn("git_read() {", text)
                self.assertIn("runuser -u andris -- env -i", text)
                self.assertIn("HOME=/home/andris USER=andris LOGNAME=andris", text)
                self.assertIn("GIT_OPTIONAL_LOCKS=0", text)
                self.assertIn('git -C "$REPO" "$@"', text)
                self.assertIn(" runuser ", text)
                self.assertNotIn("safe.directory", text)
                self.assertNotIn(
                    'git_read() { GIT_OPTIONAL_LOCKS=0 git -C "$REPO"',
                    text,
                )


if __name__ == "__main__":
    unittest.main()
