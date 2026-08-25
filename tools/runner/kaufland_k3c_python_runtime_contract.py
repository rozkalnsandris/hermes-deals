#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys
from typing import Any

CONTRACT_VERSION = "kaufland-k3c-hash-locked-python-runtime-v1"
SUPPORTED_PYTHON_LINES = {"3.11", "3.13"}
RECEIPT_KEYS = {
    "schema_version",
    "contract_version",
    "registration_sha",
    "runtime_identity_sha256",
    "python_implementation",
    "python_version",
    "python_line",
    "python_binary_sha256",
    "runtime_lock_relative",
    "runtime_lock_sha256",
    "runtime_inventory_sha256",
    "runtime_tree_sha256",
    "lock_manifest_sha256",
    "lock_verifier_sha256",
    "provisioner_sha256",
    "runtime_contract_sha256",
    "diagnostic_executed",
    "retained_evidence_read_performed",
    "retained_evidence_write_performed",
    "production_database_write_performed",
    "production_deploy_performed",
}
HEX40_RE = re.compile(r"[0-9a-f]{40}")
HEX64_RE = re.compile(r"[0-9a-f]{64}")
PYTHON_VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[a-zA-Z0-9.+-]*)?")


class RuntimeContractError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeContractError(message)


def sha256_file(path: Path) -> str:
    _require(path.is_file() and not path.is_symlink(), f"unsafe file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_symlink_target(root: Path, path: Path) -> str:
    target = os.readlink(path)
    target_path = Path(target)
    _require(not target_path.is_absolute(), f"absolute symlink is forbidden: {path}")
    resolved_root = root.resolve()
    resolved_target = (path.parent / target_path).resolve(strict=False)
    try:
        resolved_target.relative_to(resolved_root)
    except ValueError as exc:
        raise RuntimeContractError(f"symlink escapes runtime root: {path}") from exc
    return target


def runtime_tree_sha256(root: Path) -> str:
    _require(root.is_dir() and not root.is_symlink(), "runtime tree root is missing or unsafe")
    resolved_root = root.resolve()
    digest = hashlib.sha256()
    root_mode = stat.S_IMODE(root.lstat().st_mode)
    digest.update(f"ROOT\0{root_mode:o}\n".encode())

    def visit(directory: Path) -> None:
        entries = sorted(os.scandir(directory), key=lambda item: item.name)
        for entry in entries:
            path = Path(entry.path)
            rel = path.relative_to(resolved_root).as_posix()
            info = path.lstat()
            mode = stat.S_IMODE(info.st_mode)
            if stat.S_ISLNK(info.st_mode):
                target = _safe_symlink_target(resolved_root, path)
                digest.update(f"L\0{rel}\0{mode:o}\0{target}\n".encode())
            elif stat.S_ISDIR(info.st_mode):
                digest.update(f"D\0{rel}\0{mode:o}\n".encode())
                visit(path)
            elif stat.S_ISREG(info.st_mode):
                file_sha = sha256_file(path)
                digest.update(
                    f"F\0{rel}\0{mode:o}\0{info.st_size}\0{file_sha}\n".encode()
                )
            else:
                raise RuntimeContractError(f"unsupported runtime filesystem entry: {rel}")

    visit(resolved_root)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    _require(path.is_file() and not path.is_symlink(), f"unsafe JSON file: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(payload, dict), f"JSON object required: {path}")
    return payload


def _clean_env() -> dict[str, str]:
    return {
        "HOME": "/home/andris",
        "USER": "andris",
        "LOGNAME": "andris",
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONHASHSEED": "0",
        "PIP_CONFIG_FILE": "/dev/null",
        "PIP_NO_INPUT": "1",
    }


def _run_checked(argv: list[str], *, cwd: Path) -> str:
    completed = subprocess.run(
        argv,
        cwd=cwd,
        env=_clean_env(),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise RuntimeContractError("runtime verification subprocess failed")
    return completed.stdout


def _runtime_identity(
    *,
    registration_sha: str,
    python_implementation: str,
    python_version: str,
    python_line: str,
    runtime_lock_relative: str,
    runtime_lock_sha256: str,
    lock_manifest_sha256: str,
    lock_verifier_sha256: str,
    provisioner_sha256: str,
    runtime_contract_sha256: str,
) -> str:
    fields = (
        CONTRACT_VERSION,
        registration_sha,
        python_implementation,
        python_version,
        python_line,
        runtime_lock_relative,
        runtime_lock_sha256,
        lock_manifest_sha256,
        lock_verifier_sha256,
        provisioner_sha256,
        runtime_contract_sha256,
    )
    return hashlib.sha256(("\n".join(fields) + "\n").encode()).hexdigest()


def verify_runtime(
    *,
    runtime_root: Path,
    repo: Path,
    registration_sha: str,
    expected_provisioner_sha: str,
    expected_runtime_contract_sha: str,
    expected_lock_manifest_sha: str,
    expected_lock_verifier_sha: str,
) -> dict[str, str]:
    _require(HEX40_RE.fullmatch(registration_sha) is not None, "registration SHA is invalid")
    for value, label in (
        (expected_provisioner_sha, "provisioner"),
        (expected_runtime_contract_sha, "runtime contract"),
        (expected_lock_manifest_sha, "lock manifest"),
        (expected_lock_verifier_sha, "lock verifier"),
    ):
        _require(HEX64_RE.fullmatch(value) is not None, f"expected {label} SHA-256 is invalid")

    repo = repo.resolve()
    runtime_root = runtime_root.resolve()
    _require(repo.is_dir() and not repo.is_symlink(), "repository root is missing or unsafe")
    _require(runtime_root.is_dir() and not runtime_root.is_symlink(), "runtime root is missing or unsafe")

    receipt = _load_json(runtime_root / "candidate-receipt.json")
    _require(set(receipt) == RECEIPT_KEYS, "runtime receipt schema keys mismatch")
    _require(receipt["schema_version"] == 1, "runtime receipt schema version mismatch")
    _require(receipt["contract_version"] == CONTRACT_VERSION, "runtime contract version mismatch")
    _require(receipt["registration_sha"] == registration_sha, "runtime registration SHA mismatch")
    for key in (
        "diagnostic_executed",
        "retained_evidence_read_performed",
        "retained_evidence_write_performed",
        "production_database_write_performed",
        "production_deploy_performed",
    ):
        _require(receipt[key] is False, f"runtime receipt mutation flag is not false: {key}")

    python_implementation = receipt["python_implementation"]
    python_version = receipt["python_version"]
    python_line = receipt["python_line"]
    _require(python_implementation == "CPython", "runtime is not CPython")
    _require(isinstance(python_version, str) and PYTHON_VERSION_RE.fullmatch(python_version) is not None, "runtime Python version is invalid")
    _require(python_line in SUPPORTED_PYTHON_LINES, "runtime Python line is unsupported")
    _require(python_version.startswith(python_line + "."), "runtime Python version/line mismatch")

    runtime_lock_relative = receipt["runtime_lock_relative"]
    expected_lock_relative = {
        "3.11": "backend/locks/runtime-py311.txt",
        "3.13": "backend/locks/runtime-py313.txt",
    }[python_line]
    _require(runtime_lock_relative == expected_lock_relative, "runtime lock path mismatch")

    manifest_path = repo / "backend/locks/manifest.json"
    verifier_path = repo / "scripts/verify-python-lock-environment.py"
    provisioner_path = repo / "tools/runner/build-kaufland-k3c-python-runtime.sh"
    contract_path = repo / "tools/runner/kaufland_k3c_python_runtime_contract.py"
    lock_path = repo / runtime_lock_relative
    _require(sha256_file(manifest_path) == expected_lock_manifest_sha, "lock manifest source drift")
    _require(sha256_file(verifier_path) == expected_lock_verifier_sha, "lock verifier source drift")
    _require(sha256_file(provisioner_path) == expected_provisioner_sha, "runtime provisioner source drift")
    _require(sha256_file(contract_path) == expected_runtime_contract_sha, "runtime contract source drift")
    _require(receipt["lock_manifest_sha256"] == expected_lock_manifest_sha, "runtime receipt lock manifest SHA mismatch")
    _require(receipt["lock_verifier_sha256"] == expected_lock_verifier_sha, "runtime receipt lock verifier SHA mismatch")
    _require(receipt["provisioner_sha256"] == expected_provisioner_sha, "runtime receipt provisioner SHA mismatch")
    _require(receipt["runtime_contract_sha256"] == expected_runtime_contract_sha, "runtime receipt contract SHA mismatch")

    manifest = _load_json(manifest_path)
    manifest_entry = (manifest.get("locks") or {}).get(Path(runtime_lock_relative).name)
    _require(isinstance(manifest_entry, dict), "runtime lock is absent from manifest")
    manifest_python_line = manifest_entry.get("python")
    manifest_lock_sha = manifest_entry.get("sha256")
    _require(manifest_python_line == python_line, "runtime lock manifest Python line mismatch")
    _require(isinstance(manifest_lock_sha, str) and HEX64_RE.fullmatch(manifest_lock_sha) is not None, "runtime lock manifest SHA is invalid")
    _require(sha256_file(lock_path) == manifest_lock_sha, "runtime lock source drift")
    _require(receipt["runtime_lock_sha256"] == manifest_lock_sha, "runtime receipt lock SHA mismatch")

    venv_root = runtime_root / "venv"
    python_path = venv_root / "bin/python"
    _require(venv_root.is_dir() and not venv_root.is_symlink(), "runtime venv is missing or unsafe")
    _require(python_path.is_file() and not python_path.is_symlink() and os.access(python_path, os.X_OK), "runtime Python is missing or unsafe")
    binary_sha = sha256_file(python_path)
    _require(receipt["python_binary_sha256"] == binary_sha, "runtime Python binary SHA mismatch")

    tree_sha = runtime_tree_sha256(venv_root)
    _require(receipt["runtime_tree_sha256"] == tree_sha, "runtime tree SHA mismatch")

    identity_sha = _runtime_identity(
        registration_sha=registration_sha,
        python_implementation=python_implementation,
        python_version=python_version,
        python_line=python_line,
        runtime_lock_relative=runtime_lock_relative,
        runtime_lock_sha256=manifest_lock_sha,
        lock_manifest_sha256=expected_lock_manifest_sha,
        lock_verifier_sha256=expected_lock_verifier_sha,
        provisioner_sha256=expected_provisioner_sha,
        runtime_contract_sha256=expected_runtime_contract_sha,
    )
    _require(receipt["runtime_identity_sha256"] == identity_sha, "runtime identity SHA mismatch")

    identity_raw = _run_checked(
        [
            str(python_path),
            "-c",
            "import json,platform,sys; print(json.dumps({'implementation':platform.python_implementation(),'version':platform.python_version(),'line':f'{sys.version_info.major}.{sys.version_info.minor}'},sort_keys=True))",
        ],
        cwd=repo / "backend",
    ).strip()
    identity_payload = json.loads(identity_raw)
    _require(identity_payload == {
        "implementation": python_implementation,
        "line": python_line,
        "version": python_version,
    }, "runtime interpreter identity mismatch")

    _run_checked([str(python_path), "-m", "pip", "check"], cwd=repo / "backend")
    verifier_output = _run_checked(
        [str(python_path), str(verifier_path), str(lock_path)],
        cwd=repo / "backend",
    )
    lines = [line.strip() for line in verifier_output.splitlines() if line.strip()]
    _require("PYTHON_LOCK_ENVIRONMENT=PASS" in lines, "runtime lock verifier did not report PASS")
    inventory_values = [
        line.split("=", 1)[1]
        for line in lines
        if line.startswith("LOCKED_INVENTORY_SHA256=")
    ]
    _require(len(inventory_values) == 1 and HEX64_RE.fullmatch(inventory_values[0]) is not None, "runtime inventory SHA is invalid")
    inventory_sha = inventory_values[0]
    _require(receipt["runtime_inventory_sha256"] == inventory_sha, "runtime inventory SHA mismatch")

    for key in (
        "runtime_identity_sha256",
        "runtime_lock_sha256",
        "runtime_inventory_sha256",
        "runtime_tree_sha256",
        "python_binary_sha256",
    ):
        _require(isinstance(receipt[key], str) and HEX64_RE.fullmatch(receipt[key]) is not None, f"invalid receipt digest: {key}")

    return {
        "runtime_identity_sha256": identity_sha,
        "runtime_tree_sha256": tree_sha,
        "runtime_inventory_sha256": inventory_sha,
        "runtime_python_line": python_line,
        "runtime_lock_relative": runtime_lock_relative,
        "runtime_lock_sha256": manifest_lock_sha,
        "runtime_python_binary_sha256": binary_sha,
    }


def _cmd_tree_sha(args: argparse.Namespace) -> int:
    print(runtime_tree_sha256(Path(args.root)))
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    result = verify_runtime(
        runtime_root=Path(args.runtime_root),
        repo=Path(args.repo),
        registration_sha=args.registration_sha,
        expected_provisioner_sha=args.expected_provisioner_sha,
        expected_runtime_contract_sha=args.expected_runtime_contract_sha,
        expected_lock_manifest_sha=args.expected_lock_manifest_sha,
        expected_lock_verifier_sha=args.expected_lock_verifier_sha,
    )
    print("RUNTIME_CONTRACT=PASS")
    for key in (
        "runtime_identity_sha256",
        "runtime_tree_sha256",
        "runtime_inventory_sha256",
        "runtime_python_line",
        "runtime_lock_relative",
        "runtime_lock_sha256",
        "runtime_python_binary_sha256",
    ):
        print(f"{key.upper()}={result[key]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    tree_parser = subparsers.add_parser("tree-sha")
    tree_parser.add_argument("--root", required=True)
    tree_parser.set_defaults(func=_cmd_tree_sha)

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--runtime-root", required=True)
    verify_parser.add_argument("--repo", required=True)
    verify_parser.add_argument("--registration-sha", required=True)
    verify_parser.add_argument("--expected-provisioner-sha", required=True)
    verify_parser.add_argument("--expected-runtime-contract-sha", required=True)
    verify_parser.add_argument("--expected-lock-manifest-sha", required=True)
    verify_parser.add_argument("--expected-lock-verifier-sha", required=True)
    verify_parser.set_defaults(func=_cmd_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (RuntimeContractError, json.JSONDecodeError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 20


if __name__ == "__main__":
    raise SystemExit(main())
