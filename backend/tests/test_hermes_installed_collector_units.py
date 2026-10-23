"""Synthetic #992 installed-unit identity tests: no systemctl or Git execution."""
from __future__ import annotations

import importlib.util
import io
from pathlib import Path
from contextlib import redirect_stdout
from unittest import TestCase
from unittest.mock import patch


FILE = (
    Path(__file__).resolve().parents[2]
    / "tools/verify_hermes_installed_collector_units.py"
)
spec = importlib.util.spec_from_file_location("hermes_installed_units", FILE)
units = importlib.util.module_from_spec(spec)
spec.loader.exec_module(units)
SHA = "a" * 40


def fake_source(*, changed=None, dirty=False, wrong_sha=False):
    seen = []
    scanned = []

    def run(*args):
        seen.append(args)
        if args[:3] == ("git", "-C", str(units.REPO)):
            op = args[3]
            if op == "branch":
                return b"main\n"
            if op == "rev-parse":
                return (("b" * 40 if wrong_sha else SHA) + "\n").encode()
            if op == "status":
                return b" M file\n" if dirty else b""
            if op == "remote":
                return b"https://github.com/rozkalnsandris/hermes-deals.git\n"
            if op == "cat-file":
                return b"[Unit]\nDescription=Reviewed\n"
            raise AssertionError(args)
        if args[:2] == ("systemctl", "show"):
            name = args[-1]
            path = units.SYSTEMD / name
            properties = {
                "LoadState": "loaded", "FragmentPath": str(path),
                "DropInPaths": "", "NeedDaemonReload": "no",
            }
            if changed and name == units.UNITS[0]:
                properties.update(changed)
            return ("\n".join(f"{k}={v}" for k, v in properties.items()) + "\n").encode()
        raise AssertionError(args)

    def scan(path, blob):
        scanned.append((path, blob))

    return run, scan, seen, scanned


class InstalledUnitTests(TestCase):
    def test_exact_four_units_rechecked_and_all_blobs_compared(self):
        run, scan, seen, scanned = fake_source()
        with patch.object(units.REPO, "is_dir", return_value=True), patch.object(
            type(units.REPO), "is_dir", return_value=True
        ):
            # The real checkout is intentionally unavailable in CI.
            with patch.object(units, "REPO", Path(__file__).resolve().parents[2]):
                units.verify(SHA, run=run, scan=scan)
        self.assertEqual([path.name for path, _ in scanned], list(units.UNITS))
        self.assertEqual(
            len([a for a in seen if a[:2] == ("systemctl", "show")]), 8
        )
        self.assertEqual(
            len([a for a in seen if len(a) > 3 and a[3] == "cat-file"]), 4
        )

    def test_mismatched_installed_path_or_dropin_refused(self):
        for changed in (
            {"DropInPaths": "/etc/systemd/system/override.conf"},
            {"FragmentPath": "/run/systemd/system/other.service"},
            {"NeedDaemonReload": "yes"},
            {"LoadState": "not-found"},
        ):
            with self.subTest(changed=changed):
                run, scan, _, _ = fake_source(changed=changed)
                with patch.object(units, "REPO", Path(__file__).resolve().parents[2]):
                    with self.assertRaises(units.Stop):
                        units.verify(SHA, run=run, scan=scan)

    def test_dirty_or_stale_git_head_is_not_accepted(self):
        for case in ({"dirty": True}, {"wrong_sha": True}):
            with self.subTest(case=case):
                run, scan, _, scanned = fake_source(**case)
                with patch.object(units, "REPO", Path(__file__).resolve().parents[2]):
                    with self.assertRaises(units.Stop):
                        units.verify(SHA, run=run, scan=scan)
                self.assertEqual(scanned, [])

    def test_invalid_sha_fails_before_host_reads(self):
        run, scan, seen, _ = fake_source()
        with self.assertRaises(units.Stop):
            units.verify("../main", run=run, scan=scan)
        self.assertEqual(seen, [])

    def test_metadata_rejects_symlink_group_write_and_nonroot(self):
        class Meta:
            st_mode = 0o100644
            st_uid = 0
            st_gid = 0
            st_nlink = 1
            st_size = 512

        units._check_metadata(Meta())
        for key, value in (
            ("st_mode", 0o100664), ("st_mode", 0o120777),
            ("st_uid", 1000), ("st_gid", 1000),
            ("st_nlink", 2), ("st_size", 0),
        ):
            with self.subTest(key=key, value=value):
                meta = Meta()
                setattr(meta, key, value)
                with self.assertRaises(units.Stop):
                    units._check_metadata(meta)

    def test_no_unapproved_execution_surface_in_source(self):
        src = FILE.read_text(encoding="utf-8")
        for forbidden in (
            "systemctl restart", "systemctl reload", "daemon-reload",
            "docker ", "chmod(", "chown(", "os.mkdir(", "os.unlink(",
        ):
            self.assertNotIn(forbidden, src)
        self.assertIn('cat-file", "blob"', src)

    def test_main_failure_emits_sanitized_stop(self):
        out = io.StringIO()
        with redirect_stdout(out), patch.object(
            units.pwd, "getpwuid", side_effect=RuntimeError("secret")
        ):
            status = units.main(["--expected-source-sha", SHA])
        self.assertEqual(status, 2)
        self.assertEqual(out.getvalue(), "HERMES_INSTALLED_COLLECTOR_UNITS=STOP\n")
