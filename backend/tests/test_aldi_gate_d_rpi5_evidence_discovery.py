from __future__ import annotations

import importlib.util
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "aldi_gate_d_rpi5_evidence_discovery.py"
spec = importlib.util.spec_from_file_location("aldi_gate_d_rpi5_evidence_discovery_tested", TOOL)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


class FakeGateD:
    @staticmethod
    def load_gate_b_authoritative(path: Path):
        return (
            {
                "decision": "READY_FOR_SHADOW_REPLAY",
                "replay_fingerprint": "f" * 64,
            },
            {"identity": {"current_manifest_sha256": "c" * 64}},
        )

    @staticmethod
    def validate_legacy_page_manifest(path: Path):
        payload = json.loads(path.read_text(encoding="utf-8"))
        root = path.parent.parent / "raw" / "page-images"
        rows = []
        for label, count in (("current", 49), ("preview", 41)):
            for page in range(1, count + 1):
                data = (root / label / f"page-{page:03d}.img").read_bytes()
                rows.append(
                    {
                        "label": label,
                        "page_number": page,
                        "sha256": digest(data),
                        "bytes": len(data),
                        "format": "jpeg",
                    }
                )
        return {"rows": rows, "page_set_sha256": payload["page_set"]}

    @staticmethod
    def validate_image(
        path: Path,
        *,
        expected_sha256: str,
        expected_bytes: int,
        expected_format: str,
    ):
        if path.is_symlink() or not path.is_file():
            raise ValueError("unsafe image")
        data = path.read_bytes()
        if (
            len(data) != expected_bytes
            or digest(data) != expected_sha256
            or expected_format != "jpeg"
        ):
            raise ValueError("image mismatch")
        return data, ".jpg"


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "state"
        self.root.mkdir()
        self.gate_b = Path(self.tmp.name) / "gate-b.json"
        self.archive_bytes = b"archive"
        self.projection_bytes = b"projection"
        self.gate_b_bytes = b"gate-b"
        self.page3_bytes = b"page3"
        self.gate_b.write_bytes(self.gate_b_bytes)
        module.EXPECTED_A21_ARCHIVE_SHA256 = digest(self.archive_bytes)
        module.EXPECTED_A21_PROJECTION_SHA256 = digest(self.projection_bytes)
        module.EXPECTED_GATE_B_PLAN_SHA256 = digest(self.gate_b_bytes)
        module.EXPECTED_PAGE3_SHA256 = digest(self.page3_bytes)

        (self.root / "hermes-deals-aldi-a21-test.tar.gz").write_bytes(
            self.archive_bytes
        )
        projection = (
            self.root
            / "extract"
            / "reports"
            / "a21-adjudicated-projection.jsonl"
        )
        projection.parent.mkdir(parents=True)
        projection.write_bytes(self.projection_bytes)
        page3 = (
            self.root
            / "a30-authoritative-cycle-github"
            / "run1"
            / "evidence"
            / "pages"
            / "current"
            / "page-003.img"
        )
        page3.parent.mkdir(parents=True)
        page3.write_bytes(self.page3_bytes)
        self.make_legacy("run1", "1" * 64)

    def tearDown(self):
        self.tmp.cleanup()

    def make_legacy(self, name: str, page_set: str) -> Path:
        run = self.root / "a30-v02-runs" / name
        manifest = run / "reports" / "page-image-manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            json.dumps({"page_set": page_set}),
            encoding="utf-8",
        )
        for label, count in (("current", 49), ("preview", 41)):
            folder = run / "raw" / "page-images" / label
            folder.mkdir(parents=True, exist_ok=True)
            for page in range(1, count + 1):
                (folder / f"page-{page:03d}.img").write_bytes(
                    f"{label}-{page}".encode()
                )
        return manifest

    def discover(self):
        return module.discover_evidence(
            state_root=self.root,
            gate_b_plan=self.gate_b,
            gate_d_module=FakeGateD,
        )

    def test_ready_and_duplicate_exact_copies_are_allowed(self):
        copy = self.root / "copies" / "hermes-deals-aldi-a21-copy.tar.gz"
        copy.parent.mkdir()
        copy.write_bytes(self.archive_bytes)
        self.make_legacy("run2", "1" * 64)

        result = self.discover()

        self.assertEqual(result["decision"], module.READY)
        self.assertEqual(len(result["matches"]["a21_archives"]), 2)
        self.assertEqual(len(result["matches"]["legacy_a30_runs"]), 2)
        self.assertEqual(result["identity"]["legacy_page_set_sha256"], "1" * 64)
        self.assertFalse(result["review_pack_execution_authorized"])
        for value in result["selected"].values():
            self.assertFalse(str(value or "").startswith("/"))

    def test_missing_page3_waits(self):
        page3 = (
            self.root
            / "a30-authoritative-cycle-github"
            / "run1"
            / "evidence"
            / "pages"
            / "current"
            / "page-003.img"
        )
        page3.unlink()

        result = self.discover()

        self.assertEqual(result["decision"], module.WAIT)
        self.assertIn("authoritative_current_page3", result["missing_inputs"])

    def test_distinct_legacy_page_sets_block(self):
        self.make_legacy("run2", "2" * 64)

        result = self.discover()

        self.assertEqual(result["decision"], module.BLOCKED)
        self.assertEqual(
            result["reason"],
            "multiple_distinct_valid_legacy_page_sets",
        )

    def test_tampered_archive_is_not_selected(self):
        archive = self.root / "hermes-deals-aldi-a21-test.tar.gz"
        archive.write_bytes(b"tampered")

        result = self.discover()

        self.assertEqual(result["decision"], module.WAIT)
        self.assertIn("a21_archive", result["missing_inputs"])

    def test_symlinked_projection_is_ignored(self):
        projection = (
            self.root
            / "extract"
            / "reports"
            / "a21-adjudicated-projection.jsonl"
        )
        target = self.root / "projection-real.jsonl"
        target.write_bytes(self.projection_bytes)
        projection.unlink()
        projection.symlink_to(target)

        result = self.discover()

        self.assertEqual(result["decision"], module.WAIT)
        self.assertIn("a21_projection", result["missing_inputs"])

    def test_create_only_output_is_idempotent(self):
        result = self.discover()
        output = Path(self.tmp.name) / "plan.json"

        self.assertEqual(module.write_create_only(output, result), "created")
        self.assertEqual(module.write_create_only(output, result), "unchanged")
        output.write_text("{}\n", encoding="utf-8")
        with self.assertRaises(module.DiscoveryError):
            module.write_create_only(output, result)


if __name__ == "__main__":
    unittest.main()
