from __future__ import annotations

import csv
from hashlib import sha256
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = ROOT / "tools" / "aldi_a30_frozen_acquisition.py"
SPEC = importlib.util.spec_from_file_location(
    "aldi_a30_frozen_acquisition",
    TOOL_PATH,
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _write_tsv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def _prospect_links() -> dict[str, object]:
    result: dict[str, object] = {}
    for source_key, count, week in (
        ("prospect-current", 49, "2026cw31"),
        ("prospect-preview", 41, "2026cw32"),
    ):
        magazine = (
            "https://magazine.aldi-nord.de/aldi-nord/aldi-aktuell/"
            f"2026/{week}-fixture/"
        )
        base = f"https://ipaper.ipapercms.dk/aldi/{week}/fixture/"
        result[source_key] = {
            "all_urls": [
                magazine,
                *[
                    f"{base}Image.ashx?PageNumber={page}"
                    for page in range(1, count + 1)
                ],
            ]
        }
    return result


class AldiA30ArchiveTest(unittest.TestCase):
    def test_exact_archive_manifest_and_projection_are_verified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source" / "fixture-root"
            reports = source / "reports"
            nested = source / "input" / "baseline" / "reports"
            reports.mkdir(parents=True)
            nested.mkdir(parents=True)
            projection = reports / "a21-adjudicated-projection.jsonl"
            projection.write_text('{"source_offer_id":"1"}\n', encoding="utf-8")
            summary = reports / "a21-summary.json"
            summary.write_text(
                json.dumps(
                    {
                        "projection_rows": 1,
                        "scope_counts": {
                            "in_scope": 1,
                            "out_of_scope": 0,
                            "review": 0,
                        },
                        "publication_counts": {
                            "auto_candidate": 1,
                            "blocked_out_of_scope": 0,
                            "review_required": 0,
                        },
                    }
                ),
                encoding="utf-8",
            )
            links = nested / "prospect-links.json"
            links.write_text(json.dumps(_prospect_links()), encoding="utf-8")
            manifest = source / "manifest.sha256"
            manifest.write_text(
                "\n".join(
                    f"{sha256(path.read_bytes()).hexdigest()}  "
                    f"{path.relative_to(source).as_posix()}"
                    for path in (projection, summary, links)
                )
                + "\n",
                encoding="utf-8",
            )
            archive = root / "a21.tar.gz"
            with tarfile.open(archive, "w:gz") as bundle:
                bundle.add(source, arcname=source.name)

            old_rows = MODULE.EXPECTED_A21_ROWS
            old_scope = MODULE.EXPECTED_SCOPE_COUNTS
            old_publication = MODULE.EXPECTED_PUBLICATION_COUNTS
            MODULE.EXPECTED_A21_ROWS = 1
            MODULE.EXPECTED_SCOPE_COUNTS = {
                "in_scope": 1,
                "out_of_scope": 0,
                "review": 0,
            }
            MODULE.EXPECTED_PUBLICATION_COUNTS = {
                "auto_candidate": 1,
                "blocked_out_of_scope": 0,
                "review_required": 0,
            }
            try:
                extracted, report = MODULE.verify_a21_archive(
                    archive,
                    root / "extract",
                    expected_archive_sha256=sha256(archive.read_bytes()).hexdigest(),
                    expected_projection_sha256=sha256(
                        projection.read_bytes()
                    ).hexdigest(),
                )
            finally:
                MODULE.EXPECTED_A21_ROWS = old_rows
                MODULE.EXPECTED_SCOPE_COUNTS = old_scope
                MODULE.EXPECTED_PUBLICATION_COUNTS = old_publication

            self.assertTrue((extracted / "manifest.sha256").is_file())
            self.assertEqual(report["projection_rows"], 1)
            plan = MODULE.derive_source_plan(extracted)
            self.assertEqual(plan["total_expected_pages"], 90)
            self.assertFalse(plan["viewer_html_required_for_parity"])

    def test_archive_parent_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "unsafe.tar.gz"
            with tarfile.open(archive, "w:gz") as bundle:
                info = tarfile.TarInfo("../escape.txt")
                data = b"escape"
                info.size = len(data)
                bundle.addfile(info, io.BytesIO(data))
            with self.assertRaisesRegex(MODULE.AldiA30Error, "unsafe"):
                MODULE.verify_a21_archive(
                    archive,
                    root / "extract",
                    expected_archive_sha256=sha256(
                        archive.read_bytes()
                    ).hexdigest(),
                )


class AldiA30CapabilityTest(unittest.TestCase):
    def test_expired_viewers_are_advisory_when_attempt_set_is_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "viewer.tsv"
            rows = [
                {
                    "label": label,
                    "viewer_kind": kind,
                    "url": f"https://example.invalid/{label}/{kind}",
                    "transport_ok": "true",
                    "http_ok": "false",
                    "http_code": "404",
                    "content_type": "text/html",
                    "sha256": "a" * 64,
                    "bytes": "100",
                }
                for label in ("current", "preview")
                for kind in ("magazine", "ipaper")
            ]
            _write_tsv(
                path,
                [
                    "label",
                    "viewer_kind",
                    "url",
                    "transport_ok",
                    "http_ok",
                    "http_code",
                    "content_type",
                    "sha256",
                    "bytes",
                ],
                rows,
            )
            report = MODULE.validate_viewer_attempts(path)
        self.assertEqual(report["attempt_count"], 4)
        self.assertEqual(report["http_ok_count"], 0)
        self.assertFalse(report["expired_viewer_is_fatal"])
        self.assertFalse(report["viewer_html_required_for_parity"])

    def test_all_90_frozen_page_images_are_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pages.json"
            rows = [
                {
                    "label": label,
                    "page_number": page,
                    "format": "jpeg",
                    "bytes": 50_000,
                    "sha256": sha256(
                        f"{label}:{page}".encode("utf-8")
                    ).hexdigest(),
                }
                for label, count in MODULE.EXPECTED_PAGE_COUNTS.items()
                for page in range(1, count + 1)
            ]
            path.write_text(json.dumps({"rows": rows}), encoding="utf-8")
            report = MODULE.validate_page_images(path)
            self.assertEqual(report["total_images"], 90)
            self.assertEqual(
                report["counts_by_label"],
                {"current": 49, "preview": 41},
            )

            path.write_text(json.dumps({"rows": rows[:-1]}), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.AldiA30Error, "incomplete"):
                MODULE.validate_page_images(path)

    def test_acquisition_passes_without_pdf_or_viewer_but_matcher_stays_blocked(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf_attempts = root / "pdf.tsv"
            _write_tsv(
                pdf_attempts,
                [
                    "label",
                    "candidate_index",
                    "url",
                    "http_ok",
                    "pdf_magic",
                    "selected",
                    "sha256",
                    "bytes",
                ],
                [
                    {
                        "label": label,
                        "candidate_index": index,
                        "url": f"https://example.invalid/{label}/{index}.pdf",
                        "http_ok": "false",
                        "pdf_magic": "false",
                        "selected": "false",
                        "sha256": "",
                        "bytes": "0",
                    }
                    for label in ("current", "preview")
                    for index in (1, 2)
                ],
            )
            text_summary = root / "text.json"
            text_summary.write_text(
                json.dumps({"backend": "none", "documents": {}}),
                encoding="utf-8",
            )
            summary = MODULE.build_capability_summary(
                a21={
                    "projection_sha256": MODULE.EXPECTED_A21_PROJECTION_SHA256,
                    "projection_rows": 519,
                    "scope_counts": MODULE.EXPECTED_SCOPE_COUNTS,
                    "publication_counts": MODULE.EXPECTED_PUBLICATION_COUNTS,
                },
                source_plan={"total_expected_pages": 90},
                viewers={"attempt_count": 4, "http_ok_count": 0},
                images={
                    "total_images": 90,
                    "counts_by_label": {"current": 49, "preview": 41},
                },
                pdf_attempts_path=pdf_attempts,
                pdf_text_summary_path=text_summary,
            )
        self.assertEqual(summary["result"], "pass")
        self.assertTrue(summary["acquisition_gate_passed"])
        self.assertFalse(summary["parity_matcher_ready"])
        self.assertFalse(summary["viewer_html_required_for_parity"])
        self.assertIn("image-assisted text recovery", summary["next_gate"])
        self.assertFalse(summary["production_apply_authorized"])
        self.assertFalse(summary["database_write_performed"])
        self.assertFalse(summary["deployment_performed"])


class AldiA30StaticContractTest(unittest.TestCase):
    def test_runner_separates_advisory_viewer_from_required_page_assets(self) -> None:
        text = (
            ROOT / "tools" / "run-hermes-deals-aldi-a30-acquisition-v02.sh"
        ).read_text(encoding="utf-8")
        probe = text.split("probe_viewer() {", 1)[1].split("fetch_required() {", 1)[0]
        required = text.split("fetch_required() {", 1)[1].split(
            "printf 'label\\tviewer_kind", 1
        )[0]
        self.assertNotIn("--fail", probe)
        self.assertIn("--fail", required)
        self.assertIn("viewer_html_required=false", text)
        self.assertIn("expired/unavailable viewer is non-fatal", text)
        self.assertIn(
            "hermes-deals-aldi-a21-20260801T100533Z.tar.gz",
            text,
        )

    def test_runner_has_no_production_or_database_actions(self) -> None:
        text = (
            ROOT / "tools" / "run-hermes-deals-aldi-a30-acquisition-v02.sh"
        ).read_text(encoding="utf-8")
        self.assertNotIn("docker", text)
        self.assertNotIn("psql", text)
        self.assertNotIn("systemctl", text)
        self.assertNotIn("git commit", text)
        self.assertNotIn("git push", text)
        self.assertIn("production_database_write=false", text)
        self.assertIn("production_deploy=false", text)


if __name__ == "__main__":
    unittest.main()
