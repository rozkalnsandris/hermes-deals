from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "lidl_gate_b_freeze_plan.py"
SPEC = importlib.util.spec_from_file_location("lidl_gate_b_freeze_plan", TOOL)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def canonical_bytes(payload: dict[str, object]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()


class LidlGateBFreezePlanTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.evidence_root = self.root / "evidence"
        self.corpus_root = self.root / "corpus"
        self.flyers_root = self.corpus_root / "flyers"
        self.run_dir = self.evidence_root / "lidl-gate-a-20260806T133221Z"
        self.family_root = (
            self.run_dir
            / "controller"
            / "one-shot"
            / "discovery"
            / "family-current"
        )
        self.flyers_root.mkdir(parents=True)
        self.family_root.mkdir(parents=True)
        self._write_fixture()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_json(self, path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical_bytes(payload))

    def _write_fixture(self) -> None:
        source_payload = {
            "dateTime": "2026-08-02T12:16:00Z",
            "flyer": {
                "id": "3385100",
                "flyerUrlAbsolute": (
                    "https://www.lidl.de/l/prospekte/"
                    "aktionsprospekt-03-08-2026-08-08-2026/ar/21"
                ),
                "hiResPdfUrl": (
                    "https://endpoints.leaflets.schwarz/"
                    "flyer/3385100/source.pdf"
                ),
                "offerStartDate": "2026-08-03",
                "offerEndDate": "2026-08-08",
                "regions": [{"code": "21"}, {"code": "7"}],
                "pages": [{"number": index} for index in range(1, 70)],
            },
        }
        source_json = json.dumps(
            source_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        source_pdf = b"%PDF-1.7\nfixture-lidl-week-32\n"
        pdf_sha = sha256(source_pdf).hexdigest()
        raw_sha = sha256(source_json).hexdigest()
        self.source_pdf = source_pdf
        self.source_json = source_json
        self.pdf_sha = pdf_sha
        self.raw_sha = raw_sha

        (self.family_root / "source.pdf").write_bytes(source_pdf)
        (self.family_root / "source.json").write_bytes(source_json)
        meta = {
            "target": "current",
            "flyer_identifier": (
                "aktionsprospekt-03-08-2026-08-08-2026-a1b2c3"
            ),
            "route_region": "21",
            "valid_from": "2026-08-03",
            "valid_until": "2026-08-08",
            "viewer_url": source_payload["flyer"]["flyerUrlAbsolute"],
            "viewer_final_url": source_payload["flyer"]["flyerUrlAbsolute"],
            "official_flyer_id": "3385100",
            "document_url": source_payload["flyer"]["hiResPdfUrl"],
            "advertised_regions": ["21", "7"],
            "pdf_sha256": pdf_sha,
            "raw_sha256": raw_sha,
            "pdf_bytes": len(source_pdf),
            "raw_bytes": len(source_json),
            "page_count": 69,
        }
        self._write_json(self.family_root / "meta.json", meta)
        self._write_json(
            self.family_root.parent / "discovery.json",
            {
                "today_berlin": "2026-08-06",
                "store_external_id": "DE06664",
                "targets": {"current": meta},
            },
        )
        self._write_json(
            self.run_dir / "controller" / "controller-manifest.json",
            {
                "schema_version": 1,
                "controller_version": "lidl-weekly-shadow-controller-v1",
                "result": "WAIT",
                "reason": "one_shot_wait_source",
                "one_shot_result": "WAIT_SOURCE",
                "one_shot_reason": (
                    "exact_source_not_archived_in_immutable_corpus"
                ),
                "target": "current",
                "today_berlin": "2026-08-06",
                "execution_fingerprint": None,
                "new_immutable_snapshot_required": False,
                "shadow_execution_required": False,
                "dry_run": True,
                "corpus_write_authorized": False,
                "database_write_authorized": False,
                "review_write_authorized": False,
                "production_publish_authorized": False,
                "systemd_change_authorized": False,
                "bounded_retry_authorized": False,
            },
        )
        self._write_json(
            self.run_dir
            / "controller"
            / "one-shot"
            / "one-shot-status.json",
            {
                "schema_version": 1,
                "workflow_version": "lidl-family-weekly-one-shot-v1",
                "result": "WAIT_SOURCE",
                "reason": "exact_source_not_archived_in_immutable_corpus",
                "target": "current",
                "today_berlin": "2026-08-06",
                "source": {
                    "route_region": "21",
                    "valid_from": "2026-08-03",
                    "valid_until": "2026-08-08",
                    "pdf_sha256": pdf_sha,
                    "raw_sha256": raw_sha,
                    "page_count": 69,
                    "readiness": {
                        "state": "SOURCE_AVAILABLE",
                        "reason": "source_payload_usable",
                        "page_count": 69,
                    },
                },
                "corpus_match": None,
                "dry_run": True,
                "corpus_write": False,
                "db_write": False,
                "review_seed": False,
                "auto_approve": False,
                "auto_publish": False,
                "systemd_change": False,
            },
        )
        request = "\n".join(
            [
                "runner_version=lidl-weekly-gate-a-rpi5-v01",
                (
                    "registered_commit="
                    "805006b884e4234eda89beb27da839793e68db2d"
                ),
                "registered_image_id=sha256:" + "4" * 64,
                "target=current",
                "as_of=2026-08-06",
                "use_previous=false",
                "previous_manifest=none",
                f"corpus_root={self.corpus_root}",
                "production_database_write=false",
                "review_write=false",
                "production_publish=false",
                "production_deploy=false",
                "systemd_change=false",
                "",
            ]
        )
        (self.run_dir / "run-request.txt").write_text(
            request,
            encoding="utf-8",
        )

    def plan(self) -> dict[str, object]:
        return MODULE.build_freeze_plan(
            gate_a_run_dir=self.run_dir,
            evidence_root=self.evidence_root,
            corpus_root=self.corpus_root,
        )

    def test_valid_wait_source_evidence_produces_plan_only_result(self) -> None:
        plan = self.plan()
        self.assertEqual(plan["result"], "READY_TO_FREEZE")
        self.assertEqual(plan["source"]["pdf_sha256"], self.pdf_sha)
        self.assertEqual(plan["source"]["raw_sha256"], self.raw_sha)
        self.assertRegex(plan["plan_fingerprint"], r"^[0-9a-f]{64}$")
        self.assertTrue(plan["safety"]["plan_only"])
        self.assertFalse(plan["safety"]["corpus_write_authorized"])
        self.assertFalse(plan["safety"]["database_write_authorized"])
        self.assertTrue(
            plan["apply_contract"]["separate_owner_authorization_required"]
        )
        self.assertFalse(Path(plan["destination"]["flyer_dir"]).exists())

    def test_plan_is_byte_deterministic(self) -> None:
        self.assertEqual(canonical_bytes(self.plan()), canonical_bytes(self.plan()))

    def test_tampered_pdf_fails_closed(self) -> None:
        (self.family_root / "source.pdf").write_bytes(b"tampered")
        with self.assertRaisesRegex(
            MODULE.LidlGateBFreezePlanError,
            "source PDF SHA mismatch",
        ):
            self.plan()

    def test_unsafe_gate_a_flag_fails_closed(self) -> None:
        path = self.run_dir / "controller" / "controller-manifest.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["corpus_write_authorized"] = True
        self._write_json(path, payload)
        with self.assertRaisesRegex(
            MODULE.LidlGateBFreezePlanError,
            "controller safety mismatch",
        ):
            self.plan()

    def test_non_wait_source_result_fails_closed(self) -> None:
        path = self.run_dir / "controller" / "controller-manifest.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["result"] = "READY"
        self._write_json(path, payload)
        with self.assertRaisesRegex(
            MODULE.LidlGateBFreezePlanError,
            "Gate A result is not WAIT",
        ):
            self.plan()

    def test_existing_exact_source_fails_closed(self) -> None:
        existing = self.flyers_root / "existing-family"
        existing.mkdir()
        (existing / "source.pdf").write_bytes(self.source_pdf)
        (existing / "source.json").write_bytes(self.source_json)
        with self.assertRaisesRegex(
            MODULE.LidlGateBFreezePlanError,
            "exact source PDF is already frozen",
        ):
            self.plan()

    def test_existing_destination_fails_closed(self) -> None:
        destination = (
            self.flyers_root
            / "aktionsprospekt-03-08-2026-08-08-2026-a1b2c3"
        )
        destination.mkdir()
        with self.assertRaisesRegex(
            MODULE.LidlGateBFreezePlanError,
            "planned corpus destination already exists",
        ):
            self.plan()

    def test_symlinked_source_evidence_fails_closed(self) -> None:
        source = self.family_root / "source.pdf"
        original = self.family_root / "source-real.pdf"
        source.rename(original)
        source.symlink_to(original)
        with self.assertRaisesRegex(
            MODULE.LidlGateBFreezePlanError,
            "unsafe or missing file",
        ):
            self.plan()

    def test_stable_identity_mismatch_fails_closed(self) -> None:
        path = self.family_root / "meta.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["official_flyer_id"] = "wrong"
        self._write_json(path, payload)
        with self.assertRaisesRegex(
            MODULE.LidlGateBFreezePlanError,
            "official flyer ID mismatch",
        ):
            self.plan()


if __name__ == "__main__":
    unittest.main()
