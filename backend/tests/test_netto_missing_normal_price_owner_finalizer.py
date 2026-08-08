from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
FINALIZER = ROOT / "tools" / "runner" / "run-netto-missing-normal-price-audit-owner-finalizer.sh"
TARGET_SHA = "150a95a72a423201195df567184a98acec4d52be"
WORKTREE = "/home/andris/hermes-deals-worktrees/netto-missing-normal-price-audit-v1"
RUNTIME_ROOT = "/usr/local/libexec/hermes-deals-audits/netto-missing-normal-price-audit-v1"
DISPATCHER = "/usr/local/sbin/hermes-deals-netto-missing-normal-price-audit-dispatch"
CONFIG = "/etc/hermes-deals-audits.d/netto-missing-normal-price-audit-v1.conf"
SUDOERS = "/etc/sudoers.d/hermes-deals-netto-missing-normal-price-audit"
EXPECTED_N9_SHA = "2b180d67af4c5d1e586704088e3d685cff21ae2e12f3052254daf4553dd4e147"
EXPECTED_N10_SHA = "bf35bff323d76a2b29a7248df067641e5b9f2a7d29329cf53bf9fc0ae832734a"


def source() -> str:
    return FINALIZER.read_text(encoding="utf-8")


def test_finalizer_is_syntax_valid_and_pins_reviewed_bootstrap() -> None:
    text = source()
    subprocess.run(["bash", "-n", str(FINALIZER)], check=True)

    assert "FINALIZER_VERSION='netto-missing-normal-price-audit-owner-finalizer-v1'" in text
    assert "SOURCE_PR='438'" in text
    assert f"TARGET_SHA='{TARGET_SHA}'" in text
    assert f"WORKTREE='{WORKTREE}'" in text
    assert "install-netto-missing-normal-price-rpi5-audit.sh" in text
    assert f"RUNTIME_ROOT='{RUNTIME_ROOT}'" in text
    assert f"DISPATCHER='{DISPATCHER}'" in text
    assert f"CONFIG='{CONFIG}'" in text
    assert f"SUDOERS='{SUDOERS}'" in text
    assert f"EXPECTED_N9_SHA='{EXPECTED_N9_SHA}'" in text
    assert f"EXPECTED_N10_SHA='{EXPECTED_N10_SHA}'" in text
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


def test_finalizer_installs_only_reviewed_root_trust_and_never_executes_audit() -> None:
    text = source()

    assert 'sudo bash "$INSTALLER" "$TARGET_SHA" "$WORKTREE"' in text
    assert 'sudo --non-interactive -u github-runner -- sudo --non-interactive -l "$DISPATCHER"' in text
    assert "AUDIT_EXECUTED=false" in text
    assert "NEXT_GITHUB_ACTION=apply audit:netto-missing-normal-price-v1 to merged PR #438" in text

    assert 'sudo --non-interactive "$DISPATCHER"' not in text
    assert 'sudo --non-interactive -u github-runner -- sudo --non-interactive "$DISPATCHER"' not in text

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
        "PYMUPDF_VERSION=1.28.0",
        "root:root:755",
        "root:root:644",
        "root:root:440",
        "registered missing-normal-price commit mismatch",
        "registered N9 SHA mismatch",
        "registered N10 SHA mismatch",
        "N9 manifest SHA256 mismatch",
        "N10 ledger SHA256 mismatch",
        "immutable corpus root is unavailable or unsafe",
        "PyMuPDF 1.28.0 required",
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
        "netto_missing_normal_price_audit.py",
        "netto_visual_geometry_corpus_replay.py",
        "netto_visual_geometry_shadow.py",
        "n10_full_visual_review_v1.json",
    ):
        assert runtime_member in text

    assert "github-runner unexpectedly belongs to Docker group" in text


def test_finalizer_has_only_bounded_sudo_commands() -> None:
    text = source()
    root_lines = [line.strip() for line in text.splitlines() if line.strip().startswith("sudo ")]

    assert root_lines == [
        'sudo bash "$INSTALLER" "$TARGET_SHA" "$WORKTREE" 2>&1 | tee "$INSTALL_LOG"',
        'sudo --non-interactive visudo -cf "$SUDOERS" >/dev/null',
        'sudo --non-interactive -l -U github-runner > "$SUDO_LIST_LOG"',
        'sudo --non-interactive -u github-runner -- sudo --non-interactive -l "$DISPATCHER" >/dev/null',
    ]
    assert all("--non-interactive" in line for line in root_lines[1:])
