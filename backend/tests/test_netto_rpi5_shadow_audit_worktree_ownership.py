from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "tools/runner/install-netto-shadow-rpi5-audit-worktree-v2.sh"


def test_v2_installer_has_valid_bash_syntax() -> None:
    subprocess.run(["bash", "-n", str(INSTALLER)], check=True)


def test_v2_repairs_only_the_exact_validated_worktree_metadata() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    expected_admin = (
        'WORKTREE_ADMIN="$PRIMARY_GIT_COMMON_DIR/worktrees/'
        'netto-shadow-audit-install"'
    )
    assert expected_admin in text
    assert '[[ "$(cat "$WORKTREE_DOT_GIT")" == "gitdir: $WORKTREE_ADMIN" ]]' in text
    assert '[[ "$COMMON_DIR" == "$PRIMARY_GIT_COMMON_DIR" ]]' in text
    assert '[[ "$GITDIR_TARGET" == "$WORKTREE_DOT_GIT" ]]' in text
    assert 'chown -R andris:andris "$WORKTREE_ADMIN"' in text
    assert text.index("dedicated worktree .git pointer mismatch") < text.index(
        'chown -R andris:andris "$WORKTREE_ADMIN"'
    )


def test_v2_suppresses_root_index_refresh_and_checks_as_andris() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    assert "export GIT_OPTIONAL_LOCKS=0" in text
    assert "runuser -u andris -- /usr/bin/env" in text
    assert 'if ! STATUS_OUTPUT="$(runuser -u andris' in text
    assert "andris cannot read dedicated worktree after installation" in text
    assert '[[ -z "$STATUS_OUTPUT" ]]' in text
    assert '[[ "$INDEX_PATH" == "$WORKTREE_ADMIN/index" ]]' in text
    assert "WORKTREE_INDEX_OWNERSHIP=andris:andris" in text


def test_v2_preserves_read_only_audit_boundary() -> None:
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
    assert 'V1_INSTALLER="$SOURCE_REPO/tools/runner/' in text

