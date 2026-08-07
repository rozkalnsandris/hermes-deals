from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEDICATED = "/home/andris/hermes-deals-audit-source-lidl"
SHARED = "/home/andris/hermes-deals-audit-source"

RUNTIME_PATHS = (
    ROOT / "tools" / "run-hermes-deals-lidl-weekly-gate-a-v01.sh",
    ROOT / "tools" / "runner" / "install-lidl-weekly-gate-a-dispatcher.sh",
    ROOT / "tools" / "runner" / "run-lidl-weekly-gate-a-owner-finalizer-v01.sh",
)


def test_lidl_gate_a_uses_only_dedicated_audit_clone() -> None:
    for path in RUNTIME_PATHS:
        text = path.read_text(encoding="utf-8")
        assert DEDICATED in text, path
        assert f"AUDIT_REPO='{SHARED}'" not in text, path
        assert f'AUDIT_REPO="{SHARED}"' not in text, path


def test_lidl_dedicated_clone_keeps_unprivileged_read_only_git_checks() -> None:
    runner = RUNTIME_PATHS[0].read_text(encoding="utf-8")
    installer = RUNTIME_PATHS[1].read_text(encoding="utf-8")
    finalizer = RUNTIME_PATHS[2].read_text(encoding="utf-8")

    assert "runuser -u andris -- env HOME=/home/andris GIT_OPTIONAL_LOCKS=0" in runner
    assert "runuser -u andris -- env HOME=/home/andris GIT_OPTIONAL_LOCKS=0" in installer
    assert "GIT_OPTIONAL_LOCKS=0 git -C" in finalizer

    assert "audit origin is not allowlisted" in runner
    assert "AUDIT_INDEX_SHA_BEFORE=" in runner
    assert "AUDIT_GIT_INDEX_UNCHANGED=true" in runner

    assert "audit origin is not allowlisted" in installer
    assert "INDEX_SHA_BEFORE=" in installer
    assert "AUDIT_GIT_INDEX_UNCHANGED=true" in installer

    assert "audit repository origin is not allowlisted" in finalizer
    assert "AUDIT_INDEX_REGISTERED=" in finalizer
    assert "AUDIT_INDEX_STATE_REGISTERED=" in finalizer
