from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
FINALIZER = ROOT / "tools" / "runner" / "run-netto-ownership-separator-audit-owner-finalizer.sh"
TARGET_SHA = "91f6d28332c2e488b7076c0f20492a0c43db52db"
DISPATCHER = "/usr/local/sbin/hermes-deals-netto-ownership-separator-audit-dispatch"
WORKTREE = "/home/andris/hermes-deals-worktrees/netto-ownership-separator-audit-v1"


def source() -> str:
    return FINALIZER.read_text(encoding="utf-8")


def test_finalizer_is_syntax_valid_and_pins_reviewed_bootstrap() -> None:
    text = source()
    subprocess.run(["bash", "-n", str(FINALIZER)], check=True)

    assert "FINALIZER_VERSION='netto-ownership-separator-audit-owner-finalizer-v1'" in text
    assert "SOURCE_PR='330'" in text
    assert f"TARGET_SHA='{TARGET_SHA}'" in text
    assert f"WORKTREE='{WORKTREE}'" in text
    assert "install-netto-ownership-separator-rpi5-audit.sh" in text
    assert f"DISPATCHER='{DISPATCHER}'" in text
    assert "source PR merge SHA mismatch" in text
    assert 'merge-base --is-ancestor "$TARGET_SHA" origin/main' in text
    assert "exact source SHA has no successful main-push CI" in text


def test_finalizer_preserves_primary_and_uses_exact_detached_worktree() -> None:
    text = source()

    assert "PRIMARY='/home/andris/hermes-deals'" in text
    assert "verify_primary_unchanged" in text
    assert "PRIMARY_WORKTREE_UNCHANGED=true" in text
    assert "PRIMARY_INDEX_UNCHANGED=true" in text
    assert 'git -C "$PRIMARY" worktree add --detach "$WORKTREE" "$TARGET_SHA"' in text
    assert '[[ -z "$(git_read "$WORKTREE" branch --show-current)" ]]' in text
    assert '[[ -z "$(git_read "$WORKTREE" status --porcelain=v1 --untracked-files=all)" ]]' in text

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


def test_finalizer_installs_only_reviewed_root_trust_and_does_not_run_audit() -> None:
    text = source()

    assert 'sudo bash "$INSTALLER" "$TARGET_SHA" "$WORKTREE"' in text
    assert 'sudo -u github-runner -- sudo --non-interactive -l "$DISPATCHER"' in text
    assert "AUDIT_EXECUTED=false" in text
    assert "NEXT_GITHUB_ACTION=apply audit:netto-ownership-separator-v1 to merged PR #330" in text

    # No dispatcher execution is allowed in the bootstrap helper itself.
    assert 'sudo --non-interactive "$DISPATCHER"' not in text
    assert 'sudo -u github-runner -- sudo --non-interactive "$DISPATCHER"' not in text

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
        "psql ",
    ):
        assert forbidden not in text


def test_finalizer_requires_safety_markers_and_narrow_runner_boundary() -> None:
    text = source()

    for marker in (
        "INSTALL_RESULT=PASS",
        "AUDIT=netto-ownership-separator-audit-v1",
        "N9_MANIFEST_SHA256=$EXPECTED_N9_SHA",
        "PYMUPDF_VERSION=1.28.0",
        "PYMUPDF_RUNTIME_USER=andris",
        "PYMUPDF_PYTHON=/usr/bin/python3",
        "RUNNER_HAS_DOCKER_GROUP=false",
        "PRODUCTION_APPLY_AUTHORIZED=false",
        "DISPATCHER_AUTHORIZATION_CHECK=PASS",
        "DATABASE_WRITE=false",
        "REVIEW_WRITE=false",
        "APPROVAL_PUBLICATION=false",
        "PRODUCTION_DEPLOY=false",
        "OWNER_FINALIZER_RESULT=PASS",
    ):
        assert marker in text

    assert "github-runner unexpectedly belongs to Docker group" in text
    assert "root:root:755" in text
    assert "root:root:644" in text
    assert "root:root:440" in text
