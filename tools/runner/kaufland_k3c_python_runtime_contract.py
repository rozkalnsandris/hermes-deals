#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import stat
import subprocess
import sys
import tarfile
from typing import Any

CONTRACT_VERSION = "kaufland-k3c-hash-locked-python-runtime-v2"
BOOTSTRAP_CONTRACT_VERSION = "kaufland-k3c-python-bootstrap-v1"
BOOTSTRAP_RELATIVE = "tools/runner/kaufland-k3c-python-bootstrap.json"
RUNTIME_RELATIVE = "python"
PYTHON_RELATIVE = "python/bin/python3.13"
SUPPORTED_PYTHON_LINES = {"3.13"}
RECEIPT_KEYS = {
    "schema_version",
    "contract_version",
    "registration_sha",
    "runtime_identity_sha256",
    "python_implementation",
    "python_version",
    "python_line",
    "python_relative",
    "python_binary_sha256",
    "bootstrap_manifest_relative",
    "bootstrap_manifest_sha256",
    "bootstrap_asset_id",
    "bootstrap_asset_name",
    "bootstrap_asset_sha256",
    "bootstrap_asset_size",
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
                digest.update(
                    f"F\0{rel}\0{mode:o}\0{info.st_size}\0{sha256_file(path)}\n".encode()
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


def load_bootstrap_manifest(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    _require(payload.get("schema_version") == 1, "bootstrap manifest schema version mismatch")
    _require(payload.get("contract_version") == BOOTSTRAP_CONTRACT_VERSION, "bootstrap contract version mismatch")
    release = payload.get("release")
    asset = payload.get("asset")
    python = payload.get("python")
    target = payload.get("platform")
    _require(isinstance(release, dict) and release.get("immutable") is True, "bootstrap release is not immutable")
    _require(isinstance(asset, dict), "bootstrap asset object is invalid")
    _require(isinstance(python, dict), "bootstrap Python object is invalid")
    _require(isinstance(target, dict), "bootstrap platform object is invalid")
    _require(isinstance(asset.get("asset_id"), int) and asset["asset_id"] > 0, "bootstrap asset ID is invalid")
    _require(isinstance(asset.get("size"), int) and asset["size"] > 0, "bootstrap asset size is invalid")
    _require(isinstance(asset.get("sha256"), str) and HEX64_RE.fullmatch(asset["sha256"]) is not None, "bootstrap asset SHA-256 is invalid")
    _require(python.get("implementation") == "CPython", "bootstrap implementation mismatch")
    _require(python.get("version") == "3.13.14", "bootstrap Python version mismatch")
    _require(python.get("line") == "3.13", "bootstrap Python line mismatch")
    _require(python.get("executable") == PYTHON_RELATIVE, "bootstrap Python executable mismatch")
    _require(target.get("os") == "linux" and target.get("architecture") == "aarch64", "bootstrap platform mismatch")
    return payload


def _clean_tar_name(name: str) -> str:
    _require(isinstance(name, str) and name not in {"", "."}, "empty tar member name")
    pure = PurePosixPath(name)
    _require(not pure.is_absolute(), f"absolute tar member is forbidden: {name}")
    _require(".." not in pure.parts, f"tar path traversal is forbidden: {name}")
    normalized = posixpath.normpath(name)
    _require(normalized == name.rstrip("/"), f"non-canonical tar member path: {name}")
    _require(normalized == "python" or normalized.startswith("python/"), f"unexpected tar top-level path: {name}")
    return normalized


def _validate_link(member_name: str, target: str) -> None:
    _require(target != "", f"empty tar link target: {member_name}")
    target_path = PurePosixPath(target)
    _require(not target_path.is_absolute(), f"absolute tar link is forbidden: {member_name}")
    combined = posixpath.normpath(posixpath.join(posixpath.dirname(member_name), target))
    _require(combined == "python" or combined.startswith("python/"), f"tar link escapes python root: {member_name}")


def _tar_parent_names(name: str) -> tuple[str, ...]:
    parts = PurePosixPath(name).parts
    return tuple(PurePosixPath(*parts[:index]).as_posix() for index in range(1, len(parts)))


def safe_extract_bootstrap(archive: Path, destination: Path) -> None:
    _require(archive.is_file() and not archive.is_symlink(), "bootstrap archive is missing or unsafe")
    _require(destination.is_dir() and not destination.is_symlink(), "bootstrap destination is missing or unsafe")
    python_root = destination / RUNTIME_RELATIVE
    _require(not python_root.exists() and not python_root.is_symlink(), "bootstrap runtime root already exists")
    with tarfile.open(archive, mode="r:gz") as bundle:
        members = bundle.getmembers()
        _require(bool(members), "bootstrap archive is empty")
        canonical_names: set[str] = set()
        symlink_names: set[str] = set()
        for member in members:
            name = _clean_tar_name(member.name)
            _require(name not in canonical_names, f"duplicate tar member is forbidden: {name}")
            canonical_names.add(name)
            if member.isdev() or member.isfifo():
                raise RuntimeContractError(f"special tar member is forbidden: {name}")
            if member.islnk():
                raise RuntimeContractError(f"hardlink tar member is forbidden: {name}")
            if member.issym():
                _validate_link(name, member.linkname)
                symlink_names.add(name)
            elif not (member.isdir() or member.isfile()):
                raise RuntimeContractError(f"unsupported tar member type: {name}")
        for name in canonical_names:
            symlink_parent = next((parent for parent in _tar_parent_names(name) if parent in symlink_names), None)
            _require(symlink_parent is None, f"tar member is nested below symlink parent: {name}")
        bundle.extractall(destination, members=members, numeric_owner=False)
    _require(python_root.is_dir() and not python_root.is_symlink(), "bootstrap archive did not create python runtime root")


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


def _runtime_identity(*, registration_sha: str, python_implementation: str, python_version: str, python_line: str, bootstrap_manifest_sha256: str, bootstrap_asset_id: int, bootstrap_asset_sha256: str, runtime_lock_relative: str, runtime_lock_sha256: str, lock_manifest_sha256: str, lock_verifier_sha256: str, provisioner_sha256: str, runtime_contract_sha256: str) -> str:
    fields = (
        CONTRACT_VERSION,
        registration_sha,
        python_implementation,
        python_version,
        python_line,
        bootstrap_manifest_sha256,
        str(bootstrap_asset_id),
        bootstrap_asset_sha256,
        runtime_lock_relative,
        runtime_lock_sha256,
        lock_manifest_sha256,
        lock_verifier_sha256,
        provisioner_sha256,
        runtime_contract_sha256,
    )
    return hashlib.sha256(("\n".join(fields) + "\n").encode()).hexdigest()


def verify_runtime(*, runtime_root: Path, repo: Path, registration_sha: str, expected_provisioner_sha: str, expected_runtime_contract_sha: str, expected_lock_manifest_sha: str, expected_lock_verifier_sha: str) -> dict[str, str]:
    _require(HEX40_RE.fullmatch(registration_sha) is not None, "registration SHA is invalid")
    for value, label in ((expected_provisioner_sha, "provisioner"), (expected_runtime_contract_sha, "runtime contract"), (expected_lock_manifest_sha, "lock manifest"), (expected_lock_verifier_sha, "lock verifier")):
        _require(HEX64_RE.fullmatch(value) is not None, f"expected {label} SHA-256 is invalid")
    _require(repo.is_dir() and not repo.is_symlink(), "repository root is missing or unsafe")
    _require(runtime_root.is_dir() and not runtime_root.is_symlink(), "runtime root is missing or unsafe")
    repo = repo.resolve()
    runtime_root = runtime_root.resolve()

    receipt = _load_json(runtime_root / "candidate-receipt.json")
    _require(set(receipt) == RECEIPT_KEYS, "runtime receipt schema keys mismatch")
    _require(receipt["schema_version"] == 2, "runtime receipt schema version mismatch")
    _require(receipt["contract_version"] == CONTRACT_VERSION, "runtime contract version mismatch")
    _require(receipt["registration_sha"] == registration_sha, "runtime registration SHA mismatch")
    for key in ("diagnostic_executed", "retained_evidence_read_performed", "retained_evidence_write_performed", "production_database_write_performed", "production_deploy_performed"):
        _require(receipt[key] is False, f"runtime receipt mutation flag is not false: {key}")

    bootstrap_path = repo / BOOTSTRAP_RELATIVE
    bootstrap = load_bootstrap_manifest(bootstrap_path)
    bootstrap_sha = sha256_file(bootstrap_path)
    asset = bootstrap["asset"]
    _require(receipt["bootstrap_manifest_relative"] == BOOTSTRAP_RELATIVE, "bootstrap manifest path mismatch")
    _require(receipt["bootstrap_manifest_sha256"] == bootstrap_sha, "bootstrap manifest SHA mismatch")
    _require(receipt["bootstrap_asset_id"] == asset["asset_id"], "bootstrap asset ID mismatch")
    _require(receipt["bootstrap_asset_name"] == asset["name"], "bootstrap asset name mismatch")
    _require(receipt["bootstrap_asset_sha256"] == asset["sha256"], "bootstrap asset SHA mismatch")
    _require(receipt["bootstrap_asset_size"] == asset["size"], "bootstrap asset size mismatch")

    python_implementation = receipt["python_implementation"]
    python_version = receipt["python_version"]
    python_line = receipt["python_line"]
    _require(python_implementation == "CPython", "runtime is not CPython")
    _require(isinstance(python_version, str) and PYTHON_VERSION_RE.fullmatch(python_version) is not None, "runtime Python version is invalid")
    _require(python_version == bootstrap["python"]["version"], "runtime Python version/bootstrap mismatch")
    _require(python_line in SUPPORTED_PYTHON_LINES and python_line == bootstrap["python"]["line"], "runtime Python line mismatch")
    _require(receipt["python_relative"] == PYTHON_RELATIVE, "runtime Python relative path mismatch")

    manifest_path = repo / "backend/locks/manifest.json"
    verifier_path = repo / "scripts/verify-python-lock-environment.py"
    provisioner_path = repo / "tools/runner/build-kaufland-k3c-python-runtime.sh"
    contract_path = repo / "tools/runner/kaufland_k3c_python_runtime_contract.py"
    runtime_lock_relative = receipt["runtime_lock_relative"]
    _require(runtime_lock_relative == "backend/locks/runtime-py313.txt", "runtime lock path mismatch")
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
    entry = (manifest.get("locks") or {}).get(Path(runtime_lock_relative).name)
    _require(isinstance(entry, dict) and entry.get("python") == python_line, "runtime lock manifest Python line mismatch")
    manifest_lock_sha = entry.get("sha256")
    _require(isinstance(manifest_lock_sha, str) and HEX64_RE.fullmatch(manifest_lock_sha) is not None, "runtime lock manifest SHA is invalid")
    _require(sha256_file(lock_path) == manifest_lock_sha, "runtime lock source drift")
    _require(receipt["runtime_lock_sha256"] == manifest_lock_sha, "runtime receipt lock SHA mismatch")

    python_root = runtime_root / RUNTIME_RELATIVE
    python_path = runtime_root / PYTHON_RELATIVE
    _require(python_root.is_dir() and not python_root.is_symlink(), "runtime Python root is missing or unsafe")
    _require(python_path.is_file() and not python_path.is_symlink() and os.access(python_path, os.X_OK), "runtime Python is missing or unsafe")
    binary_sha = sha256_file(python_path)
    _require(receipt["python_binary_sha256"] == binary_sha, "runtime Python binary SHA mismatch")
    tree_sha = runtime_tree_sha256(python_root)
    _require(receipt["runtime_tree_sha256"] == tree_sha, "runtime tree SHA mismatch")

    identity_sha = _runtime_identity(registration_sha=registration_sha, python_implementation=python_implementation, python_version=python_version, python_line=python_line, bootstrap_manifest_sha256=bootstrap_sha, bootstrap_asset_id=asset["asset_id"], bootstrap_asset_sha256=asset["sha256"], runtime_lock_relative=runtime_lock_relative, runtime_lock_sha256=manifest_lock_sha, lock_manifest_sha256=expected_lock_manifest_sha, lock_verifier_sha256=expected_lock_verifier_sha, provisioner_sha256=expected_provisioner_sha, runtime_contract_sha256=expected_runtime_contract_sha)
    _require(receipt["runtime_identity_sha256"] == identity_sha, "runtime identity SHA mismatch")

    identity_raw = _run_checked([str(python_path), "-c", "import json,platform,sys; print(json.dumps({'implementation':platform.python_implementation(),'version':platform.python_version(),'line':f'{sys.version_info.major}.{sys.version_info.minor}','executable':sys.executable,'prefix':sys.prefix},sort_keys=True))"], cwd=repo / "backend").strip()
    identity_payload = json.loads(identity_raw)
    _require(identity_payload["implementation"] == python_implementation, "runtime interpreter implementation mismatch")
    _require(identity_payload["version"] == python_version and identity_payload["line"] == python_line, "runtime interpreter version mismatch")
    _require(Path(identity_payload["executable"]).resolve() == python_path.resolve(), "runtime interpreter executable relocation mismatch")
    _require(Path(identity_payload["prefix"]).resolve() == python_root.resolve(), "runtime interpreter prefix relocation mismatch")

    _run_checked([str(python_path), "-m", "pip", "check"], cwd=repo / "backend")
    verifier_output = _run_checked([str(python_path), str(verifier_path), str(lock_path)], cwd=repo / "backend")
    lines = [line.strip() for line in verifier_output.splitlines() if line.strip()]
    _require("PYTHON_LOCK_ENVIRONMENT=PASS" in lines, "runtime lock verifier did not report PASS")
    inventory_values = [line.split("=", 1)[1] for line in lines if line.startswith("LOCKED_INVENTORY_SHA256=")]
    _require(len(inventory_values) == 1 and HEX64_RE.fullmatch(inventory_values[0]) is not None, "runtime inventory SHA is invalid")
    inventory_sha = inventory_values[0]
    _require(receipt["runtime_inventory_sha256"] == inventory_sha, "runtime inventory SHA mismatch")

    for key in ("runtime_identity_sha256", "bootstrap_manifest_sha256", "bootstrap_asset_sha256", "runtime_lock_sha256", "runtime_inventory_sha256", "runtime_tree_sha256", "python_binary_sha256"):
        _require(isinstance(receipt[key], str) and HEX64_RE.fullmatch(receipt[key]) is not None, f"invalid receipt digest: {key}")
    return {
        "runtime_identity_sha256": identity_sha,
        "runtime_tree_sha256": tree_sha,
        "runtime_inventory_sha256": inventory_sha,
        "runtime_python_line": python_line,
        "runtime_lock_relative": runtime_lock_relative,
        "runtime_lock_sha256": manifest_lock_sha,
        "runtime_python_binary_sha256": binary_sha,
        "bootstrap_manifest_sha256": bootstrap_sha,
        "bootstrap_asset_sha256": asset["sha256"],
    }


def _cmd_tree_sha(args: argparse.Namespace) -> int:
    print(runtime_tree_sha256(Path(args.root)))
    return 0


def _cmd_extract(args: argparse.Namespace) -> int:
    safe_extract_bootstrap(Path(args.archive), Path(args.destination))
    print("BOOTSTRAP_EXTRACTION=PASS")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    result = verify_runtime(runtime_root=Path(args.runtime_root), repo=Path(args.repo), registration_sha=args.registration_sha, expected_provisioner_sha=args.expected_provisioner_sha, expected_runtime_contract_sha=args.expected_runtime_contract_sha, expected_lock_manifest_sha=args.expected_lock_manifest_sha, expected_lock_verifier_sha=args.expected_lock_verifier_sha)
    print("RUNTIME_CONTRACT=PASS")
    for key in ("runtime_identity_sha256", "runtime_tree_sha256", "runtime_inventory_sha256", "runtime_python_line", "runtime_lock_relative", "runtime_lock_sha256", "runtime_python_binary_sha256", "bootstrap_manifest_sha256", "bootstrap_asset_sha256"):
        print(f"{key.upper()}={result[key]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    tree_parser = subparsers.add_parser("tree-sha")
    tree_parser.add_argument("--root", required=True)
    tree_parser.set_defaults(func=_cmd_tree_sha)
    extract_parser = subparsers.add_parser("safe-extract")
    extract_parser.add_argument("--archive", required=True)
    extract_parser.add_argument("--destination", required=True)
    extract_parser.set_defaults(func=_cmd_extract)
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
    except (RuntimeContractError, json.JSONDecodeError, OSError, TypeError, ValueError, subprocess.SubprocessError, tarfile.TarError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 20


if __name__ == "__main__":
    raise SystemExit(main())
