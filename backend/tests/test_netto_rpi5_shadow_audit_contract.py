from __future__ import annotations

from datetime import date
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = ROOT / "tools" / "netto_rpi5_shadow_audit.py"
SPEC = importlib.util.spec_from_file_location("netto_rpi5_shadow_audit", TOOL_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _run(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        list(args),
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def _row(campaign: str, field: str, index: int) -> dict[str, object]:
    value: object = f"value-{index}"
    if field == "price":
        value = "1.99"
    elif field == "validity":
        value = ["2026-08-03", "2026-08-08"]
    return {
        "campaign_id": campaign,
        "field": field,
        "expected": value,
        "predicted": value,
        "classification": "match",
        "page_number": index + 1,
        "card_id": f"{campaign}-{field}-{index}",
        "manifest_sha256": "a" * 64,
        "pdf_sha256": "b" * 64,
        "parser_identity": "netto-parser@test",
        "store_external_id": "5659",
        "scope": "family_primary_netto",
    }


class NettoRpi5ShadowAuditUnitTest(unittest.TestCase):
    def test_extract_row_lists_requires_complete_audit_rows(self) -> None:
        rows = [_row("n25", "title", 0), _row("n26", "title", 1)]
        self.assertEqual(list(MODULE.row_groups({"audit_rows": rows})), [rows])
        self.assertEqual(list(MODULE.row_groups({"rows": [{"field": "title"}]})), [])

    def test_date_pair_supports_direct_and_selected_ranges(self) -> None:
        self.assertEqual(
            MODULE.date_pair({"valid_from": "2026-08-03", "valid_until": "2026-08-08"}),
            ("2026-08-03", "2026-08-08"),
        )
        self.assertEqual(
            MODULE.date_pair(
                {"selected_validity": {"valid_from": "2026-08-10", "valid_until": "2026-08-15"}}
            ),
            ("2026-08-10", "2026-08-15"),
        )

    def test_manifest_candidate_is_bound_to_family_store(self) -> None:
        self.assertTrue(
            MODULE.manifest_candidate(
                {"store_external_id": "5659", "scope": "family_primary_netto", "strategy": "netto_fixture"}
            )
        )
        self.assertFalse(
            MODULE.manifest_candidate(
                {"store_external_id": "6071", "scope": "family_primary_netto"}
            )
        )

    def test_reference_maps_only_legacy_container_raw_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_root = root / "host-raw"
            target = raw_root / "netto" / "store.html"
            target.parent.mkdir(parents=True)
            target.write_text("<html>immutable</html>", encoding="utf-8")
            manifest = raw_root / "netto" / "manifest.json"

            self.assertEqual(
                MODULE.reference(
                    manifest,
                    raw_root,
                    "/data/raw/netto/store.html",
                ),
                target.absolute(),
            )

            arbitrary = Path("/srv/raw/netto/store.html")
            self.assertEqual(
                MODULE.reference(manifest, raw_root, str(arbitrary)),
                arbitrary.absolute(),
            )

            traversal = Path("/data/raw/../etc/passwd")
            self.assertEqual(
                MODULE.reference(manifest, raw_root, str(traversal)),
                traversal.absolute(),
            )

    def test_symlinks_are_not_scanned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "netto.json"
            target.write_text("{}", encoding="utf-8")
            (root / "netto-link.json").symlink_to(target)
            found = list(MODULE.regular_files(root, (".json",), 10, 3))
        self.assertEqual(found, [target])


class NettoRpi5ShadowAuditIntegrationTest(unittest.TestCase):
    def test_full_read_only_fixture_produces_bounded_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            audit_root = root / "audits" / "netto-n25-n26"
            raw_root = root / "raw"
            state_root = root / "state"
            output = root / "output"
            (repo / "tools").mkdir(parents=True)
            (repo / "backend/tests/fixtures/netto").mkdir(parents=True)
            audit_root.mkdir(parents=True)
            raw_root.mkdir(parents=True)
            state_root.mkdir(parents=True)

            for name in (
                "netto_shadow_promotion.py",
                "netto_shadow_gate.py",
                "netto_shadow_weekly.py",
            ):
                shutil.copy2(ROOT / "tools" / name, repo / "tools" / name)
            policy = {
                "basis": {
                    "combined_full_title_rate": 0.754098,
                    "automatic_package_selection_count": 0,
                },
                "promotion_policy": {"production_integration_allowed": False},
                "title_policy": {"route": "review_required"},
                "package_policy": {"route": "review_required"},
            }
            (repo / "backend/tests/fixtures/netto/n25_title_package_review_policy_v1.json").write_text(
                json.dumps(policy), encoding="utf-8"
            )
            _run("git", "init", "-b", "main", cwd=repo)
            _run("git", "config", "user.email", "audit@example.invalid", cwd=repo)
            _run("git", "config", "user.name", "Audit Test", cwd=repo)
            _run("git", "add", ".", cwd=repo)
            _run("git", "commit", "-m", "fixture", cwd=repo)
            expected_head = _run("git", "rev-parse", "HEAD", cwd=repo)

            rows = [
                _row(campaign, field, index)
                for campaign in ("n25", "n26")
                for index, field in enumerate(sorted(MODULE.FIELDS))
            ]
            (audit_root / "immutable-audit-rows.json").write_text(
                json.dumps({"audit_rows": rows}), encoding="utf-8"
            )

            html = raw_root / "store.html"
            pdf = raw_root / "prospect.pdf"
            html.write_bytes(b"<html>Netto store 5659</html>")
            pdf.write_bytes(b"%PDF-1.7\nfixture\n")
            manifest = {
                "strategy": "netto_store_page_plus_current_prospect_pdf_v3",
                "store_external_id": "5659",
                "scope": "family_primary_netto",
                "valid_from": "2026-08-03",
                "valid_until": "2026-08-08",
                "prospect_slug": "hz32_hasb",
                "store_path": "/data/raw/store.html",
                "store_sha256": _sha(html.read_bytes()),
                "prospect_pdf_path": "/data/raw/prospect.pdf",
                "prospect_pdf_sha256": _sha(pdf.read_bytes()),
                "parser_version": "netto-parser@test",
            }
            (raw_root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (state_root / "history.json").write_text(
                json.dumps(
                    [
                        {
                            "campaign_key": "week-31",
                            "action": "run_shadow",
                            "recorded_at": "2026-07-27T06:00:00+00:00",
                            "production_write_authorized": False,
                        },
                        {
                            "campaign_key": "week-32",
                            "action": "write_plan_ready",
                            "recorded_at": "2026-08-03T06:00:00+00:00",
                            "production_write_authorized": False,
                        },
                    ]
                ),
                encoding="utf-8",
            )

            old = os.environ.get("HERMES_AUDIT_TEST_MODE")
            os.environ["HERMES_AUDIT_TEST_MODE"] = "1"
            try:
                summary = MODULE.run_audit(
                    repo=repo,
                    expected_head=expected_head,
                    audit_root=audit_root,
                    raw_root=raw_root,
                    state_root=state_root,
                    output=output,
                    today=date(2026, 8, 4),
                    minimum_samples=1,
                )
            finally:
                if old is None:
                    os.environ.pop("HERMES_AUDIT_TEST_MODE", None)
                else:
                    os.environ["HERMES_AUDIT_TEST_MODE"] = old

            self.assertEqual(summary["result"], "pass")
            self.assertEqual(summary["acceptance_status"], "ready")
            self.assertTrue(summary["issue_27_real_corpus_evidence_ready"])
            self.assertTrue(summary["issue_28_two_real_transitions_ready"])
            self.assertEqual(summary["verified_manifest_count"], 1)
            self.assertFalse(summary["production_apply_authorized"])
            self.assertFalse(summary["database_write_performed"])
            self.assertFalse(summary["deployment_performed"])
            self.assertEqual(
                _run("git", "status", "--porcelain=v1", "--untracked-files=all", cwd=repo),
                "",
            )
            self.assertTrue((output / "audit-artifact-manifest.json").is_file())


class NettoRpi5ShadowAuditStaticContractTest(unittest.TestCase):
    def test_workflow_uses_exact_label_and_no_checkout(self) -> None:
        text = (ROOT / ".github/workflows/netto-shadow-rpi5-audit.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("audit:netto-shadow-v1", text)
        self.assertIn("pull_request_target:", text)
        self.assertIn("hermes-deals-netto-shadow-audit-dispatch", text)
        self.assertNotIn("actions/checkout", text)
        self.assertIn("Production deployment: **not authorized**", text)
        self.assertIn("Database write: **not authorized**", text)

    def test_installer_creates_dedicated_root_owned_boundary(self) -> None:
        text = (ROOT / "tools/runner/install-netto-shadow-rpi5-audit.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("github-runner must not belong to the Docker group", text)
        self.assertIn("/usr/local/sbin/hermes-deals-netto-shadow-audit-dispatch", text)
        self.assertIn("audit_name='netto-shadow-v1'", text)
        self.assertIn("production_apply_authorized", text)
        self.assertNotIn("docker exec", text)
        self.assertNotIn("psql", text)

    def test_runner_never_calls_docker_or_database(self) -> None:
        text = (ROOT / "tools/run-hermes-deals-netto-shadow-evidence-v01.sh").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("docker", text)
        self.assertNotIn("psql", text)
        self.assertIn("--output", text)
        self.assertIn("HERMES_AUDIT_EXPECTED_HEAD", text)


if __name__ == "__main__":
    unittest.main()
