from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import pwd
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
for path in (ROOT / "backend", TOOLS, TOOLS / "lidl_parser_provenance"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

FIXTURE_PATH = ROOT / "backend" / "tests" / "test_lidl_gate_b_freeze_plan.py"
FIXTURE_SPEC = importlib.util.spec_from_file_location(
    "lidl_gate_b_freeze_plan_fixture_for_apply",
    FIXTURE_PATH,
)
assert FIXTURE_SPEC and FIXTURE_SPEC.loader
FIXTURE = importlib.util.module_from_spec(FIXTURE_SPEC)
sys.modules[FIXTURE_SPEC.name] = FIXTURE
FIXTURE_SPEC.loader.exec_module(FIXTURE)

APPLY_PATH = TOOLS / "lidl_gate_b_freeze_apply.py"
APPLY_SPEC = importlib.util.spec_from_file_location(
    "lidl_gate_b_freeze_apply_real_planner",
    APPLY_PATH,
)
assert APPLY_SPEC and APPLY_SPEC.loader
APPLY = importlib.util.module_from_spec(APPLY_SPEC)
sys.modules[APPLY_SPEC.name] = APPLY
APPLY_SPEC.loader.exec_module(APPLY)


class LidlGateBFreezeApplyRealPlannerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = FIXTURE.LidlGateBFreezePlanTest(methodName="runTest")
        self.fixture.setUp()
        self.fixture._write_base_revision()
        self.plan = self.fixture.plan()
        self.authorization = self.fixture.root / "real-planner-authorization.json"
        self.uid = os.geteuid()
        self.gid = os.getegid()
        self.authorized_by = pwd.getpwuid(self.uid).pw_name
        payload = {
            "schema_version": 1,
            "authorization_version": "lidl-gate-b-freeze-authorization-v1",
            "action": "freeze_exact_gate_a_source",
            "authorized_by": self.authorized_by,
            "authorization_nonce": "c" * 64,
            "plan_fingerprint": self.plan["plan_fingerprint"],
            "issued_for_commit": self.plan["gate_a"]["registered_commit"],
            "gate_a_run_dir": self.plan["gate_a"]["run_dir"],
            "destination": self.plan["destination"]["flyer_dir"],
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
        self.authorization.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.authorization.chmod(0o600)

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def test_real_planner_replan_does_not_treat_own_staging_as_frozen(self) -> None:
        destination = Path(self.plan["destination"]["flyer_dir"])
        staging = self.fixture.flyers_root / (
            ".gate-b-freeze-"
            + self.plan["plan_fingerprint"][:16]
            + ".staging"
        )

        receipt = APPLY.apply_freeze(
            gate_a_run_dir=self.fixture.run_dir,
            evidence_root=self.fixture.evidence_root,
            corpus_root=self.fixture.corpus_root,
            expected_plan_fingerprint=self.plan["plan_fingerprint"],
            authorization_file=self.authorization,
            expected_uid=self.uid,
            expected_gid=self.gid,
            authorized_by=self.authorized_by,
        )

        self.assertEqual(receipt["result"], "FROZEN")
        self.assertFalse(staging.exists())
        self.assertTrue(destination.is_dir())
        self.assertEqual(
            {path.name for path in destination.iterdir()},
            {
                "source.pdf",
                "source.json",
                "discovery-meta.json",
                "gate-b-freeze-receipt.json",
            },
        )
        self.assertEqual(
            (destination / "source.pdf").read_bytes(),
            self.fixture.source_pdf,
        )
        self.assertEqual(
            (destination / "source.json").read_bytes(),
            self.fixture.source_json,
        )
        self.assertTrue(receipt["safety"]["corpus_write_performed"])
        self.assertFalse(receipt["safety"]["parser_scan_performed"])
        self.assertFalse(receipt["safety"]["database_write_performed"])
        self.assertFalse(receipt["safety"]["review_write_performed"])
        self.assertFalse(receipt["safety"]["production_publish_performed"])
        self.assertFalse(receipt["safety"]["production_deploy_performed"])
        self.assertFalse(receipt["safety"]["systemd_change_performed"])

        with self.assertRaises(FIXTURE.MODULE.LidlGateBFreezePlanError):
            self.fixture.plan()

    def test_wrong_fingerprint_staging_is_not_ignored(self) -> None:
        staging = self.fixture.flyers_root / ".gate-b-freeze-0123456789abcdef.staging"
        staging.mkdir(mode=0o700)
        for source_name, destination_name in (
            ("source.pdf", "source.pdf"),
            ("source.json", "source.json"),
            ("meta.json", "discovery-meta.json"),
        ):
            source = self.fixture.family_root / source_name
            destination = staging / destination_name
            destination.write_bytes(source.read_bytes())
            destination.chmod(0o600)

        with self.assertRaisesRegex(
            FIXTURE.MODULE.LidlGateBFreezePlanError,
            "exact source PDF is already frozen",
        ):
            self.fixture.plan()


if __name__ == "__main__":
    unittest.main()
