from __future__ import annotations

import hashlib
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx

from app import probe
from app.source_config import SourceConfig


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 14, 12, 0, 0, tzinfo=timezone.utc)


class _Session:
    def __init__(self):
        self.snapshot = None

    def add(self, snapshot):
        self.snapshot = snapshot

    def commit(self):
        pass

    def refresh(self, snapshot):
        assert snapshot is self.snapshot


class _Client:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def get(self, _url):
        return self.response

    def stream(self, _method, _url):
        return _Stream(self.response)


class _Stream:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self.response

    def __exit__(self, *_args):
        return False


class ProbeSnapshotWriteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.content = b"<html>offers</html>" * 80
        self.source = SourceConfig(
            chain="aldi_nord", enabled=True, priority=1,
            url="https://example.invalid/offers", scope="test", notes="",
            keywords=("offers",),
        )

    def _probe(self):
        response = httpx.Response(
            200, content=self.content, headers={"content-type": "text/html"},
            request=httpx.Request("GET", self.source.url),
        )
        settings = SimpleNamespace(
            raw_snapshot_dir=self.root,
            http_user_agent="HermesDealsTest/1",
        )
        db = _Session()
        with (
            patch.object(probe, "get_settings", return_value=settings),
            patch.object(probe, "datetime", _FrozenDatetime),
            patch.object(probe.httpx, "Client", return_value=_Client(response)),
        ):
            result = probe.probe_source(db, self.source)
        self.assertIs(result, db.snapshot)
        return result

    def test_new_snapshot_is_written(self):
        result = self._probe()
        self.assertTrue(result.success)
        self.assertEqual(Path(result.snapshot_path).read_bytes(), self.content)

    def test_existing_snapshot_is_never_overwritten(self):
        digest = hashlib.sha256(self.content).hexdigest()[:12]
        folder = self.root / self.source.chain
        folder.mkdir()
        existing = folder / f"20261014T120000Z-{digest}.html"
        existing.write_bytes(b"previous immutable evidence")

        result = self._probe()

        self.assertEqual(existing.read_bytes(), b"previous immutable evidence")
        self.assertFalse(result.success)
        self.assertEqual(result.strategy_hint, "snapshot_write_error")
        self.assertIsNone(result.snapshot_path)

    def test_storage_permission_failure_is_not_reported_as_network_failure(self):
        original_open = Path.open

        def denied(path, *args, **kwargs):
            if path.parent == self.root / self.source.chain:
                raise PermissionError("snapshot directory is not writable")
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", denied):
            result = self._probe()

        self.assertFalse(result.success)
        self.assertEqual(result.strategy_hint, "snapshot_write_error")
        self.assertIsNone(result.snapshot_path)

    def test_bounded_probe_rejects_oversized_response_before_raw_write(self):
        response = httpx.Response(
            200, content=self.content, headers={"content-type": "text/html"},
            request=httpx.Request("GET", self.source.url),
        )
        settings = SimpleNamespace(raw_snapshot_dir=self.root,
                                   http_user_agent="HermesDealsTest/1")
        db = _Session()
        with (
            patch.object(probe, "get_settings", return_value=settings),
            patch.object(probe.httpx, "Client", return_value=_Client(response)),
        ):
            result = probe.probe_source(db, self.source, max_content_bytes=1024)
        self.assertIs(result, db.snapshot)
        self.assertFalse(result.success)
        self.assertEqual(result.strategy_hint, "response_too_large")
        self.assertIsNone(result.snapshot_path)
        self.assertFalse((self.root / self.source.chain).exists())

    def test_bounded_probe_keeps_exact_payload_and_digest(self):
        response = httpx.Response(
            200, content=self.content, headers={"content-type": "text/html"},
            request=httpx.Request("GET", self.source.url),
        )
        settings = SimpleNamespace(raw_snapshot_dir=self.root,
                                   http_user_agent="HermesDealsTest/1")
        db = _Session()
        with (
            patch.object(probe, "get_settings", return_value=settings),
            patch.object(probe.httpx, "Client", return_value=_Client(response)),
        ):
            result = probe.probe_source(db, self.source,
                                        max_content_bytes=len(self.content))
        self.assertTrue(result.success)
        self.assertEqual(result.sha256, hashlib.sha256(self.content).hexdigest())
        self.assertEqual(Path(result.snapshot_path).read_bytes(), self.content)


if __name__ == "__main__":
    unittest.main()
