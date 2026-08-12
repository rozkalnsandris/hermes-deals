from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "tools/aldi_a30_authoritative_cycle.py"
REVIEW = ROOT / "tools/aldi_a30_rollover_review.py"
PLAN = ROOT / "config/aldi-a30-authoritative-cycle-2026cw32-cw33.json"
RUNNER = ROOT / "tools/run-hermes-deals-aldi-a30-authoritative-cycle-v01.sh"
INSTALLER = ROOT / "tools/runner/install-aldi-a30-authoritative-cycle-dispatcher.sh"
WORKFLOW = ROOT / ".github/workflows/aldi-a30-authoritative-cycle-rpi5.yml"
UPLOAD_ARTIFACT_SHA = "b7c566a772e6b6bfb58ed0dc250532a479d7789f"


def load_review_module():
    spec = importlib.util.spec_from_file_location(
        "aldi_a30_rollover_review_under_test",
        REVIEW,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load ALDI rollover-review module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AldiA30AuthoritativeCycleContractTest(unittest.TestCase):
    def test_python_and_shell_syntax(self) -> None:
        for path in (MODULE, REVIEW):
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        for path in (RUNNER, INSTALLER):
            subprocess.run(
                ["bash", "-n", str(path)],
                check=True,
                capture_output=True,
                text=True,
            )

    def test_plan_is_frozen_and_distinct(self) -> None:
        plan = json.loads(PLAN.read_text(encoding="utf-8"))
        self.assertEqual(
            plan["source_discovery_commit"],
            "24d1a44df06751fe9107e568ceb12c9f2c5cea79",
        )
        self.assertEqual(plan["source_discovery_run_id"], 31010778804)
        self.assertEqual(plan["old_preview_page_count"], 41)
        self.assertEqual(plan["rollover"]["required_pages"], 41)
        self.assertNotEqual(
            plan["sources"]["current"]["source_path"],
            plan["sources"]["preview"]["source_path"],
        )

    def test_workflow_is_owner_only_and_manual(self) -> None:
        document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        self.assertIn("workflow_dispatch", document[True])
        text = WORKFLOW.read_text(encoding="utf-8")
        for required in (
            "rozkalnsandris",
            "277435981",
            "self-hosted",
            "hermes-deals-audit",
            f"actions/upload-artifact@{UPLOAD_ARTIFACT_SHA} # v6.0.0",
        ):
            self.assertIn(required, text)
        self.assertNotIn("uses: actions/upload-artifact@v6", text)

    def test_safety_boundaries(self) -> None:
        text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (MODULE, REVIEW, RUNNER, INSTALLER, WORKFLOW)
        )
        for required in (
            "PRODUCTION_DATABASE_WRITE=false",
            "PRODUCTION_DEPLOYMENT=false",
            "B15M2_V08_ACTION=false",
        ):
            self.assertIn(required, text)
        for forbidden in (
            "docker run",
            "docker compose",
            "psql ",
            "alembic upgrade",
            "systemctl restart",
        ):
            self.assertNotIn(forbidden, text)

    def test_runner_worktree_verification_is_fail_closed(self) -> None:
        text = RUNNER.read_text(encoding="utf-8")
        for required in (
            "capture_repo_snapshot",
            "PRIMARY_WORKTREE_VERIFICATION=failed",
            "PRIMARY_WORKTREE_MODIFIED=unknown",
            '[[ ! -s "$stderr_file" ]] || return 1',
            "git index is missing, unsafe, or unreadable",
            "audit_after",
            "primary_after",
            "aldi_a30_rollover_review.py",
        ):
            self.assertIn(required, text)
        self.assertNotIn(
            'status --porcelain=v1 -z --untracked-files=all | sha256sum',
            text,
        )

    def test_installer_preserves_audit_index_ownership(self) -> None:
        text = INSTALLER.read_text(encoding="utf-8")
        for required in (
            'AUDIT_USER="andris"',
            '/usr/sbin/runuser -u "$AUDIT_USER"',
            "GIT_OPTIONAL_LOCKS=0",
            "audit_git_to_file",
            "audit repo git command emitted stderr",
            "INDEX_OWNER_BEFORE",
            "INDEX_SHA256_BEFORE",
            "INDEX_OWNER_AFTER_GIT",
            "INDEX_SHA256_AFTER_GIT",
            "INDEX_OWNER_AFTER",
            "INDEX_SHA256_AFTER",
            "INSTALLER_INDEX_OWNERSHIP_PRESERVED=true",
        ):
            self.assertIn(required, text)
        self.assertEqual(text.count('/usr/bin/git -C "$REPO"'), 1)
        self.assertNotIn('$(git -C "$REPO"', text)
        self.assertNotIn('[[ -z "$(git -C "$REPO"', text)
        self.assertIn(
            'status "$tmp_dir/status.stdout" status --porcelain=v1 -z --untracked-files=all',
            text,
        )

    def test_exact_content_classification_detects_moved_pages(self) -> None:
        module = load_review_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old_paths = []
            current_paths = []
            for page, data in enumerate((b"A", b"B", b"C", b"D"), start=1):
                path = root / f"old-{page}.img"
                path.write_bytes(data)
                old_paths.append(path)
            for page, data in enumerate((b"X", b"A", b"B", b"D"), start=1):
                path = root / f"new-{page}.img"
                path.write_bytes(data)
                current_paths.append(path)

            result = module.classify_exact_rollover(old_paths, current_paths)

        self.assertEqual(result["exact_positional_matched_pages"], 1)
        self.assertEqual(result["content_set_matched_pages"], 3)
        self.assertEqual(
            [(row["old_page"], row["new_page"]) for row in result["moved_pages"]],
            [(1, 2), (2, 3)],
        )
        self.assertEqual(result["old_only_pages"], [3])
        self.assertEqual(result["new_only_pages"], [1])

    def test_manual_review_bundle_contains_only_unmatched_pages(self) -> None:
        module = load_review_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = root / "evidence"
            evidence.mkdir()
            old_paths = []
            current_paths = []
            for page, data in enumerate((b"A", b"B"), start=1):
                path = root / f"old-{page}.img"
                path.write_bytes(data)
                old_paths.append(path)
            for page, data in enumerate((b"A", b"X"), start=1):
                path = root / f"new-{page}.img"
                path.write_bytes(data)
                current_paths.append(path)
            exact = module.classify_exact_rollover(old_paths, current_paths)
            summary = module.write_manual_review_bundle(
                evidence,
                old_paths,
                current_paths,
                exact,
                [],
                False,
            )
            review_json = json.loads(
                (evidence / "manual-review/manual-review.json").read_text()
            )

        self.assertEqual(summary["classification"], "manual_review_required")
        self.assertEqual(review_json["old_only_pages"], [2])
        self.assertEqual(review_json["new_only_pages"], [2])
        self.assertEqual(len(review_json["old_preview_files"]), 1)
        self.assertEqual(len(review_json["new_current_files"]), 1)
        self.assertFalse(review_json["automatic_promotion_allowed"])

    def test_rollover_review_markers_and_strict_gate(self) -> None:
        text = REVIEW.read_text(encoding="utf-8")
        for required in (
            "ROLLOVER_POSITIONAL_MATCHED_PAGES",
            "ROLLOVER_CONTENT_SET_MATCHED_PAGES",
            "ROLLOVER_MOVED_PAGES",
            "ROLLOVER_OLD_ONLY_PAGES",
            "ROLLOVER_NEW_ONLY_PAGES",
            "MANUAL_REVIEW_REQUIRED",
            "strict_41_of_41_gate_unchanged",
            "manual-review/manual-review.json",
        ):
            self.assertIn(required, text)


if __name__ == "__main__":
    unittest.main()
