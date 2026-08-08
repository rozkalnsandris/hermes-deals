from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
FINALIZER = (
    ROOT
    / "tools"
    / "runner"
    / "run-netto-object-card-graph-audit-reregister-owner-finalizer.sh"
)
TARGET_SHA = "5a263b103210d6a3aa223f057f13acb034b115cb"
WORKTREE = "/home/andris/hermes-deals-worktrees/netto-object-card-graph-audit-v1"


def source() -> str:
    return FINALIZER.read_text(encoding="utf-8")


def test_reregister_finalizer_pins_fixed_merge_and_is_syntax_valid() -> None:
    text = source()
    subprocess.run(["bash", "-n", str(FINALIZER)], check=True)

    assert "SOURCE_PR='411'" in text
    assert f"TARGET_SHA='{TARGET_SHA}'" in text
    assert f"WORKTREE='{WORKTREE}'" in text
    assert "exact target SHA has no successful main-push CI" in text
    assert 'merge-base --is-ancestor "$TARGET_SHA" origin/main' in text
    assert "SOURCE_PR='403'" not in text
    assert "3114135cf3d41c089b7ca5de7d134e725a9e1cd8" not in text


def test_reregister_refreshes_only_safe_stale_dedicated_worktree() -> None:
    text = source()

    assert "verify_worktree_identity" in text
    assert "audit worktree ownership mismatch" in text
    assert "audit worktree must be detached" in text
    assert "audit worktree is dirty" in text
    assert "audit worktree is not attached to primary repository" in text
    assert "audit worktree origin is not allowlisted" in text
    assert 'git -C "$PRIMARY" worktree remove "$WORKTREE"' in text
    assert 'git -C "$PRIMARY" worktree add --detach "$WORKTREE" "$TARGET_SHA"' in text
    assert "worktree remove --force" not in text
    assert "worktree remove -f" not in text


def test_reregister_preserves_primary_and_does_not_execute_audit() -> None:
    text = source()

    assert "verify_primary_unchanged" in text
    assert "PRIMARY_WORKTREE_UNCHANGED=true" in text
    assert "PRIMARY_INDEX_UNCHANGED=true" in text
    assert "AUDIT_EXECUTED=false" in text
    assert "NEXT_GITHUB_ACTION=apply audit:netto-object-card-graph-v1 to merged PR #411" in text

    assert 'sudo --non-interactive "$DISPATCHER"' not in text
    assert 'sudo -u github-runner -- sudo --non-interactive "$DISPATCHER"' not in text
    for forbidden in (
        'git -C "$PRIMARY" switch',
        'git -C "$PRIMARY" checkout',
        'git -C "$PRIMARY" reset',
        'git -C "$PRIMARY" clean',
        'git -C "$PRIMARY" stash',
        'git -C "$PRIMARY" pull',
        'git -C "$PRIMARY" merge',
        'git -C "$PRIMARY" rebase',
        "docker ",
        "systemctl ",
        "cloudflared ",
        "psql ",
    ):
        assert forbidden not in text


def test_reregister_keeps_root_boundary_bounded() -> None:
    text = source()
    sudo_lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith("sudo ")
    ]
    assert sudo_lines == [
        'sudo bash "$INSTALLER" "$TARGET_SHA" "$WORKTREE" 2>&1 | tee "$INSTALL_LOG"',
        'sudo visudo -cf "$SUDOERS" >/dev/null',
        'sudo -l -U github-runner > "$SUDO_LIST_LOG"',
        'sudo -u github-runner -- sudo --non-interactive -l "$DISPATCHER" >/dev/null',
    ]


def test_reregister_verifies_runtime_evidence_and_safety_markers() -> None:
    text = source()
    for marker in (
        "INSTALL_RESULT=PASS",
        "REGISTERED_SHA=$TARGET_SHA",
        "registered object-card graph commit mismatch",
        "registered N9 SHA mismatch",
        "N9 manifest SHA256 mismatch",
        "PyMuPDF 1.28.0 required",
        "github-runner unexpectedly belongs to Docker group",
        "DATABASE_WRITE=false",
        "REVIEW_WRITE=false",
        "APPROVAL_PUBLICATION=false",
        "PRODUCTION_DEPLOY=false",
        "OWNER_FINALIZER_RESULT=PASS",
    ):
        assert marker in text
