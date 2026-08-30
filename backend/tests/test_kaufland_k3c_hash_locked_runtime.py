from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
BUILDER = ROOT / "tools/runner/build-kaufland-k3c-python-runtime.sh"
CONTRACT = ROOT / "tools/runner/kaufland_k3c_python_runtime_contract.py"
BOOTSTRAP = ROOT / "tools/runner/kaufland-k3c-python-bootstrap.json"
INSTALLER = ROOT / "tools/runner/install-kaufland-k3c-promo-structure-rpi5-bridge.sh"
WORKFLOW = ROOT / ".github/workflows/kaufland-k3c-promo-structure-rpi5.yml"
CI_WORKFLOW = ROOT / ".github/workflows/ci.yml"
LOCK_WORKFLOW = ROOT / ".github/workflows/python-dependency-locks.yml"
LOCK_COMPILER = ROOT / "scripts/compile-python-locks.sh"
LOCK_MANIFEST = ROOT / "backend/locks/manifest.json"
DOCKERFILE = ROOT / "backend/Dockerfile"

_spec = importlib.util.spec_from_file_location("kaufland_k3c_python_runtime_contract", CONTRACT)
assert _spec is not None and _spec.loader is not None
runtime_contract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runtime_contract)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _tar(path: Path, members: list[tarfile.TarInfo]) -> None:
    with tarfile.open(path, "w:gz") as bundle:
        for member in members:
            if member.isfile():
                payload = b"payload"
                member.size = len(payload)
                bundle.addfile(member, io.BytesIO(payload))
            else:
                bundle.addfile(member)


def test_runtime_tree_fingerprint_is_deterministic_and_byte_sensitive(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    (root / "lib").mkdir(parents=True)
    artifact = root / "lib" / "module.py"
    artifact.write_text("value = 1\n", encoding="utf-8")
    first = runtime_contract.runtime_tree_sha256(root)
    assert runtime_contract.runtime_tree_sha256(root) == first
    assert len(first) == 64
    artifact.write_text("value = 2\n", encoding="utf-8")
    assert runtime_contract.runtime_tree_sha256(root) != first


def test_runtime_tree_rejects_symlink_escape_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")
    (root / "escape").symlink_to(Path("..") / "outside.txt")
    with pytest.raises(runtime_contract.RuntimeContractError, match="symlink escapes runtime root"):
        runtime_contract.runtime_tree_sha256(root)


def test_runtime_tree_cli_turns_unsafe_path_into_controlled_rc20(tmp_path: Path, capsys) -> None:
    root = tmp_path / "runtime"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")
    (root / "escape").symlink_to(Path("..") / "outside.txt")
    rc = runtime_contract.main(["tree-sha", "--root", str(root)])
    captured = capsys.readouterr()
    assert rc == 20
    assert "symlink escapes runtime root" in captured.err
    assert "Traceback" not in captured.err


def test_bootstrap_manifest_pins_exact_immutable_asset() -> None:
    payload = json.loads(_text(BOOTSTRAP))
    assert payload["contract_version"] == "kaufland-k3c-python-bootstrap-v1"
    assert payload["provider"] == "astral-sh/python-build-standalone"
    assert payload["release"] == {
        "tag": "20260805",
        "release_id": 365709887,
        "target_commit": "76b41240bc8dfe753a54b2e32c8941e536568be8",
        "immutable": True,
    }
    assert payload["asset"]["asset_id"] == 502923386
    assert payload["asset"]["name"] == "cpython-3.13.14+20260805-aarch64-unknown-linux-gnu-install_only.tar.gz"
    assert payload["asset"]["size"] == 89958991
    assert payload["asset"]["sha256"] == "4777d7df2edb47b96e53abad5e1b9df1b2a1a9b2f7bdba12b5c0122163b3fed9"
    assert payload["python"] == {
        "implementation": "CPython",
        "version": "3.13.14",
        "line": "3.13",
        "executable": "python/bin/python3.13",
    }
    assert payload["platform"] == {"os": "linux", "architecture": "aarch64"}
    runtime_contract.load_bootstrap_manifest(BOOTSTRAP)


def test_safe_bootstrap_extract_accepts_python_tree(tmp_path: Path) -> None:
    archive = tmp_path / "runtime.tar.gz"
    directory = tarfile.TarInfo("python")
    directory.type = tarfile.DIRTYPE
    file_member = tarfile.TarInfo("python/bin/python3.13")
    file_member.mode = 0o755
    _tar(archive, [directory, file_member])
    destination = tmp_path / "out"
    destination.mkdir()
    runtime_contract.safe_extract_bootstrap(archive, destination)
    assert (destination / "python/bin/python3.13").read_bytes() == b"payload"


@pytest.mark.parametrize(
    ("name", "kind", "linkname", "message"),
    [
        ("../escape", tarfile.REGTYPE, "", "tar path traversal"),
        ("/absolute", tarfile.REGTYPE, "", "absolute tar member"),
        ("python/fifo", tarfile.FIFOTYPE, "", "special tar member"),
        ("python/device", tarfile.CHRTYPE, "", "special tar member"),
        ("python/hard", tarfile.LNKTYPE, "python/bin/python3.13", "hardlink tar member"),
        ("python/link", tarfile.SYMTYPE, "../../outside", "tar link escapes python root"),
    ],
)
def test_safe_bootstrap_extract_rejects_unsafe_members(tmp_path: Path, name: str, kind: bytes, linkname: str, message: str) -> None:
    archive = tmp_path / "runtime.tar.gz"
    member = tarfile.TarInfo(name)
    member.type = kind
    member.linkname = linkname
    _tar(archive, [member])
    destination = tmp_path / "out"
    destination.mkdir()
    with pytest.raises(runtime_contract.RuntimeContractError, match=message):
        runtime_contract.safe_extract_bootstrap(archive, destination)


def test_safe_bootstrap_extract_rejects_duplicate_members(tmp_path: Path) -> None:
    archive = tmp_path / "runtime.tar.gz"
    first = tarfile.TarInfo("python/bin/python3.13")
    second = tarfile.TarInfo("python/bin/python3.13")
    _tar(archive, [first, second])
    destination = tmp_path / "out"
    destination.mkdir()
    with pytest.raises(runtime_contract.RuntimeContractError, match="duplicate tar member"):
        runtime_contract.safe_extract_bootstrap(archive, destination)


def test_safe_bootstrap_extract_rejects_member_below_symlink_parent(tmp_path: Path) -> None:
    archive = tmp_path / "runtime.tar.gz"
    link = tarfile.TarInfo("python/lib")
    link.type = tarfile.SYMTYPE
    link.linkname = "share"
    nested = tarfile.TarInfo("python/lib/escape.txt")
    _tar(archive, [nested, link])
    destination = tmp_path / "out"
    destination.mkdir()
    with pytest.raises(runtime_contract.RuntimeContractError, match="nested below symlink parent"):
        runtime_contract.safe_extract_bootstrap(archive, destination)


def test_safe_bootstrap_extract_rejects_preexisting_runtime_root(tmp_path: Path) -> None:
    archive = tmp_path / "runtime.tar.gz"
    member = tarfile.TarInfo("python/bin/python3.13")
    _tar(archive, [member])
    destination = tmp_path / "out"
    (destination / "python").mkdir(parents=True)
    with pytest.raises(runtime_contract.RuntimeContractError, match="runtime root already exists"):
        runtime_contract.safe_extract_bootstrap(archive, destination)


def test_builder_bootstraps_canonical_py313_without_host_venv_dependency() -> None:
    source = _text(BUILDER)
    for marker in (
        "BOOTSTRAP_REL='tools/runner/kaufland-k3c-python-bootstrap.json'",
        "EXPECTED_PYTHON_VERSION='3.13.14'",
        "EXPECTED_ARCH='aarch64'",
        "RUNTIME_LOCK_REL='backend/locks/runtime-py313.txt'",
        "502923386",
        "89958991",
        "curl --fail --location",
        "--proto '=https'",
        "--tlsv1.2",
        "--retry 0",
        "safe-extract",
        "python/bin/python3.13",
        "--require-hashes",
        "--only-binary=:all:",
        '"$STAGING_PYTHON" -m pip check',
        "PIP_CONFIG_FILE=/dev/null",
        "RUNTIME_TREE_SHA",
        "candidate-receipt.json",
        "final relocated runtime candidate verification failed",
        "NETWORK_PACKAGE_INSTALL_PERFORMED=true",
        "DIAGNOSTIC_EXECUTED=false",
    ):
        assert marker in source
    assert "/usr/bin/python3 -m venv" not in source
    assert "$STAGING_DIR/venv" not in source
    assert "kaufland_k3c_promo_structure_diagnostic" not in source
    assert "/home/andris/hermes-deals-retained-evidence" not in source
    assert "apt install" not in source
    assert "apt-get install" not in source


def test_active_python_surfaces_are_unified_on_313() -> None:
    ci = _text(CI_WORKFLOW)
    lock_workflow = _text(LOCK_WORKFLOW)
    compiler = _text(LOCK_COMPILER)
    dockerfile = _text(DOCKERFILE)
    manifest = json.loads(_text(LOCK_MANIFEST))
    assert 'python-version: "3.13"' in ci
    assert "backend/locks/ci-py313.txt" in ci
    assert 'python-version: "3.11"' not in ci
    assert "Verify Python 3.13 locks" in lock_workflow
    assert "bash scripts/compile-python-locks.sh 3.13" in lock_workflow
    assert 'echo "usage: $0 3.13"' in compiler
    assert "FROM python:3.13.14-slim-bookworm@sha256:" in dockerfile
    assert set(manifest["locks"]) == {"runtime-py313.txt", "ci-py313.txt"}
    assert {entry["python"] for entry in manifest["locks"].values()} == {"3.13"}
    assert runtime_contract.SUPPORTED_PYTHON_LINES == {"3.13"}


def test_root_registration_preverifies_candidate_and_does_not_install_packages() -> None:
    source = _text(INSTALLER)
    preverify = 'CANDIDATE_REPORT="$(run_contract_as_andris verify'
    mutation = "# Persistent host registration begins here."
    copy_runtime = 'cp -a -- "$RUNTIME_CANDIDATE" "$REGISTERED_RUNTIME_DIR"'
    registered_verify = 'REGISTERED_RUNTIME_REPORT="$(run_contract_as_andris verify'
    assert source.index(preverify) < source.index(mutation) < source.index(copy_runtime)
    assert source.index(copy_runtime) < source.index(registered_verify)
    assert 'chown -hR root:root "$REGISTERED_RUNTIME_DIR"' in source
    assert "RUNTIME_PACKAGE_INSTALL_PERFORMED=false" in source
    assert "NETWORK_PACKAGE_INSTALL_PERFORMED=false" in source
    assert "pip install" not in source
    assert " -m venv" not in source


def test_dispatcher_reverifies_runtime_before_import_and_uses_bootstrapped_python() -> None:
    source = _text(INSTALLER)
    runtime_python = 'RUNTIME_PYTHON="$runtime_registered_dir/python/bin/python3.13"'
    runtime_verify = 'RUNTIME_VERIFY_REPORT="$(runuser -u andris'
    import_function = "probe_python_import() {"
    diagnostic = 'exec "$2" -m app.kaufland_k3c_promo_structure_diagnostic'
    assert runtime_python in source
    assert source.index(runtime_python) < source.index(runtime_verify) < source.index(import_function)
    assert source.index(import_function) < source.index(diagnostic)


def test_workflow_binds_all_runtime_trust_sources_without_installing_runtime() -> None:
    source = _text(WORKFLOW)
    for path in (
        "tools/runner/build-kaufland-k3c-python-runtime.sh",
        "tools/runner/kaufland_k3c_python_runtime_contract.py",
        "tools/runner/kaufland-k3c-python-bootstrap.json",
        "backend/locks/manifest.json",
        "scripts/verify-python-lock-environment.py",
        "backend/locks/runtime-py313.txt",
    ):
        assert path in source
    assert "pip install" not in source
    assert " -m venv" not in source
    assert "apt install" not in source
    assert "apt-get install" not in source


def test_runtime_shell_sources_are_syntax_valid() -> None:
    for path in (BUILDER, INSTALLER):
        completed = subprocess.run(["bash", "-n", str(path)], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        assert completed.returncode == 0, completed.stderr
