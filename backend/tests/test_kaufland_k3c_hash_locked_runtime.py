from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
BUILDER = ROOT / "tools/runner/build-kaufland-k3c-python-runtime.sh"
CONTRACT = ROOT / "tools/runner/kaufland_k3c_python_runtime_contract.py"
INSTALLER = ROOT / "tools/runner/install-kaufland-k3c-promo-structure-rpi5-bridge.sh"
WORKFLOW = ROOT / ".github/workflows/kaufland-k3c-promo-structure-rpi5.yml"

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


def test_builder_uses_only_repo_hash_locks_and_never_executes_diagnostic() -> None:
    source = _text(BUILDER)
    for marker in (
        "3.11) RUNTIME_LOCK_REL=\"$RUNTIME_PY311_REL\"",
        "3.13) RUNTIME_LOCK_REL=\"$RUNTIME_PY313_REL\"",
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

    assert "kaufland_k3c_promo_structure_diagnostic" not in source
    assert "/home/andris/hermes-deals-retained-evidence" not in source
    assert "apt install" not in source
    assert "apt-get install" not in source


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
    assert "/home/andris/.cache/hermes-deals-kaufland-k3c-python-runtime/candidate-" in source
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
