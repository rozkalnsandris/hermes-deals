#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from typing import Any, Mapping

CONFIG = Path("/etc/hermes-deals-audits.d/aldi-gate-d1-overlay-v2.json")
STATE_ROOT = Path("/home/andris/.local/state/hermes-deals/aldi-perfect-shadow")
STAGING_ROOT = Path("/home/andris/hermes-deals-runner-evidence")
EXPORT_ROOT = Path("/home/github-runner/_work/_temp")
EXPORT_PREFIX = "hermes-deals-aldi-gate-d1-overlay-v2-"
V1_COMMIT = "690a0a09364b59e323230d24af006542bbdb1012"
V1_MANIFEST_SHA256 = "481bd9ea014afb928f9f2b4b5d5f84c6f571c72c2524d7b442b16124ca73169f"
CANONICAL_GATE_B_SHA256 = "3188821faa36a6d9fb598fde521a59993e6cb11678a8160e4afead4ba4fcfdd4"


class DispatchError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DispatchError(message)


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def regular_file(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False
    return stat.S_ISREG(mode) and not path.is_symlink()


def regular_dir(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False
    return stat.S_ISDIR(mode) and not path.is_symlink()


def safe_relative(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, str) or not value or value.startswith("/"):
        return False
    return ".." not in Path(value).parts and "." not in Path(value).parts


def load_config() -> dict[str, Any]:
    require(regular_file(CONFIG), "overlay config missing or unsafe")
    info = CONFIG.stat()
    require(info.st_uid == 0 and info.st_gid == 0, "overlay config owner mismatch")
    require(stat.S_IMODE(info.st_mode) == 0o600, "overlay config mode mismatch")
    value = json.loads(CONFIG.read_text(encoding="utf-8"))
    require(isinstance(value, dict), "overlay config invalid")
    return value


def validate_result(result: Mapping[str, Any]) -> None:
    require(result.get("schema_version") == 1, "unexpected result schema")
    require(result.get("mode") == "ALDI_GATE_D_RPI5_EVIDENCE_DISCOVERY_V01", "unexpected result mode")
    require(result.get("review_pack_execution_authorized") is False, "review-pack authority drift")
    require(result.get("production_eligible") is False, "production authority drift")
    transport = result.get("gate_b_transport")
    require(isinstance(transport, Mapping), "transport evidence missing")
    require(transport.get("decoded_sha256") == CANONICAL_GATE_B_SHA256, "decoded Gate B identity drift")
    require(transport.get("fix_version") == 2, "transport fix version drift")
    safety = result.get("safety")
    require(isinstance(safety, Mapping), "safety block missing")
    require(safety.get("discovery_only") is True, "discovery-only flag missing")
    require(safety.get("strict_41_of_41_gate_unchanged") is True, "strict gate drift")
    for key, value in safety.items():
        if key.endswith("_authorized"):
            require(value is False, f"unsafe authority flag: {key}")
    selected = result.get("selected")
    require(isinstance(selected, Mapping), "selected evidence block missing")
    for value in selected.values():
        require(safe_relative(value), "unsafe selected evidence path")


def copy_file(source: Path, destination: Path) -> dict[str, Any]:
    require(regular_file(source), f"missing export source: {source.name}")
    require(not destination.exists(), f"export destination exists: {destination.name}")
    shutil.copyfile(source, destination, follow_symlinks=False)
    os.chmod(destination, 0o600)
    shutil.chown(destination, user="github-runner", group="github-runner")
    return {"path": destination.name, "bytes": destination.stat().st_size, "sha256": sha_file(destination)}


def write_manifest(export_dir: Path, *, commit_sha: str, status: str, rows: list[dict[str, Any]]) -> None:
    value = {
        "schema_version": 1,
        "audit": "aldi-gate-d1-overlay-v2",
        "commit_sha": commit_sha,
        "status": status,
        "v1_commit": V1_COMMIT,
        "v1_bundle_manifest_sha256": V1_MANIFEST_SHA256,
        "files": sorted(rows, key=lambda row: row["path"]),
        "raw_evidence_exported": False,
        "raw_exception_exported": False,
        "production_apply_authorized": False,
        "review_pack_execution_authorized": False,
    }
    path = export_dir / "dispatcher-evidence-manifest.json"
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    shutil.chown(path, user="github-runner", group="github-runner")


def dispatch(commit_sha: str, export_raw: str) -> int:
    require(os.geteuid() == 0, "root required")
    require(len(commit_sha) == 40 and all(ch in "0123456789abcdef" for ch in commit_sha), "invalid commit SHA")
    export_dir = Path(export_raw)
    require(export_dir.is_absolute(), "export path must be absolute")
    require(export_dir.parent.resolve(strict=True) == EXPORT_ROOT, "export parent rejected")
    require(export_dir.name.startswith(EXPORT_PREFIX), "export prefix rejected")
    require(regular_dir(export_dir), "export directory missing or unsafe")

    config = load_config()
    require(config.get("commit_sha") == commit_sha, "overlay commit mismatch")
    overlay = Path(str(config.get("overlay_file") or ""))
    require(regular_file(overlay), "overlay file missing or unsafe")
    require(sha_file(overlay) == config.get("overlay_sha256"), "overlay SHA drift")
    require(sha_file(Path(__file__)) == config.get("dispatcher_sha256"), "dispatcher SHA drift")

    v1_bundle = Path(str(config.get("v1_bundle") or ""))
    require(regular_dir(v1_bundle) and v1_bundle.name == V1_COMMIT, "v1 bundle missing or unsafe")
    v1_manifest = v1_bundle / "bundle-manifest.json"
    require(regular_file(v1_manifest), "v1 bundle manifest missing")
    require(sha_file(v1_manifest) == V1_MANIFEST_SHA256, "v1 bundle manifest drift")
    require(regular_dir(STATE_ROOT), "ALDI state root missing or unsafe")
    require(regular_dir(STAGING_ROOT), "staging root missing or unsafe")

    staging = STAGING_ROOT / export_dir.name
    require(not staging.exists(), "staging path exists")
    staging.mkdir(mode=0o700)
    shutil.chown(staging, user="andris", group="andris")
    result = staging / "discovery-result.json"
    failure = staging / "discovery-failure.json"
    exit_file = staging / "discovery-exit-code.txt"
    gate_b = v1_bundle / "config/aldi-weekly-gate-b-replay-plan-31105044968.json"
    command = [
        "/usr/sbin/runuser", "-u", "andris", "--",
        "/usr/bin/env", "-i", "HOME=/home/andris", "USER=andris", "LOGNAME=andris",
        "PATH=/usr/local/bin:/usr/bin:/bin", "LANG=C.UTF-8",
        "/usr/bin/python3", str(overlay),
        "--bundle", str(v1_bundle),
        "--state-root", str(STATE_ROOT),
        "--gate-b-plan", str(gate_b),
        "--output", str(result),
        "--failure-output", str(failure),
    ]
    try:
        completed = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=300)
        exit_file.write_text(f"{completed.returncode}\n", encoding="ascii")
        os.chmod(exit_file, 0o600)
        rows: list[dict[str, Any]] = []
        if completed.returncode == 0:
            require(regular_file(result), "discovery result missing")
            payload = json.loads(result.read_text(encoding="utf-8"))
            require(isinstance(payload, dict), "discovery result invalid")
            validate_result(payload)
            for name in ("discovery-result.json", "discovery-exit-code.txt"):
                rows.append(copy_file(staging / name, export_dir / name))
            write_manifest(export_dir, commit_sha=commit_sha, status=str(payload.get("decision")), rows=rows)
            return 0

        require(regular_file(failure), "sanitized failure evidence missing")
        payload = json.loads(failure.read_text(encoding="utf-8"))
        require(payload.get("raw_exception_exported") is False, "raw exception export drift")
        require(payload.get("raw_evidence_exported") is False, "raw evidence export drift")
        for name in ("discovery-failure.json", "discovery-exit-code.txt"):
            rows.append(copy_file(staging / name, export_dir / name))
        write_manifest(export_dir, commit_sha=commit_sha, status="DISCOVERY_EXECUTION_BLOCKED", rows=rows)
        return 1
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: overlay-dispatch <commit-sha> <export-dir>", file=sys.stderr)
        return 2
    try:
        return dispatch(sys.argv[1], sys.argv[2])
    except Exception as exc:
        print(f"OVERLAY_DISPATCH_BLOCKED error_type={type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
