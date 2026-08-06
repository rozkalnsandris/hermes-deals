from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import pwd
import stat
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "lidl_gate_b_freeze_apply.py"
SPEC = importlib.util.spec_from_file_location("lidl_gate_b_freeze_apply", TOOL)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def canonical_bytes(payload: dict[str, object]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


class LidlGateBFreezeApplyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.evidence_root = self.root / "gate-a-evidence"
        self.run_dir = self.evidence_root / "lidl-gate-a-20260806T133221Z"
        self.corpus_root = self.root / "corpus"
        self.flyers_root = self.corpus_root / "flyers"
        self.source_root = self.root / "source"
        for path in (
            self.run_dir,
            self.flyers_root,
            self.source_root,
        ):
            path.mkdir(parents=True)
        self.uid = os.geteuid()
        self.gid = os.getegid()
        self.authorized_by = pwd.getpwuid(self.uid).pw_name
        self.fingerprint = "a" * 64
        self.commit = "8" * 40
        self.destination = self.flyers_root / "weekly-family"
        self.sources = {
            "source.pdf": b"%PDF-1.7\nweekly-family\n",
            "source.json": b'{"flyer":{"id":"1"}}\n',
            "meta.json": b'{"target":"current"}\n',
        }
        for name, payload in self.sources.items():
            (self.source_root / name).write_bytes(payload)
        self.plan = self._plan()
        self.authorization = self.root / "authorization.json"
        self._write_authorization()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _plan(self) -> dict[str, object]:
        file_rows = []
        destinations = {
            "source.pdf": "source.pdf",
            "source.json": "source.json",
            "meta.json": "discovery-meta.json",
        }
        for name, payload in self.sources.items():
            file_rows.append(
                {
                    "name": name,
                    "source": str(self.source_root / name),
                    "destination": str(self.destination / destinations[name]),
                    "bytes": len(payload),
                    "sha256": sha256(payload).hexdigest(),
                }
            )
        return {
            "schema_version": 1,
            "plan_version": "lidl-gate-b-freeze-plan-v1",
            "result": "READY_TO_FREEZE",
            "reason": "validated_gate_a_wait_source_evidence",
            "plan_fingerprint": self.fingerprint,
            "gate_a": {
                "run_dir": str(self.run_dir),
                "registered_commit": self.commit,
                "registered_image_id": "sha256:" + "4" * 64,
                "target": "current",
                "as_of": "2026-08-06",
                "result": "WAIT",
                "reason": "one_shot_wait_source",
                "one_shot_result": "WAIT_SOURCE",
                "one_shot_reason": "exact_source_not_archived_in_immutable_corpus",
            },
            "source": {
                "flyer_key": "weekly-family",
                "route_region": "21",
                "valid_from": "2026-08-03",
                "valid_until": "2026-08-08",
                "official_flyer_id": "1",
                "page_count": 69,
                "pdf_sha256": sha256(self.sources["source.pdf"]).hexdigest(),
                "raw_sha256": sha256(self.sources["source.json"]).hexdigest(),
                "stable_source_identity": {"official_flyer_id": "1"},
                "stable_source_identity_sha256": "b" * 64,
            },
            "destination": {
                "flyer_dir": str(self.destination),
                "must_not_exist": True,
                "files": file_rows,
            },
            "apply_contract": {
                "mode": "exclusive_create_only",
                "required_owner": "andris:andris",
                "directory_mode": "0700",
                "file_mode": "0600",
                "post_copy_sha256_verification_required": True,
                "rollback_before_commit": "remove_private_staging_only",
                "separate_owner_authorization_required": True,
            },
            "safety": {
                "plan_only": True,
                "corpus_write_authorized": False,
                "database_write_authorized": False,
                "review_write_authorized": False,
                "production_publish_authorized": False,
                "production_deploy_authorized": False,
                "systemd_change_authorized": False,
                "bounded_retry_authorized": False,
            },
        }

    def _authorization_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "authorization_version": "lidl-gate-b-freeze-authorization-v1",
            "action": "freeze_exact_gate_a_source",
            "authorized_by": self.authorized_by,
            "authorization_nonce": "c" * 64,
            "plan_fingerprint": self.fingerprint,
            "issued_for_commit": self.commit,
            "gate_a_run_dir": str(self.run_dir),
            "destination": str(self.destination),
            "source_pdf_sha256": self.plan["source"]["pdf_sha256"],
            "source_raw_sha256": self.plan["source"]["raw_sha256"],
            "corpus_write_authorized": True,
            "parser_scan_authorized": False,
            "database_write_authorized": False,
            "review_write_authorized": False,
            "production_publish_authorized": False,
            "production_deploy_authorized": False,
            "systemd_change_authorized": False,
            "automatic_retry_authorized": False,
            "gate_c_d_authorized": False,
        }

    def _write_authorization(self, payload: dict[str, object] | None = None) -> None:
        self.authorization.write_bytes(
            canonical_bytes(payload or self._authorization_payload())
        )
        self.authorization.chmod(0o600)

    def apply(self) -> dict[str, object]:
        with mock.patch.object(
            MODULE,
            "build_freeze_plan",
            side_effect=lambda **_: deepcopy(self.plan),
        ):
            return MODULE.apply_freeze(
                gate_a_run_dir=self.run_dir,
                evidence_root=self.evidence_root,
                corpus_root=self.corpus_root,
                expected_plan_fingerprint=self.fingerprint,
                authorization_file=self.authorization,
                expected_uid=self.uid,
                expected_gid=self.gid,
                authorized_by=self.authorized_by,
            )

    def test_exact_authorized_source_is_committed_atomically(self) -> None:
        receipt = self.apply()
        self.assertEqual(receipt["result"], "FROZEN")
        self.assertTrue(self.destination.is_dir())
        self.assertEqual(
            {path.name for path in self.destination.iterdir()},
            {
                "source.pdf",
                "source.json",
                "discovery-meta.json",
                "gate-b-freeze-receipt.json",
            },
        )
        self.assertEqual(stat.S_IMODE(self.destination.stat().st_mode), 0o700)
        for path in self.destination.iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(
            (self.destination / "source.pdf").read_bytes(),
            self.sources["source.pdf"],
        )
        stored_receipt = json.loads(
            (self.destination / "gate-b-freeze-receipt.json").read_text()
        )
        self.assertTrue(stored_receipt["safety"]["corpus_write_performed"])
        self.assertFalse(stored_receipt["safety"]["parser_scan_performed"])
        self.assertFalse(stored_receipt["safety"]["database_write_performed"])
        self.assertFalse(
            any(path.name.endswith(".staging") for path in self.flyers_root.iterdir())
        )

    def test_authorization_fingerprint_drift_fails_closed(self) -> None:
        payload = self._authorization_payload()
        payload["plan_fingerprint"] = "d" * 64
        self._write_authorization(payload)
        with self.assertRaisesRegex(
            MODULE.LidlGateBFreezeApplyError,
            "authorization plan fingerprint mismatch",
        ):
            self.apply()
        self.assertFalse(self.destination.exists())

    def test_unsafe_authorization_flag_fails_closed(self) -> None:
        payload = self._authorization_payload()
        payload["production_deploy_authorized"] = True
        self._write_authorization(payload)
        with self.assertRaisesRegex(
            MODULE.LidlGateBFreezeApplyError,
            "authorization safety mismatch",
        ):
            self.apply()
        self.assertFalse(self.destination.exists())

    def test_authorization_mode_must_be_0600(self) -> None:
        self.authorization.chmod(0o644)
        with self.assertRaisesRegex(
            MODULE.LidlGateBFreezeApplyError,
            "authorization mode must be 0600",
        ):
            self.apply()
        self.assertFalse(self.destination.exists())

    def test_existing_destination_fails_closed(self) -> None:
        self.destination.mkdir()
        with self.assertRaisesRegex(
            MODULE.LidlGateBFreezeApplyError,
            "planned destination already exists",
        ):
            self.apply()

    def test_source_hash_drift_fails_before_commit(self) -> None:
        (self.source_root / "source.pdf").write_bytes(b"tampered")
        with self.assertRaisesRegex(
            MODULE.LidlGateBFreezeApplyError,
            "copied byte count drift|copied SHA256 drift|source byte count drift",
        ):
            self.apply()
        self.assertFalse(self.destination.exists())

    def test_symlinked_source_fails_closed(self) -> None:
        source = self.source_root / "source.pdf"
        target = self.source_root / "actual.pdf"
        source.rename(target)
        source.symlink_to(target)
        with self.assertRaisesRegex(
            MODULE.LidlGateBFreezeApplyError,
            "source path is missing or unsafe",
        ):
            self.apply()
        self.assertFalse(self.destination.exists())

    def test_copy_failure_removes_only_private_staging(self) -> None:
        original = MODULE._copy_exact_file
        calls = 0

        def fail_second(descriptor, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise MODULE.LidlGateBFreezeApplyError("synthetic copy failure")
            return original(descriptor, **kwargs)

        with mock.patch.object(MODULE, "build_freeze_plan", return_value=deepcopy(self.plan)):
            with mock.patch.object(MODULE, "_copy_exact_file", side_effect=fail_second):
                with self.assertRaisesRegex(
                    MODULE.LidlGateBFreezeApplyError,
                    "synthetic copy failure",
                ):
                    MODULE.apply_freeze(
                        gate_a_run_dir=self.run_dir,
                        evidence_root=self.evidence_root,
                        corpus_root=self.corpus_root,
                        expected_plan_fingerprint=self.fingerprint,
                        authorization_file=self.authorization,
                        expected_uid=self.uid,
                        expected_gid=self.gid,
                        authorized_by=self.authorized_by,
                    )
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.flyers_root.iterdir()), [])

    def test_replay_is_blocked_after_first_commit(self) -> None:
        self.apply()
        with self.assertRaisesRegex(
            MODULE.LidlGateBFreezeApplyError,
            "planned destination already exists",
        ):
            self.apply()

    def test_weakened_plan_safety_fails_closed(self) -> None:
        self.plan["safety"]["database_write_authorized"] = True
        with self.assertRaisesRegex(
            MODULE.LidlGateBFreezeApplyError,
            "plan safety mismatch",
        ):
            self.apply()
        self.assertFalse(self.destination.exists())

    def test_rename_noreplace_never_replaces_existing_destination(self) -> None:
        source = self.flyers_root / ".gate-b-freeze-aaaaaaaaaaaaaaaa.staging"
        destination = self.flyers_root / "occupied"
        source.mkdir()
        destination.mkdir()
        with self.assertRaisesRegex(
            MODULE.LidlGateBFreezeApplyError,
            "destination already exists",
        ):
            MODULE._rename_noreplace(source, destination)
        self.assertTrue(source.exists())
        self.assertTrue(destination.exists())


if __name__ == "__main__":
    unittest.main()
