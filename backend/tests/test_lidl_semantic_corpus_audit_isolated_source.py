from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
V01 = ROOT / "tools/run-hermes-deals-lidl-semantic-corpus-audit-v01.sh"
AUDIT = ROOT / "tools/run-hermes-deals-lidl-semantic-corpus-audit-v02.sh"
INSTALLER = (
    ROOT
    / "tools/runner/install-lidl-semantic-corpus-audit-dispatcher-v02.sh"
)


def render_runtime() -> str:
    audit_text = AUDIT.read_text(encoding="utf-8")
    marker = (
        'python3 - "$source_script" "$patched_script" '
        '"$AUDIT_REPO" "$AUDIT_VERSION" <<\'PY\'\n'
    )
    try:
        program = audit_text.split(marker, 1)[1].split("\nPY\n", 1)[0]
    except IndexError as exc:
        raise AssertionError("cannot extract V02 runtime transformer") from exc

    with tempfile.TemporaryDirectory() as temp_dir:
        destination = Path(temp_dir) / "runtime.sh"
        subprocess.run(
            [
                "python3",
                "-",
                str(V01),
                str(destination),
                "/home/andris/hermes-deals-audit-source",
                "lidl-semantic-corpus-audit-v02.3-partition-contract",
            ],
            input=program,
            check=True,
            capture_output=True,
            text=True,
        )
        return destination.read_text(encoding="utf-8")


def extract_summary_validator(runtime: str) -> str:
    marker = (
        'python3 - "$output_dir/coverage-report.json" '
        '"$output_dir/manifest.json" "$flyer_key" "$scan" '
        '"$page_count" >> "$summary_rows" <<\'PY\'\n'
    )
    try:
        return runtime.split(marker, 1)[1].split("\nPY\n", 1)[0]
    except IndexError as exc:
        raise AssertionError("cannot extract semantic summary validator") from exc


def run_summary_validator(
    program: str,
    coverage: dict[str, object],
) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        coverage_path = root / "coverage-report.json"
        manifest_path = root / "manifest.json"
        coverage_path.write_text(
            json.dumps(coverage, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest_path.write_text("{}\n", encoding="utf-8")
        return subprocess.run(
            [
                "python3",
                "-",
                str(coverage_path),
                str(manifest_path),
                "fixture-flyer",
                "scan-0001",
                "69",
            ],
            input=program,
            check=False,
            capture_output=True,
            text=True,
        )


class LidlSemanticCorpusAuditIsolatedSourceTest(unittest.TestCase):
    def test_shell_entrypoints_have_valid_bash_syntax(self) -> None:
        for path in (AUDIT, INSTALLER):
            subprocess.run(
                ["bash", "-n", str(path)],
                check=True,
                capture_output=True,
                text=True,
            )

    def test_audit_uses_exact_clean_isolated_clone(self) -> None:
        text = AUDIT.read_text(encoding="utf-8")
        for required in (
            'AUDIT_VERSION="lidl-semantic-corpus-audit-v02.3-partition-contract"',
            'AUDIT_REPO="/home/andris/hermes-deals-audit-source"',
            'GIT_OPTIONAL_LOCKS=0 git -C "$AUDIT_REPO" "$@"',
            'GIT_INDEX="$AUDIT_REPO/.git/index"',
            "isolated audit repository index ownership is invalid",
            'branch="$(git_read branch --show-current)"',
            'status="$(git_read status --porcelain)"',
            'head_sha="$(git_read rev-parse HEAD)"',
            'git_read show "$EXPECTED_SHA:$V01_PATH"',
            "expected exactly one frozen V01 marker",
            'REPO="/home/andris/hermes-deals"',
            "hermes-deals-runner-evidence/hermes-deals-audit-*",
            "hermes-deals-lidl-semantic-audit-*",
            'CORPUS_ROOT="/home/andris/hermes-deals-lidl-corpus/flyers"',
            "old_discovery: new_discovery",
            "old_partition_validation: new_partition_validation",
            '/bin/bash --noprofile --norc "$patched_script"',
        ):
            self.assertIn(required, text)

        for forbidden in (
            "git checkout",
            "git reset",
            "git switch",
            "git stash",
            "docker ",
            "docker-compose",
            "psql ",
            "alembic ",
            "systemctl restart",
            "rm -rf /home/andris/hermes-deals-lidl",
            "mv /home/andris/hermes-deals-lidl",
        ):
            self.assertNotIn(forbidden, text)

    def test_runtime_uses_only_authoritative_corpus_root(self) -> None:
        runtime = render_runtime()
        for required in (
            'AUDIT_VERSION="lidl-semantic-corpus-audit-v02.3-partition-contract"',
            'REPO="/home/andris/hermes-deals-audit-source"',
            'CORPUS_ROOT="/home/andris/hermes-deals-lidl-corpus/flyers"',
            "authoritative corpus root path drift",
            "authoritative corpus directory is missing or unsafe",
            "authoritative corpus file is missing or unsafe",
            "authoritative corpus scan is missing or unsafe",
            "printf '%s\\n' \"$candidate\"",
        ):
            self.assertIn(required, runtime)

        for forbidden in (
            "find /home/andris -xdev",
            "local -a matches=()",
            "expected exactly one complete corpus directory",
            "/home/andris/hermes-deals-lidl-lab-data",
        ):
            self.assertNotIn(forbidden, runtime)

        subprocess.run(
            ["bash", "-n"],
            input=runtime,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_runtime_uses_semantic_coverage_partition_contract(self) -> None:
        runtime = render_runtime()
        validator = extract_summary_validator(runtime)
        for required in (
            'coverage.get("input_row_count")',
            'coverage.get("unique_row_count")',
            'coverage.get("explained_count")',
            "unique_total != input_total",
            "explained_total != input_total",
            "parts != input_total",
            "total = input_total",
        ):
            self.assertIn(required, validator)
        self.assertNotIn('coverage.get("row_count")', validator)

        coverage = {
            "database_write": False,
            "review_seed": False,
            "auto_approve": False,
            "auto_publish": False,
            "production_deploy": False,
            "input_row_count": 346,
            "unique_row_count": 346,
            "explained_count": 346,
            "production_ready_count": 103,
            "review_required_count": 71,
            "excluded_count": 172,
            "unexplained_count": 0,
        }
        result = run_summary_validator(validator, coverage)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["row_count"], 346)
        self.assertEqual(payload["production_ready_count"], 103)
        self.assertEqual(payload["review_required_count"], 71)
        self.assertEqual(payload["excluded_count"], 172)
        self.assertEqual(payload["unexplained_count"], 0)

        broken = dict(coverage)
        broken["explained_count"] = 345
        result = run_summary_validator(validator, broken)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("semantic row partition is incomplete", result.stderr)

    def test_installer_uses_private_mount_namespace_without_index_drift(self) -> None:
        text = INSTALLER.read_text(encoding="utf-8")
        for required in (
            'AUDIT_REPO="/home/andris/hermes-deals-audit-source"',
            'PRIMARY_REPO="/home/andris/hermes-deals"',
            'GIT_INDEX="$AUDIT_REPO/.git/index"',
            'index_sha_before="$(sha256sum "$GIT_INDEX"',
            'index_stat_before="$(stat -c',
            'GIT_OPTIONAL_LOCKS=0 git -C "$AUDIT_REPO" "$@"',
            "unshare --mount --propagation private",
            'mount --bind "$source_repo" "$primary_repo"',
            "GIT_OPTIONAL_LOCKS=0 /bin/bash",
            "install-lidl-semantic-corpus-audit-dispatcher.sh",
            "isolated audit repository index content changed during installation",
            "isolated audit repository index metadata changed during installation",
            'git_read show "$EXPECTED_SHA:$V02_SCRIPT"',
            "script_sha256='$script_sha'",
            "AUDIT_VERSION=lidl-semantic-corpus-audit-v02.3-partition-contract",
            "PRIMARY_WORKTREE_MODIFIED=false",
            "AUDIT_GIT_INDEX_UNCHANGED=true",
            "RUNNER_HAS_DOCKER_GROUP=false",
            "PRODUCTION_APPLY_AUTHORIZED=false",
        ):
            self.assertIn(required, text)

        for forbidden in (
            'git -C "$PRIMARY_REPO" checkout',
            'git -C "$PRIMARY_REPO" reset',
            'git -C "$PRIMARY_REPO" switch',
            'git -C "$PRIMARY_REPO" stash',
            "github-runner ALL=(ALL) NOPASSWD: ALL",
            'chown andris:andris "$GIT_INDEX"',
        ):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
