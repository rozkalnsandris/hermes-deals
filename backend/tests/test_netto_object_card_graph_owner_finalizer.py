from __future__ import annotations

# CI refresh: verify the unchanged owner-finalizer contract against the current main merge-ref.

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
FINALIZER = ROOT / "tools" / "runner" / "run-netto-object-card-graph-audit-owner-finalizer.sh"
TARGET_SHA = "3114135cf3d41c089b7ca5de7d134e725a9e1cd8"
WORKTREE = "/home/andris/hermes-deals-worktrees/netto-object-card-graph-audit-v1"
RUNTIME_ROOT = "/usr/local/libexec/hermes-deals-audits/netto-object-card-graph-audit-v1"
DISPATCHER = "/usr/local/sbin/hermes-deals-netto-object-card-graph-audit-dispatch"
CONFIG = "/etc/hermes-deals-audits.d/netto-object-card-graph-audit-v1.conf"
SUDOERS = "/etc/sudoers.d/hermes-deals-netto-object-card-graph-audit"
EXPECTED_N9_SHA = "2b180d67af4c5d1e586704088e3d685cff21ae2e12f3052254daf4553dd4e147"


def source() -> str:
    return FINALIZER.read_text(encoding="utf-8")


def test_finalizer_is_syntax_valid_and_pins_reviewed_bootstrap() -> None:
    text = source()
    subprocess.run(["bash", "-n", str(FINALIZER)], check=True)

    assert "FINALIZER_VERSION='netto-object-card-graph-audit-owner-finalizer-v1'" in text
    assert "SOURCE_PR='403'" in text
    assert f"TARGET_SHA='{TARGET_SHA}'" in text
    assert f"WORKTREE='{WORKTREE}'" in text
    assert "install-netto-object-card-graph-rpi5-audit.sh" in text
    assert f"RUNTIME_ROOT='{RUNTIME_ROOT}'" in text
    assert f"DISPATCHER='{DISPATCHER}'" in text
    assert f"CONFIG='{CONFIG}'" in text
    assert f"SUDOERS='{SUDOERS}'" in text
    assert f"EXPECTED_N9_SHA='{EXPECTED_N9_SHA}'" in text
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


def test_finalizer_installs_reviewed_root_trust_and_never_executes_audit() -> None:
    text = source()

    assert 'sudo bash "$INSTALLER" "$TARGET_SHA" "$WORKTREE"' in text
    assert 'sudo -u github-runner -- sudo --non-interactive -l "$DISPATCHER"' in text
    assert "AUDIT_EXECUTED=false" in text
    assert "NEXT_GITHUB_ACTION=apply audit:netto-object-card-graph-v1 to merged PR #403" in text

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


def test_finalizer_verifies_registered_runtime_and_safety_markers() -> None:
    text = source()

    for marker in (
        "INSTALL_RESULT=PASS",
        "REGISTERED_SHA=$TARGET_SHA",
        "root:root:755",
        "root:root:644",
        "root:root:440",
        "registered object-card graph commit mismatch",
        "registered N9 SHA mismatch",
        "N9 manifest SHA256 mismatch",
        "PyMuPDF 1.28.0 required",
        "PYMUPDF_VERSION=%s",
        "PYMUPDF_RUNTIME_USER=andris",
        "PYMUPDF_PYTHON=/usr/bin/python3",
        "RUNNER_HAS_DOCKER_GROUP=false",
        "DISPATCHER_AUTHORIZATION_CHECK=PASS",
        "DATABASE_WRITE=false",
        "REVIEW_WRITE=false",
        "APPROVAL_PUBLICATION=false",
        "PRODUCTION_DEPLOY=false",
        "OWNER_FINALIZER_RESULT=PASS",
    ):
        assert marker in text

    for runtime_member in (
        "netto_object_card_graph_audit.py",
        "netto_card_region_topology_audit.py",
        "netto_ownership_separator_audit.py",
        "netto_visual_geometry_corpus_replay.py",
        "netto_visual_geometry_shadow.py",
        "n2_independent_ownership_summary_v1.json",
    ):
        assert runtime_member in text

    assert "github-runner unexpectedly belongs to Docker group" in text


def test_finalizer_has_only_bounded_sudo_commands() -> None:
    text = source()
    root_lines = [line.strip() for line in text.splitlines() if line.strip().startswith("sudo ")]

    assert root_lines == [
        'sudo bash "$INSTALLER" "$TARGET_SHA" "$WORKTREE" 2>&1 | tee "$INSTALL_LOG"',
        'sudo visudo -cf "$SUDOERS" >/dev/null',
        'sudo -l -U github-runner > "$SUDO_LIST_LOG"',
        'sudo -u github-runner -- sudo --non-interactive -l "$DISPATCHER" >/dev/null',
    ]
