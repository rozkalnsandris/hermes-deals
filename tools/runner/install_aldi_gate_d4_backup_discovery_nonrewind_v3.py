#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

BASE_INSTALLER_PATH = "tools/runner/install_aldi_gate_d4_backup_discovery_nonrewind.py"
INSTALLER_PATH = "tools/runner/install_aldi_gate_d4_backup_discovery_nonrewind_v3.py"
DISPATCHER_PATH = "tools/runner/aldi_gate_d4_backup_discovery_dispatch.py"
D4_PATH = "tools/aldi_gate_d4_backup_discovery.py"
D3_PATH = "tools/aldi_gate_d3_recovery_inventory.py"
EXPECTED_TARGET_SHA = "8b9b7e66c754cb7f8a82d4d67503d59fd2ff000e"
EXPECTED_D4_BLOB = "f8ec4abb3f0c416335144f0f18e8a7c323353f4a"
EXPECTED_D3_BLOB = "4c4432baa048011ac9dfd427d8e2a0d0b4cfd2a7"
EXPECTED_BASE_INSTALLER_BLOB = "de9048513e26c6de49d7c8ee4db4eb9e1bd6bbf1"
EXPECTED_DISPATCHER_BLOB = "f76ab8dfa938162dea038a2ef981c9002d5382e5"
BASE_FILE = Path(__file__).with_name("install_aldi_gate_d4_backup_discovery_nonrewind.py")


class RegistrationV3Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RegistrationV3Error(message)


def load_base() -> ModuleType:
    require(BASE_FILE.is_file() and not BASE_FILE.is_symlink(), "base installer missing or unsafe")
    spec = importlib.util.spec_from_file_location("aldi_gate_d4_registration_base_v2", BASE_FILE)
    require(spec is not None and spec.loader is not None, "base installer import unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    require(module.EXPECTED_TARGET_SHA == EXPECTED_TARGET_SHA, "base target pin drift")
    require(module.EXPECTED_D4_BLOB == EXPECTED_D4_BLOB, "base D4 pin drift")
    require(module.EXPECTED_D3_BLOB == EXPECTED_D3_BLOB, "base D3 pin drift")
    return module


def _text(base: Any, *args: str) -> str:
    return base.audit_git(*args).stdout.decode().strip()


def validate_source_repo(base: Any, target_sha: str):
    require(target_sha == EXPECTED_TARGET_SHA, "target SHA is not reviewed Gate D4 runtime SHA")
    before = base.index_snapshot()
    require(_text(base, "branch", "--show-current") == "main", "audit repo branch mismatch")
    head = _text(base, "rev-parse", "HEAD")
    require(len(head) == 40, "audit repo HEAD invalid")
    require(base.audit_git("status", "--porcelain=v1", "-z", "--untracked-files=all").stdout == b"", "audit repo dirty")

    target = _text(base, "rev-parse", "--verify", f"{target_sha}^{{commit}}")
    require(target == target_sha, "reviewed target commit object unavailable")
    ancestry = base.audit_git("merge-base", "--is-ancestor", target_sha, head, check=False)
    require(ancestry.returncode == 0, "reviewed target is not an ancestor of audit repo HEAD")
    require(not ancestry.stderr, "ancestry check emitted stderr")

    for path, blob in ((D4_PATH, EXPECTED_D4_BLOB), (D3_PATH, EXPECTED_D3_BLOB)):
        require(_text(base, "rev-parse", f"{target_sha}:{path}") == blob, f"reviewed Git blob mismatch: {path}")
    require(_text(base, "rev-parse", f"HEAD:{BASE_INSTALLER_PATH}") == EXPECTED_BASE_INSTALLER_BLOB, "base installer blob drift")
    require(_text(base, "rev-parse", f"HEAD:{DISPATCHER_PATH}") == EXPECTED_DISPATCHER_BLOB, "dispatcher blob drift")

    installer_blob = _text(base, "rev-parse", f"HEAD:{INSTALLER_PATH}")
    require(installer_blob, "v3 installer blob unavailable")
    installed_source = base.audit_git("cat-file", "blob", installer_blob).stdout
    require(installed_source == Path(__file__).read_bytes(), "v3 installer working-tree identity drift")
    require(base.index_snapshot() == before, "audit repo index changed during source validation")
    return before, head


def main() -> int:
    base = load_base()
    base.EXPECTED_DISPATCHER_BLOB = EXPECTED_DISPATCHER_BLOB
    base.validate_source_repo = lambda target_sha: validate_source_repo(base, target_sha)
    return int(base.main())


if __name__ == "__main__":
    raise SystemExit(main())
