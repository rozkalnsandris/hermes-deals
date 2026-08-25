from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
BUILDER = ROOT / "tools/runner/build-kaufland-k3c-python-runtime.sh"
CONTRACT = ROOT / "tools/runner/kaufland_k3c_python_runtime_contract.py"
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


def test_runtime_tree_fingerprint_is_deterministic_and_byte_sensitive(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    (root / "lib").mkdir(parents=True)
    artifact = root / "lib" / "module.py"
    artifact.write_text("value = 1\n", encoding="utf-8")

    first = runtime_contract.runtime_tree_sha256(root)
    second = runtime_contract.runtime_tree_sha256(root)
    assert first == second
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


def test_builder_uses_canonical_py313_hash_lock_and_never_executes_diagnostic() -> None:
    source = _text(BUILDER)
    for marker in (
        "EXPECTED_PYTHON_LINE='3.13'",
        "RUNTIME_LOCK_REL='backend/locks/runtime-py313.txt'",
        '[[ "$PYTHON_LINE" == "$EXPECTED_PYTHON_LINE" ]]',
        "backend/locks/manifest.json",
        "scripts/verify-python-lock-environment.py",
        "--require-hashes",
        "--only-binary=:all:",
        '"$STAGING_PYTHON" -m pip check',
        "PIP_CONFIG_FILE=/dev/null",
        "PIP_NO_INPUT=1",
        "RUNTIME_TREE_SHA",
        "candidate-receipt.json",
        "RUNTIME_CONTRACT=PASS",
        "NETWORK_PACKAGE_INSTALL_PERFORMED=true",
        "DIAGNOSTIC_EXECUTED=false",
    ):
        assert marker in source

    assert "RUNTIME_PY311_REL" not in source
    assert "MANIFEST_RECORD" not in source
    assert "read -r MANIFEST_PYTHON_LINE RUNTIME_LOCK_SHA" not in source
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
    assert "locks/ci-py313.txt" in ci
    assert 'python-version: "3.11"' not in ci
    assert "ci-py311.txt" not in ci

    assert "Verify Python 3.13 locks" in lock_workflow
    assert "bash scripts/compile-python-locks.sh 3.13" in lock_workflow
    assert "backend/locks/runtime-py313.txt" in lock_workflow
    assert "backend/locks/ci-py313.txt" in lock_workflow
    assert '"3.11"' not in lock_workflow
    assert "py311" not in lock_workflow

    assert 'echo "usage: $0 3.13"' in compiler
    assert 'compile_lock "$EXPECTED_INPUT" "backend/locks/runtime-py313.txt"' in compiler
    assert 'compile_lock "$CI_INPUT" "backend/locks/ci-py313.txt"' in compiler
    assert "3.11" not in compiler

    assert "FROM python:3.13.14-slim-bookworm@sha256:" in dockerfile
    assert "locks/runtime-py313.txt" in dockerfile

    locks = manifest["locks"]
    assert set(locks) == {"runtime-py313.txt", "ci-py313.txt"}
    assert {entry["python"] for entry in locks.values()} == {"3.13"}
    assert runtime_contract.SUPPORTED_PYTHON_LINES == {"3.13"}


def test_root_registration_preverifies_candidate_and_does_not_install_packages() -> None:
    source = _text(INSTALLER)
    usage = (
        "install-kaufland-k3c-promo-structure-rpi5-bridge.sh "
        "<registration-merge-sha> <runtime-candidate-dir>"
    )
    preverify = 'CANDIDATE_REPORT="$(run_contract_as_andris verify'
    mutation = "# Persistent host registration begins here."
    copy_runtime = 'cp -a -- "$RUNTIME_CANDIDATE" "$REGISTERED_RUNTIME_DIR"'
    registered_verify = 'REGISTERED_RUNTIME_REPORT="$(run_contract_as_andris verify'

    assert usage in source
    assert "hermes-deals-kaufland-k3c-python-runtime/candidate-" in source
    assert "candidate-[0-9a-f]{64}" in source
    assert source.index(preverify) < source.index(mutation) < source.index(copy_runtime)
    assert source.index(copy_runtime) < source.index(registered_verify)
    assert 'chown -hR root:root "$REGISTERED_RUNTIME_DIR"' in source
    assert "RUNTIME_PACKAGE_INSTALL_PERFORMED=false" in source
    assert "NETWORK_PACKAGE_INSTALL_PERFORMED=false" in source
    assert "pip install" not in source
    assert " -m venv" not in source
    assert "apt install" not in source
    assert "apt-get install" not in source


def test_dispatcher_reverifies_runtime_before_import_and_uses_venv_python() -> None:
    source = _text(INSTALLER)
    runtime_python = 'RUNTIME_PYTHON="$runtime_registered_dir/venv/bin/python"'
    runtime_verify = 'RUNTIME_VERIFY_REPORT="$(runuser -u andris'
    import_function = "probe_python_import() {"
    diagnostic = 'exec "$2" -m app.kaufland_k3c_promo_structure_diagnostic'

    assert runtime_python in source
    assert source.index(runtime_python) < source.index(runtime_verify) < source.index(import_function)
    assert source.index(import_function) < source.index(diagnostic)
    assert '"$repo/backend" "$RUNTIME_PYTHON" "$module"' in source
    assert '_ "$repo/backend" "$RUNTIME_PYTHON" "$retained_root"' in source
    assert 'bridge_block "DIAGNOSTIC_RUNTIME_UNAVAILABLE"' in source
    assert 'bridge_block "DIAGNOSTIC_RUNTIME_IDENTITY_FAILED"' in source
    assert 'RUNTIME_VERIFY_STDERR_PRIVATE="$STAGING_DIR/runtime-contract-stderr.private"' in source
    assert 'rm -f -- "$RUNTIME_VERIFY_STDERR_PRIVATE"' in source


def test_workflow_binds_all_runtime_trust_sources_without_installing_runtime() -> None:
    source = _text(WORKFLOW)
    for path in (
        "tools/runner/build-kaufland-k3c-python-runtime.sh",
        "tools/runner/kaufland_k3c_python_runtime_contract.py",
        "backend/locks/manifest.json",
        "scripts/verify-python-lock-environment.py",
        "backend/locks/runtime-py311.txt",
        "backend/locks/runtime-py313.txt",
    ):
        assert path in source

    assert "pip install" not in source
    assert " -m venv" not in source
    assert "apt install" not in source
    assert "apt-get install" not in source


def test_runtime_shell_sources_are_syntax_valid() -> None:
    for path in (BUILDER, INSTALLER):
        completed = subprocess.run(
            ["bash", "-n", str(path)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
