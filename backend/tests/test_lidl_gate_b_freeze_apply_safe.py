from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "lidl_gate_b_freeze_apply_safe.py"
SPEC = importlib.util.spec_from_file_location("lidl_gate_b_freeze_apply_safe", TOOL)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class LidlGateBFreezeApplySafeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.flyers_root = self.root / "flyers"
        self.flyers_root.mkdir(mode=0o700)
        self.pdf = b"%PDF-1.7\nexact-gate-b-source\n"
        self.raw = json.dumps(
            {
                "flyer": {
                    "id": "019fa95c-4c2d-704c-a2ad-cfe2c622c4e8",
                    "flyerUrlAbsolute": (
                        "https://www.lidl.de/l/prospekte/"
                        "aktionsprospekt-03-08-2026-08-08-2026-b1cf3b/ar/21"
                    ),
                    "hiResPdfUrl": (
                        "https://endpoints.leaflets.schwarz/leaflets/pdfs/"
                        "019fa95c-4c2d-704c-a2ad-cfe2c622c4e8/source.pdf"
                    ),
                    "offerStartDate": "2026-08-03",
                    "offerEndDate": "2026-08-08",
                    "regions": [{"code": "21"}, {"code": "42"}, {"code": "7"}],
                    "pages": [{"number": value} for value in range(1, 70)],
                }
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.pdf_sha = sha256(self.pdf).hexdigest()
        self.identity = MODULE.plan_module._stable_source_identity(self.raw)
        MODULE.restore_original_filter()

    def tearDown(self) -> None:
        MODULE.restore_original_filter()
        self.temp.cleanup()

    def _write_staging(self, directory: Path) -> None:
        directory.mkdir(mode=0o700)
        files = {
            "source.pdf": self.pdf,
            "source.json": self.raw,
            "discovery-meta.json": b'{"source":"test"}\n',
        }
        for name, content in files.items():
            path = directory / name
            path.write_bytes(content)
            path.chmod(0o600)

    def test_exact_active_private_staging_is_forwarded_to_current_planner(self) -> None:
        staging = self.flyers_root / ".gate-b-freeze-7517c52e27c6f661.staging"
        self._write_staging(staging)
        MODULE.install_safe_staging_filter()
        MODULE.plan_module._corpus_identity_conflicts(
            self.flyers_root,
            source_pdf_sha256=self.pdf_sha,
            stable_identity=self.identity,
            active_private_staging=staging,
        )

    def test_staging_is_not_ignored_without_exact_active_path(self) -> None:
        staging = self.flyers_root / ".gate-b-freeze-7517c52e27c6f661.staging"
        self._write_staging(staging)
        MODULE.install_safe_staging_filter()
        with self.assertRaisesRegex(
            MODULE.plan_module.LidlGateBFreezePlanError,
            "exact source PDF is already frozen",
        ):
            MODULE.plan_module._corpus_identity_conflicts(
                self.flyers_root,
                source_pdf_sha256=self.pdf_sha,
                stable_identity=self.identity,
            )

    def test_active_private_staging_with_non_private_mode_fails_closed(self) -> None:
        staging = self.flyers_root / ".gate-b-freeze-7517c52e27c6f661.staging"
        self._write_staging(staging)
        os.chmod(staging, 0o755)
        MODULE.install_safe_staging_filter()
        with self.assertRaisesRegex(
            MODULE.plan_module.LidlGateBFreezePlanError,
            "active private staging mode mismatch",
        ):
            MODULE.plan_module._corpus_identity_conflicts(
                self.flyers_root,
                source_pdf_sha256=self.pdf_sha,
                stable_identity=self.identity,
                active_private_staging=staging,
            )

    def test_symlinked_active_private_staging_fails_closed(self) -> None:
        target = self.root / "outside-staging"
        self._write_staging(target)
        staging = self.flyers_root / ".gate-b-freeze-7517c52e27c6f661.staging"
        staging.symlink_to(target, target_is_directory=True)
        MODULE.install_safe_staging_filter()
        with self.assertRaisesRegex(
            MODULE.plan_module.LidlGateBFreezePlanError,
            "corpus child is a symlink",
        ):
            MODULE.plan_module._corpus_identity_conflicts(
                self.flyers_root,
                source_pdf_sha256=self.pdf_sha,
                stable_identity=self.identity,
                active_private_staging=staging,
            )

    def test_safe_entrypoint_patches_apply_replan_dependency(self) -> None:
        MODULE.install_safe_staging_filter()
        self.assertIs(
            MODULE.plan_module._corpus_identity_conflicts,
            MODULE._validated_corpus_identity_conflicts,
        )
        self.assertIs(
            MODULE.apply_module.build_freeze_plan,
            MODULE.plan_module.build_freeze_plan,
        )
        self.assertEqual(MODULE.SAFE_APPLY_VERSION, "lidl-gate-b-freeze-apply-safe-v1")


if __name__ == "__main__":
    unittest.main()
