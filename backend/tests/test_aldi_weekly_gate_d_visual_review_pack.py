from __future__ import annotations

import importlib.util
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "tools"
    / "aldi_weekly_gate_d_visual_review_pack.py"
)
SPEC = importlib.util.spec_from_file_location("gate_d", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def canonical_bytes(value):
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


class GateDTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.legacy_root = self.root / "legacy"
        self.current_root = self.root / "current"
        self.legacy_root.mkdir()
        self.current_root.mkdir()
        self.page_counts = {"current": 2, "preview": 1}
        self.minimum = 16

        rows = []
        for label, count in self.page_counts.items():
            for page in range(1, count + 1):
                data = b"\xff\xd8" + f"{label}-{page}".encode() + b"x" * 40
                path = self.legacy_root / label / f"page-{page:03d}.img"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                rows.append(
                    {
                        "label": label,
                        "page_number": page,
                        "format": "jpeg",
                        "bytes": len(data),
                        "sha256": sha256(data).hexdigest(),
                    }
                )
        self.legacy_manifest = self.root / "legacy-manifest.json"
        self.legacy_manifest.write_text(
            json.dumps({"strategy": "test", "rows": rows}),
            encoding="utf-8",
        )

        page3 = b"\xff\xd8page3" + b"z" * 50
        self.current_page3 = self.current_root / "page-003.img"
        self.current_page3.write_bytes(page3)
        self.page3_sha = sha256(page3).hexdigest()
        self.old_page3_sha = MODULE.EXPECTED_PAGE3_SHA256
        MODULE.EXPECTED_PAGE3_SHA256 = self.page3_sha

        projection_rows = [
            {
                "source_page": "current",
                "source_offer_id": "a",
                "identity": {"display_title_candidate": "Alpha"},
                "pricing": {"price_eur": "1.00"},
                "publication": {
                    "status": "auto_candidate",
                    "review_reasons": [],
                },
            },
            {
                "source_page": "preview",
                "source_offer_id": "b",
                "identity": {"display_title_candidate": "Beta"},
                "pricing": {"price_eur": "2.00"},
                "publication": {
                    "status": "review_required",
                    "review_reasons": ["ambiguous_title"],
                },
            },
            {
                "source_page": "current",
                "source_offer_id": "c",
                "identity": {"display_title_candidate": "Gamma"},
                "pricing": {"price_eur": "3.00"},
                "publication": {
                    "status": "blocked_out_of_scope",
                    "review_reasons": [],
                },
            },
        ]
        self.projection = self.root / "projection.jsonl"
        self.projection.write_bytes(
            b"".join(canonical_bytes(row) for row in projection_rows)
        )
        self.projection_sha = sha256(self.projection.read_bytes()).hexdigest()
        self.counts = {
            "auto_candidate": 1,
            "review_required": 1,
            "blocked_out_of_scope": 1,
        }
        self.gate_b = self.root / "gate-b.json"
        self.gate_b.write_text("{}", encoding="utf-8")

    def tearDown(self):
        MODULE.EXPECTED_PAGE3_SHA256 = self.old_page3_sha
        self.tmp.cleanup()

    def loader(self, _path):
        return (
            {
                "decision": "READY_FOR_SHADOW_REPLAY",
                "replay_fingerprint": "f" * 64,
            },
            {
                "identity": {"current_manifest_sha256": "m" * 64},
                "manifest_by_page": {
                    3: {
                        "page_number": 3,
                        "sha256": self.page3_sha,
                        "bytes": self.current_page3.stat().st_size,
                        "image_format": "jpeg",
                    }
                },
            },
        )

    def build(self, name="out"):
        return MODULE.create_review_pack(
            MODULE.PackInputs(
                projection=self.projection,
                legacy_page_manifest=self.legacy_manifest,
                legacy_page_root=self.legacy_root,
                gate_b_plan=self.gate_b,
                current_pages_root=self.current_root,
                output=self.root / name,
                commit_sha="a" * 40,
            ),
            gate_b_loader=self.loader,
            expected_projection_sha256=self.projection_sha,
            expected_projection_counts=self.counts,
            expected_projection_rows=3,
            expected_page_counts=self.page_counts,
            minimum_image_bytes=self.minimum,
        )

    def test_builds_manual_review_pack_without_claiming_gate_c_ready(self):
        manifest = self.build()
        out = self.root / "out"
        self.assertEqual(manifest["decision"], MODULE.DECISION)
        self.assertFalse(manifest["gate_c_ready"])
        self.assertFalse(manifest["production_eligible"])
        self.assertEqual(manifest["counts"]["legacy_page_count"], 3)
        self.assertEqual(manifest["counts"]["target_candidate_hint_count"], 2)
        self.assertEqual(manifest["counts"]["automatic_assignments"], 0)
        self.assertTrue((out / "index.html").is_file())
        self.assertTrue((out / "images/current/page-003.jpg").is_file())
        legacy = json.loads(
            (out / "legacy-card-ledger-template.json").read_text()
        )
        self.assertEqual(legacy["cards"], [])
        self.assertEqual(len(legacy["candidate_hints"]), 2)
        page3 = json.loads(
            (out / "page3-fresh-shadow-extraction-template.json").read_text()
        )
        self.assertEqual(
            page3["extraction_result"],
            "pending_manual_visual_review",
        )
        self.assertEqual(page3["candidates"], [])
        self.assertFalse(page3["production_eligible"])

    def test_tampered_legacy_image_fails_closed_and_leaves_no_output(self):
        path = self.legacy_root / "current/page-001.img"
        path.write_bytes(path.read_bytes() + b"tamper")
        with self.assertRaisesRegex(MODULE.GateDError, "byte count mismatch"):
            self.build()
        self.assertFalse((self.root / "out").exists())
        self.assertFalse((self.root / "out.tmp").exists())

    def test_page3_tamper_fails_closed(self):
        self.current_page3.write_bytes(self.current_page3.read_bytes() + b"x")
        with self.assertRaisesRegex(MODULE.GateDError, "current page 3 SHA mismatch"):
            self.build()

    def test_existing_output_is_never_overwritten(self):
        out = self.root / "out"
        out.mkdir()
        marker = out / "marker"
        marker.write_text("keep")
        with self.assertRaisesRegex(MODULE.GateDError, "output already exists"):
            self.build()
        self.assertEqual(marker.read_text(), "keep")

    def test_duplicate_projection_identity_is_rejected(self):
        rows = [
            {
                "source_page": "current",
                "source_offer_id": "a",
                "identity": {},
                "pricing": {},
                "publication": {"status": "auto_candidate"},
            },
            {
                "source_page": "current",
                "source_offer_id": "a",
                "identity": {},
                "pricing": {},
                "publication": {"status": "review_required"},
            },
        ]
        self.projection.write_bytes(
            b"".join(canonical_bytes(row) for row in rows)
        )
        with self.assertRaisesRegex(MODULE.GateDError, "duplicate projection"):
            MODULE.load_projection(
                self.projection,
                expected_sha256=sha256(
                    self.projection.read_bytes()
                ).hexdigest(),
                expected_counts={
                    "auto_candidate": 1,
                    "review_required": 1,
                },
                expected_rows=2,
            )

    def test_identical_inputs_produce_identical_manifests(self):
        first = self.build("one")
        second = self.build("two")
        self.assertEqual(first, second)
        for relative in (
            "review-index.json",
            "legacy-card-ledger-template.json",
            "page3-fresh-shadow-extraction-template.json",
            "candidate-hints.json",
            "index.html",
        ):
            self.assertEqual(
                (self.root / "one" / relative).read_bytes(),
                (self.root / "two" / relative).read_bytes(),
            )

    def test_invalid_commit_sha_is_rejected(self):
        with self.assertRaisesRegex(MODULE.GateDError, "commit SHA"):
            MODULE.create_review_pack(
                MODULE.PackInputs(
                    projection=self.projection,
                    legacy_page_manifest=self.legacy_manifest,
                    legacy_page_root=self.legacy_root,
                    gate_b_plan=self.gate_b,
                    current_pages_root=self.current_root,
                    output=self.root / "bad-sha",
                    commit_sha="not-a-sha",
                ),
                gate_b_loader=self.loader,
                expected_projection_sha256=self.projection_sha,
                expected_projection_counts=self.counts,
                expected_projection_rows=3,
                expected_page_counts=self.page_counts,
                minimum_image_bytes=self.minimum,
            )

    def test_html_uses_text_nodes_for_candidate_content(self):
        self.build()
        content = (self.root / "out/index.html").read_text(encoding="utf-8")
        self.assertNotIn("div.innerHTML", content)
        self.assertIn("strong.textContent", content)
        self.assertIn("key.textContent", content)
