from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "tools" / "vscode-rpi5-release.sh"


def read_launcher() -> str:
    return LAUNCHER.read_text(encoding="utf-8")


def test_vscode_tasks_expose_only_check_and_direct_deploy() -> None:
    tasks = json.loads((ROOT / ".vscode" / "tasks.json").read_text(encoding="utf-8"))
    labels = {task["label"] for task in tasks["tasks"]}
    assert labels == {
        "Hermes Deals: Check deploy",
        "Hermes Deals: Deploy current main",
    }

    modes = {tuple(task["args"]) for task in tasks["tasks"]}
    assert modes == {
        ("tools/vscode-rpi5-release.sh", "check"),
        ("tools/vscode-rpi5-release.sh", "deploy"),
    }


def test_release_launcher_preserves_direct_main_fail_closed_boundaries() -> None:
    text = read_launcher()
    required = (
        "PRIMARY_ROOT='/home/andris/hermes-deals'",
        '[[ "$BRANCH" == main ]]',
        "git status --porcelain --untracked-files=normal",
        '[[ "$LOCAL_SHA" == "$REMOTE_SHA" ]]',
        "exact current main has no successful CI push run",
        "production API image is not a Hermes Deals release image",
        "production API image has no valid release SHA provenance",
        "production API image has malformed OCI revision label",
        "production OCI revision contradicts resolved Git commit",
        'git diff --name-only "${PRODUCTION_SHA}..${REMOTE_SHA}"',
        "cumulative database migration change is not an added Alembic revision",
        "live schema is not already at exact target Alembic head",
        "cumulative Compose change detected",
        "RUNTIME_SYNC='/usr/local/sbin/hermes-deals-release-runtime-sync'",
        "MAIN_DEPLOY='/usr/local/sbin/hermes-deals-release-main-deploy'",
        "DATABASE_WRITES_AUTHORIZED=false",
        "MIGRATION_COMMANDS_EXECUTED=false",
        "ROLLBACK_PERFORMED=false",
    )
    for marker in required:
        assert marker in text


def test_launcher_prefers_full_oci_revision_with_canonical_tag_fallback() -> None:
    text = read_launcher()
    assert "org.opencontainers.image.revision" in text
    assert '[[ "$CURRENT_REVISION" =~ ^[0-9a-f]{40}$ ]]' in text
    assert "PRODUCTION_PROVENANCE='oci-revision'" in text
    assert "PRODUCTION_PROVENANCE='canonical-tag'" in text
    assert 'release-[0-9]+\\.[0-9]+\\.[0-9]+-([0-9a-f]{7})' in text
    assert '[[ "$CURRENT_TAG" == hermes-deals-api:release-* ]]' in text


def test_launcher_reconciles_only_added_revisions_at_exact_live_head() -> None:
    text = read_launcher()
    for marker in (
        'git diff --name-status "${PRODUCTION_SHA}..${REMOTE_SHA}"',
        '[[ "$status" == A && "$path" == backend/alembic/versions/*.py ]]',
        'TARGET_ALEMBIC_HEAD="$(python3 - "$ROOT/backend/alembic/versions"',
        "SELECT version_num FROM alembic_version;",
        '[[ "$PRE_ALEMBIC" == "$TARGET_ALEMBIC_HEAD" ]]',
        'MIGRATION_RECONCILIATION="verified-live-head:${PRE_ALEMBIC}"',
        '[[ "$POST_ALEMBIC" == "$PRE_ALEMBIC" ]]',
    ):
        assert marker in text
    assert "alembic upgrade" not in text
    assert "alembic downgrade" not in text


def test_launcher_has_no_issue_plan_or_apply_bridge() -> None:
    text = read_launcher()
    for forbidden in (
        "gh workflow run",
        "gh issue create",
        "hermes:deploy-ready",
        "hermes-deals-release-request-v1",
        "create_bridge_request",
        "APPLY api-ui",
        "  plan)",
        "  apply)",
    ):
        assert forbidden not in text

    assert 'fail "usage: $0 {check|deploy}"' in text
    assert 'sudo --non-interactive "$RUNTIME_SYNC" "$REMOTE_SHA"' in text
    assert 'sudo --non-interactive "$MAIN_DEPLOY" "$REMOTE_SHA"' in text


def test_check_mode_is_read_only_and_has_no_deploy_call() -> None:
    text = read_launcher()
    check_block = text.split("  check)", 1)[1].split("  deploy)", 1)[0]
    assert "CHECK PASS" in check_block
    assert "PRODUCTION_CHANGED=false" in check_block
    assert "MAIN_DEPLOY" not in check_block
    assert "RUNTIME_SYNC" not in check_block
    assert "sudo --non-interactive" not in check_block
