#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import stat
import subprocess
import sys
import tempfile

AUDIT = "aldi-gate-d3-recovery-inventory"
CONFIG = Path("/etc/hermes-deals-audits.d/aldi-gate-d3-recovery-inventory.json")
STATE_ROOT = Path("/home/andris/.local/state/hermes-deals/aldi-perfect-shadow")
STAGING_ROOT = Path("/home/andris/hermes-deals-runner-evidence")
EXPORT_ROOT = Path("/home/github-runner/_work/_temp")
EXPORT_PREFIX = "hermes-deals-aldi-gate-d3-recovery-inventory-"
ALLOWED_DECISIONS = {
    "RECOVERY_CANDIDATE_FOUND",
    "NO_RECOVERY_CANDIDATE",
    "AMBIGUOUS_RECOVERY_CANDIDATES",
}


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


def regular_root_file(path: Path, mode: int) -> bool:
    if not path.is_file() or path.is_symlink():
        return False
    info = path.stat()
    return info.st_uid == 0 and info.st_gid == 0 and stat.S_IMODE(info.st_mode) == mode


def load_config(commit_sha: str) -> dict:
    require(regular_root_file(CONFIG, 0o600), "config missing or unsafe")
    payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    require(payload.get("audit") == AUDIT, "config audit mismatch")
    require(payload.get("commit_sha") == commit_sha, "config commit mismatch")
    for flag in (
        "raw_evidence_export_authorized",
        "raw_exception_export_authorized",
        "archive_extraction_authorized",
        "production_apply_authorized",
        "review_pack_execution_authorized",
    ):
        require(payload.get(flag) is False, f"unsafe config flag: {flag}")
    tool = Path(payload["inventory_file"])
    require(tool.is_file() and not tool.is_symlink(), "inventory tool missing")
    require(sha_file(tool) == payload.get("inventory_sha256"), "inventory tool SHA drift")
    require(sha_file(Path(__file__)) == payload.get("dispatcher_sha256"), "dispatcher SHA drift")
    return payload


def validate_export_dir(path: Path) -> None:
    require(path.parent.resolve() == EXPORT_ROOT.resolve(), "export parent mismatch")
    require(path.name.startswith(EXPORT_PREFIX), "export prefix mismatch")
    require(path.is_dir() and not path.is_symlink(), "export directory missing or unsafe")


def validate_relative_values(value) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in {"path", "root", "page_images_root", "source", "state_root"} and isinstance(nested, str):
                require(not nested.startswith("/"), "absolute evidence path in result")
                require(".." not in Path(nested).parts, "traversing evidence path in result")
            validate_relative_values(nested)
    elif isinstance(value, list):
        for nested in value:
            validate_relative_values(nested)


def validate_result(payload: dict, commit_sha: str) -> None:
    require(payload.get("schema_version") == 1, "result schema mismatch")
    require(payload.get("mode") == "ALDI_GATE_D3_RECOVERY_INVENTORY_V01", "result mode mismatch")
    require(payload.get("decision") in ALLOWED_DECISIONS, "result decision mismatch")
    require(payload.get("issue_number") == 266, "result issue mismatch")
    require(payload.get("raw_evidence_exported") is False, "raw evidence export drift")
    require(payload.get("raw_exception_exported") is False, "raw exception export drift")
    require(payload.get("production_eligible") is False, "production eligibility drift")
    require(payload.get("review_pack_execution_authorized") is False, "review pack authority drift")
    safety = payload.get("safety")
    require(isinstance(safety, dict) and safety.get("inventory_only") is True, "inventory-only safety missing")
    require(safety.get("strict_49_plus_41_frozen_contract_unchanged") is True, "frozen contract drift")
    for key, value in safety.items():
        if key not in {"inventory_only", "strict_49_plus_41_frozen_contract_unchanged"}:
            require(value is False, f"unsafe result flag: {key}")
    fingerprint = payload.get("diagnostic_fingerprint")
    require(isinstance(fingerprint, str) and len(fingerprint) == 64, "fingerprint missing")
    int(fingerprint, 16)
    validate_relative_values(payload)


def write_manifest(export: Path, result: Path, commit_sha: str, decision: str, fingerprint: str) -> None:
    files = []
    for path in sorted(export.iterdir(), key=lambda item: item.name):
        if path.name == "dispatcher-evidence-manifest.json":
            continue
        require(path.is_file() and not path.is_symlink(), "unexpected export member")
        files.append({"path": path.name, "bytes": path.stat().st_size, "sha256": sha_file(path)})
    payload = {
        "schema_version": 1,
        "audit": AUDIT,
        "commit_sha": commit_sha,
        "decision": decision,
        "diagnostic_fingerprint": fingerprint,
        "files": files,
        "sanitization_passed": True,
        "raw_evidence_exported": False,
        "raw_exception_exported": False,
        "archive_extraction_authorized": False,
        "review_pack_execution_authorized": False,
        "production_apply_authorized": False,
    }
    (export / "dispatcher-evidence-manifest.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> int:
    if os.geteuid() != 0:
        print("dispatcher requires root", file=sys.stderr)
        return 1
    if len(sys.argv) != 3:
        print("usage: dispatcher <commit-sha> <export-dir>", file=sys.stderr)
        return 2
    commit_sha, export_raw = sys.argv[1], sys.argv[2]
    try:
        require(len(commit_sha) == 40 and all(ch in "0123456789abcdef" for ch in commit_sha), "invalid commit SHA")
        export = Path(export_raw)
        validate_export_dir(export)
        config = load_config(commit_sha)
        require(STATE_ROOT.is_dir() and not STATE_ROOT.is_symlink(), "state root missing or unsafe")
        user = pwd.getpwnam("andris")
        STAGING_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chown(STAGING_ROOT, user.pw_uid, user.pw_gid)
        os.chmod(STAGING_ROOT, 0o700)
        staging = Path(tempfile.mkdtemp(prefix="aldi-gate-d3-", dir=STAGING_ROOT))
        os.chown(staging, user.pw_uid, user.pw_gid)
        try:
            result = staging / "diagnostic-result.json"
            command = [
                "/usr/sbin/runuser", "-u", "andris", "--",
                "/usr/bin/env", "-i",
                "HOME=/home/andris", "USER=andris", "LOGNAME=andris",
                "PATH=/usr/local/bin:/usr/bin:/bin", "LANG=C.UTF-8",
                "/usr/bin/python3", config["inventory_file"],
                "--state-root", str(STATE_ROOT),
                "--output", str(result),
            ]
            completed = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            (export / "diagnostic-exit-code.txt").write_text(f"{completed.returncode}\n", encoding="utf-8")
            require(completed.returncode == 0, "inventory execution failed")
            require(result.is_file() and not result.is_symlink(), "diagnostic result missing")
            payload = json.loads(result.read_text(encoding="utf-8"))
            validate_result(payload, commit_sha)
            shutil.copyfile(result, export / "diagnostic-result.json", follow_symlinks=False)
            write_manifest(export, result, commit_sha, payload["decision"], payload["diagnostic_fingerprint"])
            return 0
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    except Exception as exc:
        failure = {"schema_version": 1, "audit": AUDIT, "error_type": type(exc).__name__, "raw_exception_exported": False}
        try:
            export = Path(export_raw)
            if export.is_dir() and not export.is_symlink():
                (export / "diagnostic-failure.json").write_text(json.dumps(failure, sort_keys=True) + "\n", encoding="utf-8")
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
