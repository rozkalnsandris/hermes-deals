from __future__ import annotations

from contextlib import nullcontext
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from app import aldi_cutover_canary as canary
from app import aldi_cutover_verify, db, probe, settings, source_config

RAW_ROOT_CHECK = canary._check_raw_root


class AldiCutoverCanaryTests(unittest.TestCase):
    def setUp(self):
        self.source = SimpleNamespace(enabled=True, chain="aldi_nord")
        self.config = SimpleNamespace(raw_snapshot_dir=canary.RAW_ROOT,
                                      sources_config=canary.CONFIG)
        self.snapshot = SimpleNamespace(id=uuid4(), success=True,
                                        snapshot_path="/data/raw/aldi_nord/new.html")
        self.session = object()
        self.probe = Mock(return_value=self.snapshot)
        self.verify = Mock()
        self.stack = [
            patch.object(canary.os, "geteuid", return_value=1000),
            patch.object(canary.os, "getegid", return_value=1000),
            patch.object(canary, "_check_raw_root"),
            patch.object(settings, "get_settings", return_value=self.config),
            patch.object(source_config, "load_sources", return_value=[self.source]),
            patch.object(db, "SessionLocal", return_value=nullcontext(self.session)),
            patch.object(probe, "probe_source", self.probe),
            patch.object(aldi_cutover_verify, "verify", self.verify),
        ]
        for item in self.stack:
            item.start()
            self.addCleanup(item.stop)

    def test_one_bounded_probe_is_verified_without_offer_persistence(self):
        canary.run_canary()
        self.probe.assert_called_once_with(self.session, self.source,
                                           max_content_bytes=canary.MAX_RESPONSE)
        self.verify.assert_called_once()
        args, kwargs = self.verify.call_args
        self.assertEqual(args[:2], (self.session, self.snapshot.id))
        self.assertLessEqual(args[2], kwargs["now"])

    def test_wrong_raw_root_stops_before_session_or_write(self):
        self.config.raw_snapshot_dir = Path("/legacy/raw")
        with self.assertRaises(canary.Stop):
            canary.run_canary()
        self.probe.assert_not_called()

    def test_failed_snapshot_stops_without_claiming_api_provenance(self):
        self.snapshot.success = False
        with self.assertRaises(canary.Stop):
            canary.run_canary()
        self.probe.assert_called_once()
        self.verify.assert_not_called()

    def test_raw_root_requires_reviewed_owner_group_and_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "raw"
            root.mkdir()
            os.chmod(root, 0o3775)
            RAW_ROOT_CHECK(root, owner=os.getuid(), collector_gid=os.getgid())
            os.chmod(root, 0o2775)
            with self.assertRaises(canary.Stop):
                RAW_ROOT_CHECK(root, owner=os.getuid(), collector_gid=os.getgid())
            os.chmod(root, 0o3775)
            link = Path(directory) / "linked"
            link.symlink_to(root)
            with self.assertRaises(OSError):
                RAW_ROOT_CHECK(link, owner=os.getuid(), collector_gid=os.getgid())

    def test_cli_suppresses_library_output_and_reports_unknown_mutation(self):
        root = Path(__file__).resolve().parents[1]
        program = (
            "from app import aldi_cutover_canary as c; "
            "import sys; "
            "definitely_private = lambda: (print('SOURCE_URL'), "
            "print('DB_ERROR', file=sys.stderr), "
            "(_ for _ in ()).throw(RuntimeError('private detail'))); "
            "c.run_canary = definitely_private; "
            "raise SystemExit(c.main([]))"
        )
        env = dict(os.environ, PYTHONPATH=str(root))
        result = subprocess.run([sys.executable, "-c", program], env=env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout,
                         "ALDI_CUTOVER_CANARY=STOP\nMUTATION_OUTCOME=UNKNOWN\n")
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
