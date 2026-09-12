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

    def test_acceptance_dispatcher_creates_bridge_workspace_as_execution_owner(self) -> None:
        dispatcher = (ROOT / "tools/runner/aldi-new-baseline-weekly-shadow-dispatcher.sh").read_text(encoding="utf-8")
        workspace = "/home/andris/hermes-deals-runner-evidence/aldi-new-baseline-weekly-shadow.XXXXXX"
        self.assertIn(
            f'tmp="$(runuser -u andris -- env -i PATH=/usr/bin:/bin mktemp -d {workspace})"',
            dispatcher,
        )
        self.assertNotIn(f'tmp="$(mktemp -d {workspace})"', dispatcher)
        self.assertIn('install -d -o andris -g andris -m 0700 "$tmp/input"', dispatcher)
        self.assertIn('install -d -o andris -g andris -m 0700 "$tmp/output-parent"', dispatcher)

    def test_acceptance_installer_and_dispatcher_share_canonical_registration_contract(self) -> None:
        installer = (ROOT / "tools/runner/install-aldi-new-baseline-weekly-shadow-dispatcher.sh").read_text(encoding="utf-8")
        dispatcher = (ROOT / "tools/runner/aldi-new-baseline-weekly-shadow-dispatcher.sh").read_text(encoding="utf-8")
        canonical = "/usr/local/libexec/hermes-deals-audits/aldi-new-baseline-weekly-shadow-v01/aldi_new_baseline_weekly_shadow_bridge.py"
        self.assertIn("python3", installer.split("for command in ", 1)[1].split("; do", 1)[0])
        self.assertIn("bridge_path='$LIBEXEC/aldi_new_baseline_weekly_shadow_bridge.py'", installer)
        self.assertNotIn("aldi_new_baseline_weekly-shadow_bridge.py", installer)
        self.assertIn(canonical, dispatcher)
        self.assertIn('verify_registered_file "$bridge_path" "$bridge_sha256" 555', installer)
        for name, field in (
            ("aldi_new_immutable_baseline_gate.py", "gate_a_sha256"),
            ("aldi_new_baseline_page_card_parity.py", "gate_b_sha256"),
            ("aldi_new_baseline_gate_c_replay.py", "gate_c_sha256"),
            ("aldi_new_baseline_two_cycle_shadow_gate.py", "two_cycle_sha256"),
        ):
            self.assertIn(name, installer)
            self.assertIn(field, installer)


if __name__ == "__main__":
    unittest.main()
