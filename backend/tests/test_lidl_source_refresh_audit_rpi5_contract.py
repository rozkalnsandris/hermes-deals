from __future__ import annotations

from pathlib import Path
import subprocess

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "hermes-lidl-source-refresh-audit.yml"
TOOL = ROOT / "tools" / "lidl_source_refresh_audit.py"
DISPATCHER = ROOT / "tools" / "runner" / "lidl-source-refresh-audit-dispatcher.sh"
INSTALLER = ROOT / "tools" / "runner" / "install-lidl-source-refresh-audit-dispatcher.sh"
FINALIZER = ROOT / "tools" / "runner" / "run-lidl-source-refresh-audit-owner-finalizer.sh"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_shell_entrypoints_parse() -> None:
    for path in (DISPATCHER, INSTALLER, FINALIZER):
        subprocess.run(["bash", "-n", str(path)], check=True)


def test_workflow_is_owner_issue_comment_only_and_rpi_job_has_no_repo_token() -> None:
    source = text(WORKFLOW)
    document = yaml.load(source, Loader=yaml.BaseLoader)
    assert set(document["on"]) == {"issue_comment"}
    assert document["on"]["issue_comment"]["types"] == ["created"]
    assert "workflow_dispatch:" not in source
    assert "schedule:" not in source
    assert "pull_request:" not in source
    assert "push:" not in source
    assert "github.event.issue.number == 345" in source
    assert "EXPECTED_OWNER_LOGIN: rozkalnsandris" in source
    assert 'EXPECTED_OWNER_ID: "277435981"' in source
    assert "re.fullmatch(" in source
    assert "/hermes-lidl-source-refresh-audit pr=" in source
    assert "runs-on:\n      - self-hosted" in source
    assert "permissions: {}" in source
    assert "actions/checkout" not in source
    assert "sudo --non-interactive /usr/local/sbin/hermes-deals-lidl-source-refresh-audit-dispatch" in source
    assert "actions/upload-artifact@v4" in source
    assert "source-refresh-summary.json" in source
    assert "source-review-template.json" in source
    assert "raw_source_exported" in source
    for forbidden in (
        "bash -c",
        "sh -c",
        "eval ",
        "docker ",
        "psql ",
        "alembic ",
        "systemctl ",
        "lidl-source-refresh-apply",
    ):
        assert forbidden not in source


def test_tool_is_exact_rev05_read_only_and_standard_library_only() -> None:
    source = text(TOOL)
    assert "EXPECTED_FAMILY = (" in source
    assert "aktionsprospekt-03-08-2026-08-08-2026-b1cf3b--src-6da2135ea984" in source
    assert "6da2135ea984d1f79bdb311dfa0d8affd1d2f8d46c63a1bba25b202a30a5fb16" in source
    assert "d1af2062f10f5fd25d4ac197fe74459bf0c313d7f5890f5d96c3db9572b7ddf1" in source
    assert "7486e32f837869b3dedc36b5a129c034129f653bf698df4ad55649510623ff17" in source
    assert "8d63c989fd1897215f9556942aec16636ce7c0e5a8bb05b5a672693f58519c5a" in source
    assert '"decision": "PENDING_OWNER_REVIEW"' in source
    assert '"scope": "authoritative_staging_scan_only"' in source
    assert '"staging_scan": True' in source
    assert '"corpus_write": False' in source
    assert '"parser_scan": False' in source
    assert '"raw_source_exported": False' in source
    for forbidden in (
        "import httpx",
        "import requests",
        "import subprocess",
        "os.system",
        "shutil",
        "sqlite",
        "psycopg",
        "sqlalchemy",
    ):
        assert forbidden not in source.lower()


def test_dispatcher_cannot_select_arbitrary_corpus_path_and_proves_invariance() -> None:
    source = text(DISPATCHER)
    assert "[[ $# -eq 3 ]]" in source
    assert "FAMILY=\"$CORPUS_ROOT/flyers/aktionsprospekt-03-08-2026-08-08-2026-b1cf3b--src-6da2135ea984\"" in source
    assert "--frozen-family \"$FAMILY\"" in source
    assert "--as-of \"$AS_OF\"" in source
    assert "corpus_digest" in source
    assert "authoritative Lidl corpus changed during read-only audit" in source
    assert "PRIMARY_WORKTREE_UNCHANGED=true" in source
    assert "PRIMARY_GIT_INDEX_UNCHANGED=true" in source
    assert "PRIMARY_V08_UNCHANGED=true" in source
    assert "CORPUS_WRITE=false" in source
    assert "PARSER_SCAN=false" in source
    assert "PRODUCTION_DATABASE_WRITE=false" in source
    assert "REVIEW_WRITE=false" in source
    assert "PRODUCTION_DEPLOY=false" in source
    assert "SYSTEMD_CHANGE=false" in source
    assert "AUTOMATIC_RETRY=false" in source
    assert "GATE_C_D_AUTHORIZED=false" in source
    assert "source.pdf" not in source.split("for name in", 1)[1]
    assert "source.json" not in source.split("for name in", 1)[1]
    for forbidden in (
        'rm -rf -- "$CORPUS_ROOT"',
        'mv -f -- "$STAGING" "$CORPUS_ROOT',
        "lidl_gate_b_freeze_apply",
        "docker run",
    ):
        assert forbidden not in source


def test_installer_exposes_only_fixed_read_only_dispatcher() -> None:
    source = text(INSTALLER)
    assert "AUDIT_REPO='/home/andris/hermes-deals-audit-source-lidl-refresh'" in source
    assert "INSTALLED_TOOL='/usr/local/libexec/hermes-deals-audits/lidl-source-refresh-audit.py'" in source
    assert "DISPATCHER='/usr/local/sbin/hermes-deals-lidl-source-refresh-audit-dispatch'" in source
    assert "github-runner ALL=(root) NOPASSWD: /usr/local/sbin/hermes-deals-lidl-source-refresh-audit-dispatch *" in source
    assert "RUNNER_HAS_DOCKER_GROUP=false" in source
    assert "CORPUS_WRITE=false" in source
    assert "PARSER_SCAN=false" in source
    assert "PRODUCTION_DATABASE_WRITE=false" in source
    assert "SYSTEMD_CHANGE=false" in source
    for forbidden in (
        "lidl-source-refresh-apply",
        "docker build",
        "docker run",
        "systemctl restart",
        "systemctl enable",
    ):
        assert forbidden not in source


def test_owner_finalizer_only_bootstraps_and_stops_before_audit() -> None:
    source = text(FINALIZER)
    assert "AUDIT_REPO='/home/andris/hermes-deals-audit-source-lidl-refresh'" in source
    assert "install-lidl-source-refresh-audit-dispatcher.sh" in source
    assert "OWNER_BOOTSTRAP_RESULT=PASS" in source
    assert "AUDIT_EXECUTED=false" in source
    assert "NEXT_GITHUB_COMMAND=/hermes-lidl-source-refresh-audit" in source
    assert "/usr/local/sbin/hermes-deals-lidl-source-refresh-audit-dispatch' ||" in source
    assert "CORPUS_WRITE=false" in source
    assert "PARSER_SCAN=false" in source
    assert "PRIMARY_INVARIANCE=true" in source
    assert "sudo /usr/local/sbin/hermes-deals-lidl-source-refresh-audit-dispatch" not in source
    for command in ("switch", "checkout", "reset", "clean", "pull"):
        assert f'git -C "$PRIMARY" {command}' not in source
