#!/usr/bin/env python3
from __future__ import annotations

import grp
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
from typing import Any

AUDIT = "aldi-gate-d4-backup-discovery"
SCHEMA_VERSION = 1
CONFIG = Path("/etc/hermes-deals-audits.d/aldi-gate-d4-backup-discovery.json")
REQUEST = Path("/etc/hermes-deals-audits.d/aldi-gate-d4-backup-discovery-request.json")
RUNTIME_ROOT = Path("/usr/local/libexec/hermes-deals-audits/aldi-gate-d4-backup-discovery")
D4_FILENAME = "aldi_gate_d4_backup_discovery.py"
D3_FILENAME = "aldi_gate_d3_recovery_inventory.py"
EXPECTED_D3_SHA256 = "606976346177b3a6a2965c6aab536f249f2097c41e08e76f3704990fe0473cb8"
AUDIT_USER = "andris"
RUNNER_USER = "github-runner"
STAGING_ROOT = Path("/home/andris/hermes-deals-runner-evidence")
EXPORT_ROOT = Path("/home/github-runner/_work/_temp")
EXPORT_PREFIX = "hermes-deals-aldi-gate-d4-backup-discovery-"
ALLOWED_DECISIONS = {
    "NO_CANDIDATE_IN_DESIGNATED_ROOTS",
    "READY_FOR_IRRECOVERABLE_DECISION",
    "PLAUSIBLE_RECOVERY_CANDIDATE_FOUND",
    "AMBIGUOUS_PLAUSIBLE_RECOVERY_CANDIDATES",
}
AUTHORITY_FLAGS = (
    "raw_evidence_export_authorized",
    "raw_exception_export_authorized",
    "network_acquisition_authorized",
    "archive_extraction_authorized",
    "source_or_corpus_mutation_authorized",
    "manifest_regeneration_authorized",
    "parser_execution_authorized",
    "candidate_creation_authorized",
    "review_or_publication_write_authorized",
    "production_database_write_authorized",
    "production_deployment_authorized",
    "scheduler_systemd_canary_authorized",
    "destructive_cleanup_authorized",
    "newer_41_plus_41_substitution_authorized",
    "historical_recovery_binding_authorized",
    "irrecoverable_decision_recording_authorized",
)
CONFIG_FIELDS = {
    "schema_version",
    "audit",
    "commit_sha",
    "d4_file",
    "d4_sha256",
    "d3_file",
    "d3_sha256",
    "request_file",
    "request_sha256",
    "dispatcher_sha256",
    *AUTHORITY_FLAGS,
}
ALLOWED_FAILURE_STAGES = {
    "argument_validation",
    "export_validation",
    "runner_validation",
    "config_validation",
    "request_validation",
    "runtime_validation",
    "staging_preparation",
    "d4_cli_preflight",
    "d4_execution",
    "result_validation",
    "result_export",
}


class DispatchError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DispatchError(message)


def is_hex(value: Any, length: int) -> bool:
    return isinstance(value, str) and len(value) == length and all(ch in "0123456789abcdef" for ch in value)


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def regular_root_file(path: Path, mode: int = 0o600) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (
        stat.S_ISREG(info.st_mode)
        and not path.is_symlink()
        and info.st_uid == 0
        and info.st_gid == 0
        and stat.S_IMODE(info.st_mode) == mode
    )


def root_runtime_file(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (
        stat.S_ISREG(info.st_mode)
        and not path.is_symlink()
        and info.st_uid == 0
        and info.st_gid == 0
        and stat.S_IMODE(info.st_mode) in {0o444, 0o555}
    )


def root_runtime_dir(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (
        stat.S_ISDIR(info.st_mode)
        and not path.is_symlink()
        and info.st_uid == 0
        and info.st_gid == 0
        and stat.S_IMODE(info.st_mode) in {0o555, 0o755}
    )


def runner_in_docker_group(username: str) -> bool:
    user = pwd.getpwnam(username)
    for row in grp.getgrall():
        if row.gr_name == "docker" and (username in row.gr_mem or row.gr_gid == user.pw_gid):
            return True
    return False


def validate_export_dir(path: Path, runner: pwd.struct_passwd) -> Path:
    require(path.is_absolute() and ".." not in path.parts, "export path invalid")
    require(path.parent.resolve(strict=True) == EXPORT_ROOT.resolve(strict=True), "export parent mismatch")
    require(path.name.startswith(EXPORT_PREFIX), "export prefix mismatch")
    require(path.is_dir() and not path.is_symlink(), "export directory missing or unsafe")
    info = path.lstat()
    require(info.st_uid == runner.pw_uid and info.st_gid == runner.pw_gid, "export owner mismatch")
    require(stat.S_IMODE(info.st_mode) == 0o700, "export mode mismatch")
    require(not any(path.iterdir()), "export directory must start empty")
    return path


def load_config(commit_sha: str) -> dict[str, Any]:
    require(regular_root_file(CONFIG), "config missing or unsafe")
    try:
        payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DispatchError("config invalid") from exc
    require(isinstance(payload, dict) and set(payload) == CONFIG_FIELDS, "config schema mismatch")
    require(payload.get("schema_version") == SCHEMA_VERSION, "config schema version mismatch")
    require(payload.get("audit") == AUDIT, "config audit mismatch")
    require(payload.get("commit_sha") == commit_sha, "config commit mismatch")
    require(is_hex(payload.get("d4_sha256"), 64), "D4 SHA invalid")
    require(payload.get("d3_sha256") == EXPECTED_D3_SHA256, "D3 SHA mismatch")
    require(is_hex(payload.get("request_sha256"), 64), "request SHA invalid")
    require(is_hex(payload.get("dispatcher_sha256"), 64), "dispatcher SHA invalid")
    for flag in AUTHORITY_FLAGS:
        require(payload.get(flag) is False, f"unsafe config flag: {flag}")

    runtime = RUNTIME_ROOT / commit_sha
    require(payload.get("d4_file") == str(runtime / D4_FILENAME), "D4 path mismatch")
    require(payload.get("d3_file") == str(runtime / D3_FILENAME), "D3 path mismatch")
    require(payload.get("request_file") == str(REQUEST), "request path mismatch")
    return payload


def validate_request(config: dict[str, Any]) -> None:
    require(regular_root_file(REQUEST), "request missing or unsafe")
    require(sha_file(REQUEST) == config["request_sha256"], "request SHA drift")


def validate_runtime(config: dict[str, Any], commit_sha: str) -> tuple[Path, Path]:
    runtime = RUNTIME_ROOT / commit_sha
    require(root_runtime_dir(runtime), "runtime directory missing or unsafe")
    d4 = Path(config["d4_file"])
    d3 = Path(config["d3_file"])
    require(d4.parent == runtime and d3.parent == runtime, "runtime path escaped target directory")
    require(root_runtime_file(d4), "D4 runtime missing or unsafe")
    require(root_runtime_file(d3), "D3 runtime missing or unsafe")
    require(sha_file(d4) == config["d4_sha256"], "D4 runtime SHA drift")
    require(sha_file(d3) == EXPECTED_D3_SHA256, "D3 runtime SHA drift")
    require(sha_file(Path(__file__)) == config["dispatcher_sha256"], "dispatcher SHA drift")
    return d4, d3


def validate_relative_values(value: Any) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in {"path", "root", "page_images_root", "source", "state_root"} and isinstance(nested, str):
                require(not nested.startswith("/"), "absolute evidence path in result")
                require(".." not in Path(nested).parts, "traversing evidence path in result")
            validate_relative_values(nested)
    elif isinstance(value, list):
        for nested in value:
            validate_relative_values(nested)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def validate_result(payload: dict[str, Any]) -> None:
    require(payload.get("schema_version") == 1, "result schema mismatch")
    require(payload.get("mode") == "ALDI_GATE_D4_BOUNDED_BACKUP_DISCOVERY", "result mode mismatch")
    require(payload.get("issue_number") == 631, "result issue mismatch")
    require(payload.get("decision") in ALLOWED_DECISIONS, "result decision mismatch")
    require(payload.get("provenance_binding_complete") is False, "provenance binding drift")
    require(payload.get("historical_recovery_authorized") is False, "historical recovery authority drift")
    require(payload.get("irrecoverable_decision_recorded") is False, "irrecoverable decision drift")
    fingerprint = payload.get("diagnostic_fingerprint")
    require(is_hex(fingerprint, 64), "fingerprint missing")
    fingerprint_source = dict(payload)
    fingerprint_source.pop("diagnostic_fingerprint", None)
    require(hashlib.sha256(canonical_bytes(fingerprint_source)).hexdigest() == fingerprint, "fingerprint mismatch")
    safety = payload.get("safety")
    require(isinstance(safety, dict), "result safety missing")
    require(safety.get("explicit_roots_only") is True, "explicit-roots safety missing")
    require(safety.get("strict_49_plus_41_frozen_contract_unchanged") is True, "frozen contract drift")
    for key, value in safety.items():
        if key not in {"explicit_roots_only", "strict_49_plus_41_frozen_contract_unchanged"}:
            require(value is False, f"unsafe result flag: {key}")
    validate_relative_values(payload)


def audit_user_command(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [
            "/usr/sbin/runuser", "-u", AUDIT_USER, "--",
            "/usr/bin/env", "-i",
            f"HOME=/home/{AUDIT_USER}", f"USER={AUDIT_USER}", f"LOGNAME={AUDIT_USER}",
            "PATH=/usr/local/bin:/usr/bin:/bin", "LANG=C.UTF-8",
            *args,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=180,
    )


def bounded_exit_reason(prefix: str, returncode: int) -> str:
    if returncode == 0:
        return f"{prefix}_ok"
    if returncode in {1, 2, 126, 127}:
        return f"{prefix}_exit_{returncode}"
    return f"{prefix}_exit_other"


def write_manifest(
    export: Path,
    *,
    commit_sha: str,
    decision: str,
    fingerprint: str,
    request_sha256: str,
    d4_sha256: str,
) -> None:
    files = []
    for path in sorted(export.iterdir(), key=lambda item: item.name):
        if path.name == "dispatcher-evidence-manifest.json":
            continue
        require(path.name in {"diagnostic-result.json", "diagnostic-exit-code.txt"}, "unexpected export member")
        require(path.is_file() and not path.is_symlink(), "unexpected export member type")
        files.append({"path": path.name, "bytes": path.stat().st_size, "sha256": sha_file(path)})
    payload = {
        "schema_version": 1,
        "audit": AUDIT,
        "commit_sha": commit_sha,
        "decision": decision,
        "diagnostic_fingerprint": fingerprint,
        "request_bound": True,
        "request_sha256": request_sha256,
        "d4_sha256": d4_sha256,
        "d3_sha256": EXPECTED_D3_SHA256,
        "files": files,
        "sanitization_passed": True,
        "raw_evidence_exported": False,
        "raw_exception_exported": False,
        "network_acquisition_authorized": False,
        "archive_extraction_authorized": False,
        "source_or_corpus_mutation_authorized": False,
        "review_or_publication_write_authorized": False,
        "production_database_write_authorized": False,
        "production_deployment_authorized": False,
        "scheduler_systemd_canary_authorized": False,
        "destructive_cleanup_authorized": False,
        "newer_41_plus_41_substitution_authorized": False,
        "historical_recovery_binding_authorized": False,
        "irrecoverable_decision_recording_authorized": False,
    }
    (export / "dispatcher-evidence-manifest.json").write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
    )


def prepare_staging() -> tuple[Path, pwd.struct_passwd]:
    user = pwd.getpwnam(AUDIT_USER)
    if STAGING_ROOT.exists() or STAGING_ROOT.is_symlink():
        require(STAGING_ROOT.is_dir() and not STAGING_ROOT.is_symlink(), "staging root unsafe")
        info = STAGING_ROOT.lstat()
        require(info.st_uid == user.pw_uid and info.st_gid == user.pw_gid, "staging root owner mismatch")
        require(stat.S_IMODE(info.st_mode) == 0o700, "staging root mode mismatch")
    else:
        require(STAGING_ROOT.parent.is_dir() and not STAGING_ROOT.parent.is_symlink(), "staging parent unsafe")
        STAGING_ROOT.mkdir(mode=0o700, parents=False)
        os.chown(STAGING_ROOT, user.pw_uid, user.pw_gid)
        os.chmod(STAGING_ROOT, 0o700)
    staging = Path(tempfile.mkdtemp(prefix="aldi-gate-d4-", dir=STAGING_ROOT))
    os.chown(staging, user.pw_uid, user.pw_gid)
    os.chmod(staging, 0o700)
    return staging, user


def stage_request(staging: Path, user: pwd.struct_passwd) -> Path:
    staged = staging / "request.json"
    shutil.copyfile(REQUEST, staged, follow_symlinks=False)
    os.chown(staged, user.pw_uid, user.pw_gid)
    os.chmod(staged, 0o600)
    return staged


def main() -> int:
    failure_stage = "argument_validation"
    failure_reason = "dispatch_error"
    export_raw = sys.argv[2] if len(sys.argv) >= 3 else ""
    safe_export: Path | None = None
    try:
        require(os.geteuid() == 0, "dispatcher requires root")
        require(len(sys.argv) == 3, "dispatcher argument count mismatch")
        commit_sha, export_raw = sys.argv[1], sys.argv[2]
        require(is_hex(commit_sha, 40), "invalid commit SHA")

        failure_stage = "runner_validation"
        runner = pwd.getpwnam(RUNNER_USER)
        require(not runner_in_docker_group(RUNNER_USER), "runner docker group membership forbidden")

        failure_stage = "export_validation"
        export = validate_export_dir(Path(export_raw), runner)
        safe_export = export

        failure_stage = "config_validation"
        config = load_config(commit_sha)

        failure_stage = "request_validation"
        validate_request(config)

        failure_stage = "runtime_validation"
        d4, _d3 = validate_runtime(config, commit_sha)

        failure_stage = "staging_preparation"
        staging, audit_user = prepare_staging()
        try:
            staged_request = stage_request(staging, audit_user)
            result = staging / "diagnostic-result.json"

            failure_stage = "d4_cli_preflight"
            cli = audit_user_command("/usr/bin/python3", str(d4), "--help")
            failure_reason = bounded_exit_reason("d4_cli_preflight", cli.returncode)
            require(cli.returncode == 0, "D4 CLI preflight failed")

            failure_stage = "d4_execution"
            completed = audit_user_command(
                "/usr/bin/python3", str(d4),
                "--request", str(staged_request),
                "--output", str(result),
            )
            (export / "diagnostic-exit-code.txt").write_text(f"{completed.returncode}\n", encoding="utf-8")
            failure_reason = bounded_exit_reason("d4_execution", completed.returncode)
            require(completed.returncode == 0, "D4 execution failed")

            failure_stage = "result_validation"
            require(result.is_file() and not result.is_symlink(), "diagnostic result missing")
            try:
                payload = json.loads(result.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise DispatchError("diagnostic result invalid") from exc
            require(isinstance(payload, dict), "diagnostic result root invalid")
            validate_result(payload)

            failure_stage = "result_export"
            shutil.copyfile(result, export / "diagnostic-result.json", follow_symlinks=False)
            write_manifest(
                export,
                commit_sha=commit_sha,
                decision=payload["decision"],
                fingerprint=payload["diagnostic_fingerprint"],
                request_sha256=config["request_sha256"],
                d4_sha256=config["d4_sha256"],
            )
            return 0
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    except Exception as exc:
        if failure_stage not in ALLOWED_FAILURE_STAGES:
            failure_stage = "argument_validation"
        failure = {
            "schema_version": 1,
            "audit": AUDIT,
            "error_type": type(exc).__name__,
            "failure_stage": failure_stage,
            "reason_code": failure_reason,
            "raw_exception_exported": False,
            "raw_stderr_exported": False,
            "raw_request_exported": False,
        }
        try:
            if safe_export is not None:
                failure_path = safe_export / "diagnostic-failure.json"
                if not failure_path.exists():
                    failure_path.write_text(json.dumps(failure, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
