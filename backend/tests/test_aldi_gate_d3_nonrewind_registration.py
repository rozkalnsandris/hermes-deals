from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "runner" / "install_aldi_gate_d3_recovery_inventory_nonrewind.py"


def load_module():
    spec = importlib.util.spec_from_file_location("aldi_gate_d3_nonrewind_registration", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def completed(stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
    return subprocess.CompletedProcess(args=["git"], returncode=returncode, stdout=stdout, stderr=stderr)


def test_nonrewind_registration_is_bound_to_exact_pr281_identity() -> None:
    module = load_module()

    assert module.EXPECTED_TARGET_SHA == "530a6b6d2b31f635f182788ccace01003b1cbc7d"
    assert module.EXPECTED_INVENTORY_BLOB == "4c4432baa048011ac9dfd427d8e2a0d0b4cfd2a7"
    assert module.EXPECTED_DISPATCHER_BLOB == "70c56f6ff883415a18949c6298be4affe8f8ac0d"
    assert module.INVENTORY_PATH == "tools/aldi_gate_d3_recovery_inventory.py"
    assert module.DISPATCHER_PATH == "tools/runner/aldi_gate_d3_recovery_inventory_dispatch.py"


def test_source_contains_no_repo_rewind_or_network_git_operation() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    forbidden = (
        '"fetch"',
        '"checkout"',
        '"reset"',
        '"switch"',
        '"merge", "--ff-only"',
        "reset --hard",
        "checkout -f",
    )
    for marker in forbidden:
        assert marker not in source

    assert '"merge-base", "--is-ancestor"' in source
    assert '"cat-file", "blob"' in source
    assert '"status", "--porcelain=v1", "-z", "--untracked-files=all"' in source
    assert 'GIT_OPTIONAL_LOCKS=0' in source


def test_validate_source_repo_accepts_descendant_head_without_moving_it(monkeypatch) -> None:
    module = load_module()
    target = module.EXPECTED_TARGET_SHA
    head = "f7e728438b3beee03481564665163c11ad09ef44"
    snapshot = ("andris:andris", 0o644, 1234, "a" * 64)
    calls: list[tuple[str, ...]] = []

    def fake_index_snapshot():
        return snapshot

    def fake_audit_git(*args: str, check: bool = True):
        calls.append(tuple(args))
        if args == ("branch", "--show-current"):
            return completed(b"main\n")
        if args == ("rev-parse", "HEAD"):
            return completed((head + "\n").encode())
        if args == ("status", "--porcelain=v1", "-z", "--untracked-files=all"):
            return completed(b"")
        if args == ("rev-parse", "--verify", f"{target}^{{commit}}"):
            return completed((target + "\n").encode())
        if args == ("merge-base", "--is-ancestor", target, head):
            return completed(returncode=0)
        if args == ("rev-parse", f"{target}:{module.INVENTORY_PATH}"):
            return completed((module.EXPECTED_INVENTORY_BLOB + "\n").encode())
        if args == ("rev-parse", f"{target}:{module.DISPATCHER_PATH}"):
            return completed((module.EXPECTED_DISPATCHER_BLOB + "\n").encode())
        raise AssertionError(args)

    monkeypatch.setattr(module, "index_snapshot", fake_index_snapshot)
    monkeypatch.setattr(module, "audit_git", fake_audit_git)

    before, observed_head = module.validate_source_repo(target)

    assert before == snapshot
    assert observed_head == head
    assert not any(call and call[0] in {"fetch", "checkout", "reset", "switch", "merge"} for call in calls)


def test_validate_source_repo_rejects_non_descendant_target(monkeypatch) -> None:
    module = load_module()
    target = module.EXPECTED_TARGET_SHA
    head = "f7e728438b3beee03481564665163c11ad09ef44"
    snapshot = ("andris:andris", 0o644, 1234, "a" * 64)

    monkeypatch.setattr(module, "index_snapshot", lambda: snapshot)

    def fake_audit_git(*args: str, check: bool = True):
        if args == ("branch", "--show-current"):
            return completed(b"main\n")
        if args == ("rev-parse", "HEAD"):
            return completed((head + "\n").encode())
        if args == ("status", "--porcelain=v1", "-z", "--untracked-files=all"):
            return completed(b"")
        if args == ("rev-parse", "--verify", f"{target}^{{commit}}"):
            return completed((target + "\n").encode())
        if args == ("merge-base", "--is-ancestor", target, head):
            return completed(returncode=1)
        raise AssertionError(args)

    monkeypatch.setattr(module, "audit_git", fake_audit_git)

    with pytest.raises(module.RegistrationError, match="not an ancestor"):
        module.validate_source_repo(target)


def test_validate_source_repo_rejects_blob_identity_drift(monkeypatch) -> None:
    module = load_module()
    target = module.EXPECTED_TARGET_SHA
    head = "f7e728438b3beee03481564665163c11ad09ef44"
    snapshot = ("andris:andris", 0o644, 1234, "a" * 64)

    monkeypatch.setattr(module, "index_snapshot", lambda: snapshot)

    def fake_audit_git(*args: str, check: bool = True):
        if args == ("branch", "--show-current"):
            return completed(b"main\n")
        if args == ("rev-parse", "HEAD"):
            return completed((head + "\n").encode())
        if args == ("status", "--porcelain=v1", "-z", "--untracked-files=all"):
            return completed(b"")
        if args == ("rev-parse", "--verify", f"{target}^{{commit}}"):
            return completed((target + "\n").encode())
        if args == ("merge-base", "--is-ancestor", target, head):
            return completed(returncode=0)
        if args == ("rev-parse", f"{target}:{module.INVENTORY_PATH}"):
            return completed(("0" * 40 + "\n").encode())
        if args == ("rev-parse", f"{target}:{module.DISPATCHER_PATH}"):
            return completed((module.EXPECTED_DISPATCHER_BLOB + "\n").encode())
        raise AssertionError(args)

    monkeypatch.setattr(module, "audit_git", fake_audit_git)

    with pytest.raises(module.RegistrationError, match="inventory Git blob mismatch"):
        module.validate_source_repo(target)


def test_config_authority_flags_remain_false() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for key in (
        "raw_evidence_export_authorized",
        "raw_exception_export_authorized",
        "archive_extraction_authorized",
        "review_pack_execution_authorized",
        "production_apply_authorized",
    ):
        assert f'"{key}": False' in source
