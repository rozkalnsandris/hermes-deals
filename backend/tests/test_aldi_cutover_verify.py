from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import io
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from uuid import uuid4

from app import aldi_cutover_verify as canary
from app.aldi_cutover_verify import Stop, verify


class _Database:
    def __init__(self, row):
        self.row = row
        self.reads = 0

    def get(self, _model, _identifier):
        self.reads += 1
        return self.row


class AldiCutoverVerifyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "raw"
        self.root.mkdir()
        os.chmod(self.root, 0o3775)
        folder = self.root / "aldi_nord"
        folder.mkdir()
        os.chmod(folder, 0o3775)
        self.content = b"immutable example evidence" * 60
        self.file = folder / "20261015T120000Z-example.html"
        self.file.write_bytes(self.content)
        os.chmod(self.file, 0o640)
        self.now = datetime(2026, 10, 15, 12, 1, tzinfo=timezone.utc)
        self.after = self.now - timedelta(minutes=2)
        self.identifier = uuid4()
        self.digest = hashlib.sha256(self.content).hexdigest()
        self.row = SimpleNamespace(
            id=self.identifier, source_chain="aldi_nord", success=True,
            collected_at=self.now - timedelta(minutes=1),
            snapshot_path=str(self.file), sha256=self.digest,
            content_bytes=len(self.content),
        )
        self.db = _Database(self.row)

    def _api(self):
        return [{"id": str(self.identifier), "source_chain": "aldi_nord",
                 "sha256": self.digest, "content_bytes": len(self.content),
                 "success": True}]

    def _verify(self):
        verify(self.db, self.identifier, self.after, root=self.root,
               now=self.now, api_latest=self._api, root_owner=os.getuid(),
               snapshot_model=object())

    def test_recent_collector_file_and_api_row_match_without_writes(self):
        before = self.file.read_bytes()
        self._verify()
        self.assertEqual(self.db.reads, 1)
        self.assertEqual(self.file.read_bytes(), before)

    def test_mutated_file_or_database_digest_stops(self):
        self.file.write_bytes(b"changed evidence")
        with self.assertRaises(Stop):
            self._verify()
        self.file.write_bytes(self.content)
        self.row.sha256 = "0" * 64
        with self.assertRaises(Stop):
            self._verify()

    def test_old_or_failed_snapshot_stops_before_file_read(self):
        self.row.collected_at = self.after - timedelta(seconds=1)
        with self.assertRaises(Stop):
            self._verify()
        self.row.collected_at = self.now
        self.row.success = False
        with self.assertRaises(Stop):
            self._verify()

    def test_symlink_and_wrong_root_mode_stop(self):
        link = self.root / "aldi_nord" / "linked.html"
        link.symlink_to(self.file)
        self.row.snapshot_path = str(link)
        with self.assertRaises(Stop):
            self._verify()
        self.row.snapshot_path = str(self.file)
        os.chmod(self.root, 0o2775)
        with self.assertRaises(Stop):
            self._verify()

    def test_wrong_api_snapshot_stops(self):
        def other_api():
            rows = self._api()
            rows[0]["id"] = str(uuid4())
            return rows

        with self.assertRaises(Stop):
            verify(self.db, self.identifier, self.after, root=self.root,
                   now=self.now, api_latest=other_api, root_owner=os.getuid(),
                   snapshot_model=object())

    def test_directory_replacement_during_read_stops(self):
        original_read = os.read
        renamed = False

        def read_and_rename(fd, count):
            nonlocal renamed
            chunk = original_read(fd, count)
            if chunk and not renamed:
                (self.root / "aldi_nord").rename(self.root / "moved")
                renamed = True
            return chunk

        with patch.object(canary.os, "read", side_effect=read_and_rename):
            with self.assertRaises(Stop):
                self._verify()
        self.assertTrue(renamed)

    def test_outside_raw_root_stops(self):
        self.row.snapshot_path = str(self.file.parent.parent.parent / "other.html")
        with self.assertRaises(Stop):
            self._verify()

    def test_fixed_loopback_api_read_rejects_redirect(self):
        class Response:
            status = 302

            def getheader(self, *_args):
                return "application/json"

        class Connection:
            def __init__(self, host, port, timeout):
                self.asserted = (host, port, timeout)

            def request(self, method, path):
                self.requested = (method, path)

            def getresponse(self):
                return Response()

            def close(self):
                pass

        connection = Connection("127.0.0.1", 8000, 3)
        with patch.object(canary.http.client, "HTTPConnection", return_value=connection):
            with self.assertRaises(Stop):
                canary._api_latest()
        self.assertEqual(connection.asserted, ("127.0.0.1", 8000, 3))
        self.assertEqual(connection.requested, ("GET", "/api/v1/sources/latest"))

    def test_invalid_invocation_has_only_fixed_stop_output(self):
        output = io.StringIO()
        with redirect_stdout(output):
            status = canary.main(["--snapshot-id", str(self.identifier),
                                  "--after-utc", "SECRET_INVALID_TIMESTAMP"])
        self.assertEqual(status, 2)
        self.assertEqual(output.getvalue(), "COLLECTOR_CUTOVER_VERIFY=STOP\n")


if __name__ == "__main__":
    unittest.main()
