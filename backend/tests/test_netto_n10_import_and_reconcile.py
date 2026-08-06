from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "netto_n10_import_and_reconcile.py"
SPEC = importlib.util.spec_from_file_location(
    "netto_n10_import_and_reconcile",
    TOOL,
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class NettoN10ImportAndReconcileTest(unittest.TestCase):
    def first_review(self) -> dict[str, object]:
        rows = []
        for index in range(100):
            campaign = "hz31_hasb_4" if index < 26 else "hz32_hasb"
            rows.append(
                {
                    "cell_id": f"cell-{index:03d}",
                    "campaign_id": campaign,
                    "page_number": 14 if index < 26 else 37,
                    "visual_index": index,
                    "expected_title_first_pass": f"Product {index}",
                    "expected_price_eur_first_pass": f"{index + 1}.90",
                    "title_verdict": "provisional_correct",
                    "price_verdict": "provisional_correct",
                }
            )
        return {
            "source_archive_sha256": (
                MODULE.RECONCILIATION.EXPECTED_SOURCE_ARCHIVE_SHA256
            ),
            "source_fixture_manifest_sha256": (
                MODULE.EXPECTED_N9_FIXTURE_MANIFEST_SHA256
            ),
            "page_count": 17,
            "cell_count": 100,
            "campaign_cell_counts": {"hz31_hasb_4": 26, "hz32_hasb": 74},
            "review_only_default": True,
            "automatic_approval_enabled": False,
            "automatic_publish_enabled": False,
            "database_write_performed": False,
            "deployment_performed": False,
            "production_apply_authorized": False,
            "rows": rows,
        }

    def second_review(self) -> dict[str, object]:
        rows = []
        for index in range(100):
            campaign = "hz31_hasb_4" if index < 26 else "hz32_hasb"
            rows.append(
                {
                    "cell_id": f"cell-{index:03d}",
                    "publication_slug": campaign,
                    "page_number": 14 if index < 26 else 37,
                    "visual_index": index + 1,
                    "expected_title": f"Product {index}",
                    "expected_primary_price_eur": f"{index + 1}.90",
                    "visual_verdict": "visually_coherent_target_candidate",
                    "automatic_approval_allowed": False,
                    "automatic_publish_allowed": False,
                }
            )
        return {
            "source_n9_fixture_manifest_sha256": (
                MODULE.EXPECTED_N9_FIXTURE_MANIFEST_SHA256
            ),
            "reviewed_page_count": 17,
            "reviewed_cell_count": 100,
            "target_or_review_cell_count": 98,
            "scope_control_count": 2,
            "automatic_approval": False,
            "automatic_publish": False,
            "production_write_performed": False,
            "cell_reviews": rows,
        }

    @staticmethod
    def encoded(payload: dict[str, object]) -> bytes:
        return (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n"
        ).encode("utf-8")

    def write_inputs(self, root: Path) -> tuple[Path, Path, bytes]:
        first_path = root / "first.json"
        ledger_path = root / "ledger.json"
        ledger_bytes = self.encoded(self.second_review())
        first_path.write_bytes(self.encoded(self.first_review()))
        ledger_path.write_bytes(ledger_bytes)
        return first_path, ledger_path, ledger_bytes

    def run_import(
        self,
        root: Path,
        *,
        ledger_path: Path | None = None,
        builder_path: Path | None = None,
        ledger_bytes: bytes,
    ) -> dict[str, object]:
        first_path = root / "first.json"
        if not first_path.exists():
            first_path.write_bytes(self.encoded(self.first_review()))
        return MODULE.import_and_reconcile(
            first_review_path=first_path,
            ledger_path=ledger_path,
            builder_script_path=builder_path,
            import_destination=root / "imported.json",
            report_destination=root / "report.json",
            expected_ledger_sha256=sha256(ledger_bytes).hexdigest(),
            expected_ledger_size=len(ledger_bytes),
        )

    def test_direct_ledger_import_is_exact_and_idempotent(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, ledger_path, ledger_bytes = self.write_inputs(root)

            first = self.run_import(
                root,
                ledger_path=ledger_path,
                ledger_bytes=ledger_bytes,
            )
            second = self.run_import(
                root,
                ledger_path=ledger_path,
                ledger_bytes=ledger_bytes,
            )

            self.assertEqual(first["import_state"], "created")
            self.assertEqual(first["report_state"], "created")
            self.assertEqual(second["import_state"], "unchanged")
            self.assertEqual(second["report_state"], "unchanged")
            self.assertEqual((root / "imported.json").read_bytes(), ledger_bytes)

            report = json.loads((root / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["imported_ledger_size"], len(ledger_bytes))
            self.assertEqual(report["reconciliation"]["identity_match_count"], 100)
            self.assertEqual(report["reconciliation"]["row_disagreement_count"], 0)
            self.assertFalse(report["reconciliation"]["promotion_ready"])
            self.assertFalse(report["safety"]["automatic_approval_enabled"])
            self.assertFalse(report["safety"]["automatic_publish_enabled"])
            self.assertFalse(report["safety"]["database_write_performed"])
            self.assertFalse(report["safety"]["deployment_performed"])

    def test_builder_heredoc_source_is_supported(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_bytes = self.encoded(self.second_review())
            (root / "first.json").write_bytes(self.encoded(self.first_review()))
            builder = root / "builder.sh"
            builder.write_bytes(
                b"#!/usr/bin/env bash\n"
                + MODULE.BUILDER_START_MARKER
                + b"\n"
                + ledger_bytes
                + MODULE.BUILDER_END_MARKER
                + b"\n"
            )

            result = self.run_import(
                root,
                builder_path=builder,
                ledger_bytes=ledger_bytes,
            )

            self.assertEqual(result["import_state"], "created")
            self.assertEqual((root / "imported.json").read_bytes(), ledger_bytes)

    def test_wrong_sha_fails_before_any_output(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, ledger_path, ledger_bytes = self.write_inputs(root)

            with self.assertRaisesRegex(MODULE.N10ImportError, "SHA256 mismatch"):
                MODULE.import_and_reconcile(
                    first_review_path=root / "first.json",
                    ledger_path=ledger_path,
                    import_destination=root / "imported.json",
                    report_destination=root / "report.json",
                    expected_ledger_sha256="0" * 64,
                    expected_ledger_size=len(ledger_bytes),
                )

            self.assertFalse((root / "imported.json").exists())
            self.assertFalse((root / "report.json").exists())

    def test_unsafe_ledger_fails_before_any_output(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            unsafe = self.second_review()
            unsafe["automatic_publish"] = True
            ledger_bytes = self.encoded(unsafe)
            ledger_path = root / "ledger.json"
            ledger_path.write_bytes(ledger_bytes)
            (root / "first.json").write_bytes(self.encoded(self.first_review()))

            with self.assertRaisesRegex(
                MODULE.N10ImportError,
                "automatic_publish must be false",
            ):
                self.run_import(
                    root,
                    ledger_path=ledger_path,
                    ledger_bytes=ledger_bytes,
                )

            self.assertFalse((root / "imported.json").exists())
            self.assertFalse((root / "report.json").exists())

    def test_conflicting_report_blocks_import_prewrite(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, ledger_path, ledger_bytes = self.write_inputs(root)
            (root / "report.json").write_text("conflict\n", encoding="utf-8")

            with self.assertRaisesRegex(
                MODULE.N10ImportError,
                "existing reconciliation report destination differs",
            ):
                self.run_import(
                    root,
                    ledger_path=ledger_path,
                    ledger_bytes=ledger_bytes,
                )

            self.assertFalse((root / "imported.json").exists())
            self.assertEqual(
                (root / "report.json").read_text(encoding="utf-8"),
                "conflict\n",
            )

    def test_symlink_source_is_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, ledger_path, ledger_bytes = self.write_inputs(root)
            link = root / "ledger-link.json"
            link.symlink_to(ledger_path)

            with self.assertRaisesRegex(
                MODULE.N10ImportError,
                "N10 ledger must be a regular file",
            ):
                self.run_import(
                    root,
                    ledger_path=link,
                    ledger_bytes=ledger_bytes,
                )

    def test_duplicate_builder_heredoc_is_rejected(self) -> None:
        ledger_bytes = self.encoded(self.second_review())
        block = (
            MODULE.BUILDER_START_MARKER
            + b"\n"
            + ledger_bytes
            + MODULE.BUILDER_END_MARKER
            + b"\n"
        )
        with self.assertRaisesRegex(
            MODULE.N10ImportError,
            "exactly one N10 ledger heredoc",
        ):
            MODULE.extract_ledger_from_builder_bytes(block + block)

    def test_source_selection_must_be_unambiguous(self) -> None:
        with self.assertRaisesRegex(
            MODULE.N10ImportError,
            "provide exactly one",
        ):
            MODULE.load_source_ledger_bytes()


if __name__ == "__main__":
    unittest.main()
