from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "tools" / "vscode-rpi5-release.sh"
PRODUCTION_WRAPPER = ROOT / "tools" / "vscode-rpi5-production-deploy.sh"


def read_launcher() -> str:
    return LAUNCHER.read_text(encoding="utf-8")


def read_production_wrapper() -> str:
    return PRODUCTION_WRAPPER.read_text(encoding="utf-8")


def test_vscode_tasks_expose_check_and_confirmed_production_deploy() -> None:
    tasks = json.loads((ROOT / ".vscode" / "tasks.json").read_text(encoding="utf-8"))
    labels = {task["label"] for task in tasks["tasks"]}
    assert labels == {
        "Hermes Deals: Check deploy",
        "Hermes Deals: Production deploy",
    }

    modes = {tuple(task["args"]) for task in tasks["tasks"]}
    assert modes == {
        ("tools/vscode-rpi5-release.sh", "check"),
        ("tools/vscode-rpi5-production-deploy.sh",),
    }


def test_release_launcher_preserves_direct_main_fail_closed_boundaries() -> None:
    text = read_launcher()
    required = (
        "PRIMARY_ROOT='/home/andris/hermes-deals'",
        '[[ "$BRANCH" == main ]]',
        "git status --porcelain --untracked-files=normal",
        '[[ "$LOCAL_SHA" == "$REMOTE_SHA" ]]',
        "exact current main has no successful CI push run",
        "production API image is not a managed Hermes Deals release image",
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


def test_launcher_accepts_only_bounded_managed_tags_with_oci_binding() -> None:
    text = read_launcher()
    assert "org.opencontainers.image.revision" in text
    assert '^hermes-deals-api:(main|w4b|w4c)-([0-9a-f]{12})$' in text
    assert '^hermes-deals-api:release-[A-Za-z0-9_.-]+$' in text
    assert 'MANAGED_TAG_SHA="${BASH_REMATCH[2]}"' in text
    assert '[[ "$MANAGED_TAG_SHA" == "${CURRENT_REVISION:0:12}" ]]' in text
    assert "managed production image requires an exact OCI revision label" in text
    assert "managed production image tag does not match OCI revision" in text
    assert '[[ "$CURRENT_TAG" == hermes-deals-api:release-* ]]' not in text


def test_launcher_prefers_full_oci_revision_with_canonical_tag_fallback() -> None:
    text = read_launcher()
    assert "org.opencontainers.image.revision" in text
    assert '[[ "$CURRENT_REVISION" =~ ^[0-9a-f]{40}$ ]]' in text
    assert "PRODUCTION_PROVENANCE='oci-revision'" in text
    assert "PRODUCTION_PROVENANCE='canonical-tag'" in text
    assert 'release-[0-9]+\\.[0-9]+\\.[0-9]+-([0-9a-f]{7})' in text


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


def test_production_wrapper_requires_exact_sha_confirmation_before_deploy() -> None:
    subprocess.run(["bash", "-n", str(PRODUCTION_WRAPPER)], check=True)
    text = read_production_wrapper()
    required = (
        "RELEASE_LAUNCHER='tools/vscode-rpi5-release.sh'",
        '"$RELEASE_LAUNCHER" check',
        '[[ "$LOCAL_SHA" == "$TARGET_SHA" ]]',
        "NO DEPLOY NEEDED",
        "PRODUCTION_CHANGED=false",
        "Required confirmation:",
        "DEPLOY %s",
        "read -r -p '> ' CONFIRMATION",
        '[[ "$CONFIRMATION" == "DEPLOY ${TARGET_SHA}" ]]',
        "CONFIRMATION_MATCH=PASS",
        '"$RELEASE_LAUNCHER" deploy',
    )
    for marker in required:
        assert marker in text

    check_pos = text.index('"$RELEASE_LAUNCHER" check')
    no_op_pos = text.index("NO DEPLOY NEEDED")
    confirm_pos = text.index("read -r -p '> ' CONFIRMATION")
    deploy_pos = text.index('"$RELEASE_LAUNCHER" deploy')
    assert check_pos < no_op_pos < confirm_pos < deploy_pos


def test_production_wrapper_records_timestamped_local_log_and_container_state() -> None:
    text = read_production_wrapper()
    required = (
        'STATE_ROOT="${XDG_STATE_HOME:-$HOME/.local/state}/hermes-deals/deploy"',
        'mkdir -p "$STATE_ROOT"',
        'chmod 700 "$STATE_ROOT"',
        'STAMP="$(date -u +%Y%m%dT%H%M%SZ)"',
        'LOG_FILE="$STATE_ROOT/vscode-production-deploy-${STAMP}.log"',
        'chmod 600 "$LOG_FILE"',
        'exec > >(tee -a "$LOG_FILE") 2>&1',
        "POST_DEPLOY_API_CONTAINER_RUNNING=true",
        "POST_DEPLOY_API_REVISION=%s",
        "CONFIRMED_TARGET_SHA=%s",
        "FINISHED_AT_UTC=%s",
    )
    for marker in required:
        assert marker in text
