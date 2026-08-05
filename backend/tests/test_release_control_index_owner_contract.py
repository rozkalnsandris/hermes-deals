from __future__ import annotations

import pathlib
import subprocess


ROOT = pathlib.Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "tools/runner/install-rpi5-release-dispatcher.sh"


def test_release_installer_runs_worktree_git_as_andris() -> None:
    subprocess.run(["bash", "-n", str(INSTALLER)], check=True)
    text = INSTALLER.read_text(encoding="utf-8")

    for marker in (
        "SOURCE_OWNER='andris'",
        "SOURCE_HOME='/home/andris'",
        "run_owner_git()",
        'runuser -u "$SOURCE_OWNER" -- env',
        'HOME="$SOURCE_HOME"',
        'run_owner_git status --porcelain=v1 --untracked-files=all',
        'run_owner_git ls-files --error-unmatch',
        "release source index ownership is invalid",
        "release source index ownership changed during installation",
    ):
        assert marker in text

    # The only direct Git invocation against the detached worktree must live
    # inside run_owner_git; all installer checks call that owner-scoped helper.
    assert text.count('git -C "$SOURCE_WORKTREE"') == 1


def test_release_installer_keeps_root_only_for_runtime_installation() -> None:
    text = INSTALLER.read_text(encoding="utf-8")

    for marker in (
        'install -o root -g root -m 0755 "$SOURCE_DISPATCHER" "$DISPATCHER"',
        'install -o root -g root -m 0755 "$SOURCE_REGISTER" "$REGISTER"',
        'install -o root -g root -m 0755 "$SOURCE_BRIDGE" "$BRIDGE"',
        'install -o root -g root -m 0755 "$SOURCE_AUTO_REGISTER" "$AUTO_REGISTER"',
        "DATABASE_WRITES_AUTHORIZED=false",
    ):
        assert marker in text

    for forbidden in (
        "alembic upgrade",
        "alembic downgrade",
        "docker compose up",
        "git reset",
        "git clean",
    ):
        assert forbidden not in text
