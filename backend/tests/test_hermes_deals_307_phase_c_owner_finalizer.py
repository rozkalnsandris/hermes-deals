from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
FINALIZER = ROOT / "tools" / "runner" / "run-hermes-deals-307-phase-c-owner-finalizer.sh"
TARGET_SHA = "019a33cb74cafee9d455fcf488d06f91337bc301"
DISPATCHER = "/usr/local/sbin/hermes-deals-307-phase-c-dispatch"


def source() -> str:
    return FINALIZER.read_text(encoding="utf-8")


def test_owner_finalizer_is_syntax_valid_and_pins_reviewed_bootstrap() -> None:
    text = source()
    subprocess.run(["bash", "-n", str(FINALIZER)], check=True)

    assert "FINALIZER_VERSION='hermes-deals-307-phase-c-owner-finalizer-v1'" in text
    assert "SOURCE_PR='329'" in text
    assert f"TARGET_SHA='{TARGET_SHA}'" in text
    assert "AUDIT_REPO='/home/andris/hermes-deals-audit-source-307'" in text
    assert "install-hermes-deals-307-phase-c-dispatch.sh" in text
    assert f"DISPATCHER='{DISPATCHER}'" in text
    assert "source PR merge SHA mismatch" in text
    assert 'merge-base --is-ancestor "$TARGET_SHA" origin/main' in text


def test_owner_finalizer_preserves_primary_and_uses_dedicated_clone() -> None:
    text = source()

    assert "PRIMARY='/home/andris/hermes-deals'" in text
    assert "verify_primary_unchanged" in text
    assert "PRIMARY_WORKTREE_UNCHANGED=true" in text
    assert "PRIMARY_INDEX_UNCHANGED=true" in text
    assert 'git -C "$AUDIT_REPO" fetch --prune origin main' in text
    assert 'git -C "$AUDIT_REPO" switch --detach "$TARGET_SHA"' in text

    for forbidden in (
        'git -C "$PRIMARY" switch',
        'git -C "$PRIMARY" checkout',
        'git -C "$PRIMARY" reset',
        'git -C "$PRIMARY" clean',
        'git -C "$PRIMARY" stash',
        'git -C "$PRIMARY" pull',
        'git -C "$PRIMARY" merge',
        'git -C "$PRIMARY" rebase',
    ):
        assert forbidden not in text


def test_owner_finalizer_grants_no_generic_or_rollback_execution_path() -> None:
    text = source()

    assert 'sudo bash "$INSTALLER" "$TARGET_SHA"' in text
    assert 'sudo -u github-runner -- sudo --non-interactive "$DISPATCHER" check' in text
    assert "$DISPATCHER apply-dual" in text
    assert "$DISPATCHER verify-dual" in text
    assert "$DISPATCHER rollback-lan" in text  # negative authorization check only
    assert "runner rollback-lan authorization is forbidden" in text
    assert "RUNNER_ROLLBACK_LAN_AUTHORIZED=false" in text
    assert "NEXT_GITHUB_ACTION=/hermes-307 apply-dual" in text

    # The finalizer itself must stop before the mutating GitHub bridge action.
    assert "gh api" in text  # PR metadata only
    assert "issues/307/comments" not in text
    assert "gh workflow run" not in text
    assert "apply-dual 2>&1 | tee" not in text

    for forbidden in (
        "sudo bash -c",
        "sudo sh -c",
        "sudo tee /etc/",
        "sudo install ",
        "eval ",
        "docker ",
        "ufw ",
        "systemctl ",
        "cloudflared ",
    ):
        assert forbidden not in text


def test_owner_finalizer_requires_all_safety_markers_and_read_only_check() -> None:
    text = source()

    for marker in (
        "INSTALL_RESULT=PASS",
        "SUDOERS_VALID=true",
        "RUNNER_HAS_DOCKER_GROUP=false",
        "ALLOWED_MODES=check,apply-dual,verify-dual",
        "ROLLBACK_MODE_RUNNER_AUTHORIZED=false",
        "PRODUCTION_RUNTIME_CHANGED=false",
        "CLOUDFLARE_ROUTE_CHANGED=false",
        "UFW_CHANGED=false",
        "DATABASE_WRITE=false",
        "SHARED_CLOUDFLARED_LIFECYCLE=false",
        "HERMES_DEALS_307_DUAL_BIND_CHECK=PASS",
        "READ_ONLY_PHASE_C_CHECK=PASS",
        "OWNER_FINALIZER_RESULT=PASS",
    ):
        assert marker in text
