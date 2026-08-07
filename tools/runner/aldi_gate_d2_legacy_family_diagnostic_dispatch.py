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

AUDIT = "aldi-gate-d2-legacy-family-diagnostic"
CONFIG = Path("/etc/hermes-deals-audits.d/aldi-gate-d2-legacy-family-diagnostic.json")
STATE_ROOT = Path("/home/andris/.local/state/hermes-deals/aldi-perfect-shadow")
STAGING_ROOT = Path("/home/andris/hermes-deals-runner-evidence")
EXPORT_ROOT = Path("/home/github-runner/_work/_temp")
EXPORT_PREFIX = "hermes-deals-aldi-gate-d2-legacy-family-diagnostic-"
AUDIT_USER = "andris"
AUDIT_HOME = "/home/andris"
SAFE_DECISIONS = {
    "EXACT_LEGACY_FAMILY_FOUND",
    "NO_VALID_LEGACY_FAMILY",
    "MULTIPLE_VALID_LEGACY_FAMILIES",
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
    parts = Path(value).parts
    return ".." not in parts and "." not in parts


def load_config() -> dict[str, Any]:
    require(regular_file(CONFIG), "registration config missing or unsafe")
    info = CONFIG.stat()
    require(info.st_uid == 0 and info.st_gid == 0, "registration config owner mismatch")
    require(stat.S_IMODE(info.st_mode) == 0o600, "registration config mode mismatch")
    value = json.loads(CONFIG.read_text(encoding="utf-8"))
    require(isinstance(value, dict), "registration config must be an object")
    return value


def validated_export_dir(raw: str) -> Path:
    require(raw and not raw.endswith("/.."), "empty or unsafe export path")
    path = Path(raw)
    require(path.is_absolute(), "export path must be absolute")
    require(path.parent.resolve(strict=True) == EXPORT_ROOT, "export parent rejected")
    require(path.name.startswith(EXPORT_PREFIX), "export name rejected")
    require(regular_dir(path), "export directory missing or unsafe")
    return path.resolve(strict=True)


def copy_export(source: Path, destination: Path) -> dict[str, Any]:
    require(regular_file(source), f"export source missing: {source.name}")
    require(not destination.exists(), f"export destination exists: {destination.name}")
    shutil.copyfile(source, destination, follow_symlinks=False)
    os.chmod(destination, 0o600)
    shutil.chown(destination, user="github-runner", group="github-runner")
    return {
        "path": destination.name,
        "bytes": destination.stat().st_size,
        "sha256": sha_file(destination),
    }


def validate_result(result: Mapping[str, Any]) -> None:
    require(result.get("schema_version") == 1, "unexpected diagnostic schema")
    require(result.get("mode") == "ALDI_GATE_D2_LEGACY_FAMILY_DIAGNOSTIC_V01", "unexpected diagnostic mode")
    require(result.get("decision") in SAFE_DECISIONS, "unsafe diagnostic decision")
    require(result.get("state_root") == ".", "state root must stay relative")
    require(result.get("raw_evidence_exported") is False, "raw evidence export unexpectedly true")
    require(result.get("raw_exception_exported") is False, "raw exception export unexpectedly true")
    require(result.get("production_eligible") is False, "production eligibility unexpectedly true")
    require(result.get("review_pack_execution_authorized") is False, "review pack unexpectedly authorized")
    safety = result.get("safety")
    require(isinstance(safety, Mapping), "safety block missing")
    require(safety.get("diagnostic_only") is True, "diagnostic-only flag missing")
    require(safety.get("strict_49_plus_41_frozen_contract_unchanged") is True, "49+41 frozen contract drift")
    for key in (
        "network_acquisition_authorized",
        "parser_execution_authorized",
        "source_or_corpus_mutation_authorized",
        "candidate_creation_authorized",
        "production_database_write_authorized",
        "review_write_authorized",
        "automatic_approval_authorized",
        "automatic_publication_authorized",
        "production_deployment_authorized",
        "scheduler_or_retry_authorized",
        "production_canary_authorized",
        "b15m2_v08_action_authorized",
    ):
        require(safety.get(key) is False, f"unsafe safety flag: {key}")
    candidates = result.get("candidates")
    require(isinstance(candidates, list), "candidate diagnostics missing")
    for row in candidates:
        require(isinstance(row, Mapping), "diagnostic row invalid")
        require(safe_relative(row.get("manifest_path")), "unsafe manifest path")
    page_sets = result.get("valid_page_sets")
    require(isinstance(page_sets, list), "valid page sets missing")
    for row in page_sets:
        require(isinstance(row, Mapping), "page-set row invalid")
        paths = row.get("manifest_paths")
        require(isinstance(paths, list), "page-set paths invalid")
        for value in paths:
            require(safe_relative(value), "unsafe page-set manifest path")


def write_failure(export_dir: Path, error_type: str, error_sha256: str) -> None:
    payload = {
        "schema_version": 1,
        "audit": AUDIT,
        "status": "DIAGNOSTIC_EXECUTION_BLOCKED",
        "error_type": error_type,
        "error_sha256": error_sha256,
        "raw_exception_exported": False,
        "raw_evidence_exported": False,
        "production_apply_authorized": False,
        "review_pack_execution_authorized": False,
    }
    path = export_dir / "diagnostic-failure.json"
    require(not path.exists(), "failure destination already exists")
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    shutil.chown(path, user="github-runner", group="github-runner")


def dispatch(commit_sha: str, export_raw: str) -> int:
    require(os.geteuid() == 0, "dispatcher must run as root")
    require(len(commit_sha) == 40 and all(ch in "0123456789abcdef" for ch in commit_sha), "invalid commit SHA")
    export_dir = validated_export_dir(export_raw)
    config = load_config()
    require(config.get("audit") == AUDIT, "registration audit mismatch")
    require(config.get("commit_sha") == commit_sha, "registration commit mismatch")
    diagnostic = Path(str(config.get("diagnostic_file") or ""))
    gate_d_tool = Path(str(config.get("frozen_gate_d_tool") or ""))
    require(regular_file(diagnostic), "registered diagnostic missing or unsafe")
    require(sha_file(diagnostic) == config.get("diagnostic_sha256"), "diagnostic SHA drift")
    require(regular_file(gate_d_tool), "frozen Gate D tool missing or unsafe")
    require(sha_file(gate_d_tool) == config.get("frozen_gate_d_sha256"), "frozen Gate D SHA drift")
    require(sha_file(Path(__file__)) == config.get("dispatcher_sha256"), "dispatcher registration drift")
    require(regular_dir(STATE_ROOT), "ALDI state root missing or unsafe")
    require(regular_dir(STAGING_ROOT), "runner evidence staging root missing or unsafe")

    staging = STAGING_ROOT / export_dir.name
    require(not staging.exists(), "staging path already exists")
    staging.mkdir(mode=0o700)
    shutil.chown(staging, user=AUDIT_USER, group=AUDIT_USER)
    result_path = staging / "diagnostic-result.json"
    stdout_path = staging / "diagnostic.stdout"
    stderr_path = staging / "diagnostic.stderr"
    exit_path = staging / "diagnostic-exit-code.txt"

    command = [
        "/usr/sbin/runuser", "-u", AUDIT_USER, "--",
        "/usr/bin/env", "-i",
        f"HOME={AUDIT_HOME}", f"USER={AUDIT_USER}", f"LOGNAME={AUDIT_USER}",
        "PATH=/usr/local/bin:/usr/bin:/bin", "LANG=C.UTF-8",
        "/usr/bin/python3", str(diagnostic),
        "--state-root", str(STATE_ROOT),
        "--gate-d-tool", str(gate_d_tool),
        "--output", str(result_path),
    ]

    try:
        with stdout_path.open("wb") as out_handle, stderr_path.open("wb") as err_handle:
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=out_handle,
                stderr=err_handle,
                check=False,
                timeout=300,
            )
        exit_path.write_text(f"{completed.returncode}\n", encoding="ascii")
        os.chmod(exit_path, 0o600)
        if completed.returncode != 0:
            error_bytes = stderr_path.read_bytes() if stderr_path.exists() else b""
            write_failure(export_dir, "DiagnosticExecutionError", hashlib.sha256(error_bytes).hexdigest())
            return 1
        require(regular_file(result_path), "diagnostic result missing or unsafe")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        require(isinstance(result, dict), "diagnostic result must be an object")
        validate_result(result)

        exported = [
            copy_export(result_path, export_dir / "diagnostic-result.json"),
            copy_export(exit_path, export_dir / "diagnostic-exit-code.txt"),
        ]
        manifest = {
            "schema_version": 1,
            "audit": AUDIT,
            "commit_sha": commit_sha,
            "decision": result["decision"],
            "diagnostic_fingerprint": result.get("diagnostic_fingerprint"),
            "files": sorted(exported, key=lambda row: row["path"]),
            "raw_evidence_exported": False,
            "raw_exception_exported": False,
            "production_apply_authorized": False,
            "review_pack_execution_authorized": False,
            "sanitization_passed": True,
        }
        manifest_path = export_dir / "dispatcher-evidence-manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(manifest_path, 0o600)
        shutil.chown(manifest_path, user="github-runner", group="github-runner")
        return 0
    except Exception as exc:
        write_failure(export_dir, type(exc).__name__, hashlib.sha256(str(exc).encode()).hexdigest())
        return 1
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("usage: dispatcher <registered-commit-sha> <runner-export-dir>", file=sys.stderr)
        return 2
    try:
        return dispatch(args[0], args[1])
    except Exception as exc:
        print(f"DISPATCH_RESULT=BLOCKED error_type={type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
