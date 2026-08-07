from __future__ import annotations

from pathlib import Path
import re
import subprocess

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/netto-geometry-rpi5-replay.yml"
RUNNER = ROOT / "tools/run-hermes-deals-netto-geometry-replay-v01.sh"
INSTALLER = ROOT / "tools/runner/install-netto-geometry-rpi5-replay.sh"
DOC = ROOT / "docs/NETTO_GEOMETRY_RPI5_REPLAY_V1.md"

UPLOAD_ARTIFACT_V7_0_1_SHA = "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_geometry_replay_shell_sources_have_valid_bash_syntax() -> None:
    subprocess.run(["bash", "-n", str(RUNNER)], check=True)
    subprocess.run(["bash", "-n", str(INSTALLER)], check=True)


def test_workflow_is_owner_only_and_never_checks_out_pr_code() -> None:
    source = text(WORKFLOW)
    payload = yaml.safe_load(source)
    assert payload["name"] == "Netto geometry RPi5 replay"
    assert "pull_request_target" in source
    assert "audit:netto-geometry-replay-v1" in source
    assert "EXPECTED_OWNER_LOGIN: rozkalnsandris" in source
    assert 'EXPECTED_OWNER_ID: "277435981"' in source
    assert 'event_path = pathlib.Path(os.environ["GITHUB_EVENT_PATH"])' in source
    assert "actions/checkout" not in source
    assert "pull_request.head.sha" not in source
    assert "github.event.pull_request.head" not in source
    assert "geometry replays are accepted only on merged pull requests" in source
    assert "merged commit is not reachable from current main" in source
    assert "Hermes Deals CI checks" in source
    assert "/actions/workflows/ci.yml/runs?" in source
    assert "exact merged SHA has no successful main-push Hermes Deals CI checks run" in source


def test_workflow_uses_least_privilege_and_immutable_artifact_action() -> None:
    source = text(WORKFLOW)
    assert re.search(
        r"permissions:\n  actions: read\n  contents: read\n  issues: read\n  pull-requests: read",
        source,
    )
    assert f"uses: actions/upload-artifact@{UPLOAD_ARTIFACT_V7_0_1_SHA}" in source
    assert "uses: actions/upload-artifact@v" not in source
    assert "retention-days: 14" in source
    assert "overwrite: false" in source
    assert "include-hidden-files: false" in source
    assert "hermes-deals-audit" in source
    assert (
        "sudo --non-interactive /usr/local/sbin/"
        "hermes-deals-netto-geometry-replay-dispatch"
    ) in source


def test_report_metadata_failures_cannot_mask_successful_replay_evidence() -> None:
    source = text(WORKFLOW)
    report = source.split("\n  report:\n", 1)[1]
    assert "Report metadata without masking replay evidence" in report
    assert "def best_effort_comment()" in report
    assert "def best_effort_label_cleanup()" in report
    assert "best_effort_comment()" in report
    assert "best_effort_label_cleanup()" in report
    assert "error.read(2048)" in report
    assert "REPORT_COMMENT=FAIL" in report
    assert "REPLAY_LABEL_CLEANUP=FAIL" in report
    assert "REPORT_METADATA_BEST_EFFORT=PASS" in report
    assert "raise" not in report


def test_runner_is_exact_evidence_only_and_fail_closed() -> None:
    source = text(RUNNER)
    assert "/usr/bin/python3" in source
    assert 'version != "1.28.0"' in source
    assert (
        "netto-n9-visual-cell-validation-pack-v1-20260802T202304Z/generated/"
        "fixture-manifest.json"
    ) in source
    assert (
        "2b180d67af4c5d1e586704088e3d685cff21ae2e12f3052254daf4553dd4e147"
    ) in source
    assert "/home/andris/hermes-deals-netto-corpus/flyers" in source
    assert "netto_visual_geometry_corpus_replay.py" in source
    assert '"fixture_page_count": 17' in source
    assert '"cell_count": 100' in source
    assert '"promotion_ready": False' in source
    assert '"database_write_performed": False' in source
    assert '"production_apply_authorized": False' in source
    for forbidden in (
        "docker ",
        "docker\n",
        "psql ",
        "pip install",
        "git reset",
        "git clean",
        "systemctl restart",
    ):
        assert forbidden not in source


def test_installer_uses_detached_exact_worktree_and_root_owned_runtime() -> None:
    source = text(INSTALLER)
    assert (
        "EXPECTED_SOURCE_REPO='/home/andris/hermes-deals-worktrees/"
        "netto-geometry-replay-v1'"
    ) in source
    assert "source worktree must be detached at the registered SHA" in source
    assert "source worktree HEAD mismatch" in source
    assert "source worktree is not clean" in source
    assert "source is not a worktree of /home/andris/hermes-deals" in source
    assert "registered SHA is not reachable from fetched origin/main" in source
    assert (
        "RUNTIME_ROOT='/usr/local/libexec/hermes-deals-audits/"
        "netto-geometry-replay-v1'"
    ) in source
    assert "root:root" in source
    assert "/etc/hermes-deals-audits.d/netto-geometry-replay-v1.conf" in source
    assert "/usr/local/sbin/hermes-deals-netto-geometry-replay-dispatch" in source
    assert "github-runner must not belong to the Docker group" in source
    assert "PyMuPDF 1.28.0 required" in source
    assert "bf35bff323d76a2b29a7248df067641e5b9f2a7d29329cf53bf9fc0ae832734a" in source


def test_installer_inspects_source_git_only_as_worktree_owner_without_optional_locks() -> None:
    source = text(INSTALLER)

    assert "git_source()" in source
    assert "runuser -u andris -- /usr/bin/env -i" in source
    assert "GIT_OPTIONAL_LOCKS=0" in source
    assert '/usr/bin/git "$@"' in source
    assert 'git_source -C "$SOURCE_REPO" status --porcelain=v1 --untracked-files=all' in source
    assert 'git_source -C "$SOURCE_REPO" rev-parse HEAD' in source
    assert 'git_source -C "$SOURCE_REPO" remote get-url origin' in source
    assert 'git_source -C "$SOURCE_REPO" ls-files --error-unmatch "$relative"' in source

    # A root-owned installer must never directly invoke Git against the
    # andris-owned source worktree. In particular, plain `git status` can
    # refresh and rewrite the index as a side effect.
    assert 'git -C "$SOURCE_REPO"' not in source


def test_dispatcher_exports_only_bounded_sanitized_evidence() -> None:
    source = text(INSTALLER)
    for name in (
        "netto-geometry-corpus-replay.json",
        "replay-execution.log",
        "replay-exit-code.txt",
        "runtime-identity.json",
        "dispatcher-evidence-manifest.json",
    ):
        assert name in source
    assert "unexpected replay output member" in source
    assert "sensitive content rejected" in source
    assert "32 * 1024 * 1024" in source
    assert '"production_apply_authorized": False' in source
    assert '"database_write_performed": False' in source
    assert '"review_write_performed": False' in source
    assert '"deployment_performed": False' in source
    assert '"promotion_ready": False' in source


def test_install_and_run_paths_do_not_touch_production_controls() -> None:
    combined = text(RUNNER) + "\n" + text(INSTALLER)
    for forbidden in (
        "docker compose",
        "docker exec",
        "psql ",
        "alembic upgrade",
        "systemctl enable",
        "systemctl restart",
        "git reset --hard",
        "git clean",
        "/var/lib/postgresql",
        "B15M2",
    ):
        assert forbidden not in combined
    assert "PRODUCTION_APPLY_AUTHORIZED=false" in text(INSTALLER)
    assert "promotion_ready" in text(RUNNER)


def test_runbook_keeps_primary_checkout_untouched() -> None:
    source = text(DOC)
    assert "git -C \"$PRIMARY\" worktree add --detach" in source
    assert "The primary `/home/andris/hermes-deals` checkout is never switched" in source
    assert "audit:netto-geometry-replay-v1" in source
    assert "GIT_OPTIONAL_LOCKS=0" in source
    assert "source-worktree Git checks run as `andris`" in source
