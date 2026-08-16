from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "runner" / "install_aldi_gate_d4_backup_discovery_nonrewind_v3.py"


def load_module():
    spec = importlib.util.spec_from_file_location("aldi_gate_d4_registration_v3_tested", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeBase:
    def __init__(self, module, *, dispatcher_blob: str | None = None):
        self.module = module
        self.dispatcher_blob = dispatcher_blob or module.EXPECTED_DISPATCHER_BLOB
        self.before = ("andris:andris", 0o644, 123, "a" * 64)
        self.head = "b" * 40
        self.EXPECTED_DISPATCHER_BLOB = "old"
        self.validate_source_repo = None
        self.main_calls = 0

    def index_snapshot(self):
        return self.before

    def audit_git(self, *args, check=True):
        key = args
        stdout = b""
        stderr = b""
        returncode = 0
        if key == ("branch", "--show-current"):
            stdout = b"main\n"
        elif key == ("rev-parse", "HEAD"):
            stdout = (self.head + "\n").encode()
        elif key == ("status", "--porcelain=v1", "-z", "--untracked-files=all"):
            stdout = b""
        elif key == ("rev-parse", "--verify", f"{self.module.EXPECTED_TARGET_SHA}^{{commit}}"):
            stdout = (self.module.EXPECTED_TARGET_SHA + "\n").encode()
        elif key == ("merge-base", "--is-ancestor", self.module.EXPECTED_TARGET_SHA, self.head):
            returncode = 0
        elif key == ("rev-parse", f"{self.module.EXPECTED_TARGET_SHA}:{self.module.D4_PATH}"):
            stdout = (self.module.EXPECTED_D4_BLOB + "\n").encode()
        elif key == ("rev-parse", f"{self.module.EXPECTED_TARGET_SHA}:{self.module.D3_PATH}"):
            stdout = (self.module.EXPECTED_D3_BLOB + "\n").encode()
        elif key == ("rev-parse", f"HEAD:{self.module.BASE_INSTALLER_PATH}"):
            stdout = (self.module.EXPECTED_BASE_INSTALLER_BLOB + "\n").encode()
        elif key == ("rev-parse", f"HEAD:{self.module.DISPATCHER_PATH}"):
            stdout = (self.dispatcher_blob + "\n").encode()
        elif key == ("rev-parse", f"HEAD:{self.module.INSTALLER_PATH}"):
            stdout = b"installer-blob\n"
        elif key == ("cat-file", "blob", "installer-blob"):
            stdout = TOOL.read_bytes()
        else:
            raise AssertionError(f"unexpected git call: {key}")
        return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)

    def main(self):
        self.main_calls += 1
        assert self.EXPECTED_DISPATCHER_BLOB == self.module.EXPECTED_DISPATCHER_BLOB
        assert callable(self.validate_source_repo)
        self.validate_source_repo(self.module.EXPECTED_TARGET_SHA)
        return 0


def test_v3_pins_old_runtime_but_new_dispatcher_blob():
    module = load_module()
    assert module.EXPECTED_TARGET_SHA == "8b9b7e66c754cb7f8a82d4d67503d59fd2ff000e"
    assert module.EXPECTED_D4_BLOB == "f8ec4abb3f0c416335144f0f18e8a7c323353f4a"
    assert module.EXPECTED_D3_BLOB == "4c4432baa048011ac9dfd427d8e2a0d0b4cfd2a7"
    assert module.EXPECTED_BASE_INSTALLER_BLOB == "de9048513e26c6de49d7c8ee4db4eb9e1bd6bbf1"
    assert module.EXPECTED_DISPATCHER_BLOB == "f76ab8dfa938162dea038a2ef981c9002d5382e5"


def test_v3_source_validation_binds_runtime_to_target_and_dispatcher_to_head():
    module = load_module()
    base = FakeBase(module)
    before, head = module.validate_source_repo(base, module.EXPECTED_TARGET_SHA)
    assert before == base.before
    assert head == base.head


def test_v3_source_validation_rejects_dispatcher_head_drift():
    module = load_module()
    base = FakeBase(module, dispatcher_blob="0" * 40)
    with pytest.raises(module.RegistrationV3Error, match="dispatcher blob drift"):
        module.validate_source_repo(base, module.EXPECTED_TARGET_SHA)


def test_main_overrides_only_dispatcher_pin_and_delegates_registration(monkeypatch):
    module = load_module()
    base = FakeBase(module)
    monkeypatch.setattr(module, "load_base", lambda: base)
    assert module.main() == 0
    assert base.main_calls == 1


def test_v3_source_has_no_discovery_or_permission_relaxation_surface():
    source = TOOL.read_text(encoding="utf-8")
    for forbidden in (
        "/opt/backups",
        "chmod(",
        "chown(",
        "setfacl",
        "mount --bind",
        "systemctl",
        "subprocess.run",
    ):
        assert forbidden not in source
