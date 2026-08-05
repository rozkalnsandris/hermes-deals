from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "tools/runner/install-netto-shadow-rpi5-audit-worktree.sh"


def test_worktree_installer_has_valid_bash_syntax() -> None:
    subprocess.run(["bash", "-n", str(INSTALLER)], check=True)


def test_worktree_installer_is_narrowly_bound() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    assert "/home/andris/hermes-deals-worktrees/netto-shadow-audit-install" in text
    assert "PRIMARY_GIT_COMMON_DIR='/home/andris/hermes-deals/.git'" in text
    assert "source worktree branch must be main" in text
    assert "source worktree HEAD mismatch" in text
    assert "source worktree is not clean" in text
    assert "source is not a worktree of /home/andris/hermes-deals" in text
    assert "source origin is not the Hermes Deals repository" in text


def test_worktree_installer_uses_deterministic_exact_transforms() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    assert "def replace_once" in text
    assert "expected exactly one replacement" in text
    assert "REPO='/home/andris/hermes-deals'" in text
    assert "registration source is not a Git checkout" in text
    assert "Hermes Deals repository is unavailable" in text
    assert 'Path("/home/andris/hermes-deals")' in text
    assert "source_repo='$SOURCE_REPO'" in text


def test_worktree_installer_preserves_read_only_boundary() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    for forbidden in (
        "docker exec",
        "docker compose",
        "psql ",
        "git reset --hard",
        "git clean",
        "systemctl enable",
    ):
        assert forbidden not in text
    assert "PRODUCTION_APPLY_AUTHORIZED=false" in text
    assert "RUNNER_HAS_DOCKER_GROUP=false" in text
    assert "/usr/local/sbin/hermes-deals-netto-shadow-audit-dispatch" in text
