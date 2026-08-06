from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
FINALIZER = ROOT / "tools" / "runner" / "run-lidl-weekly-gate-a-owner-finalizer-v01.sh"


def test_owner_finalizer_uses_runtime_snapshot_invariance() -> None:
    subprocess.run(["bash", "-n", str(FINALIZER)], check=True)
    text = FINALIZER.read_text(encoding="utf-8")

    assert "PRIMARY_EXPECTED_BRANCH" not in text
    assert "PRIMARY_EXPECTED_HEAD" not in text
    assert "protected primary branch differs from expected baseline" not in text
    assert "protected primary HEAD differs from expected baseline" not in text

    for marker in (
        "PRIMARY_BRANCH_BEFORE=",
        "PRIMARY_HEAD_BEFORE=",
        "PRIMARY_STATUS_SHA256_BEFORE=",
        "PRIMARY_INDEX_PATH_BEFORE=",
        "PRIMARY_INDEX_STATE_BEFORE=",
        "PRIMARY_V08_STATE_BEFORE=",
        "PRIMARY_GIT_STDERR_POLICY=empty-required",
        "PRIMARY_INDEX_VERIFIED_UNCHANGED=true",
        "PRIMARY_INDEX_VERIFIED_UNCHANGED_AFTER_WORKFLOW=true",
        "Git read failed closed or wrote to stderr",
        "primary Git index path changed",
        "primary Git index changed",
        "primary worktree status changed",
        "protected B15M2 V08 file changed",
        "AUDIT_INDEX_STATE_REGISTERED=",
        "audit Git index content changed",
    ):
        assert marker in text


def test_missing_v08_is_a_protected_snapshot_state() -> None:
    text = FINALIZER.read_text(encoding="utf-8")
    file_state = text.split("file_state() {", 1)[1].split("\n}\n\nverify_primary_unchanged", 1)[0]

    assert 'if [[ ! -e "$path" ]]; then' in file_state
    assert "printf 'missing\\n'" in file_state
    assert "return" in file_state
    assert 'PRIMARY_V08_BEFORE="$(file_state "$V08_SCRIPT")"' in text
    assert 'v08_now="$(file_state "$V08_SCRIPT")"' in text
    assert '[[ "$v08_now" == "$PRIMARY_V08_BEFORE" ]]' in text


def test_primary_worktree_has_no_mutating_git_operations() -> None:
    text = FINALIZER.read_text(encoding="utf-8")
    for forbidden in (
        'git -C "$PRIMARY" switch',
        'git -C "$PRIMARY" checkout',
        'git -C "$PRIMARY" reset',
        'git -C "$PRIMARY" stash',
        'git -C "$PRIMARY" clean',
        'git -C "$PRIMARY" pull',
        'git -C "$PRIMARY" fetch',
        'git -C "$PRIMARY" merge',
        'git -C "$PRIMARY" rebase',
    ):
        assert forbidden not in text
