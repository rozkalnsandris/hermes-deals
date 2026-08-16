#!/usr/bin/env python3
from __future__ import annotations

import grp
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any, Mapping

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
ISSUE_NUMBER = 631
REQUEST_SCHEMA_V1 = 1
REQUEST_SCHEMA_V2 = 2
MAX_INPUTS = 8
INPUT_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
FORBIDDEN_BROAD_ROOTS = {Path("/"), Path("/home"), Path("/home/andris")}
GATE_D3_STATE_ROOT = Path("/home/andris/.local/state/hermes-deals/aldi-perfect-shadow")
ALLOWED_DECISIONS = {
    "NO_CANDIDATE_IN_DESIGNATED_ROOTS",
    "READY_FOR_IRRECOVERABLE_DECISION",
    "PLAUSIBLE_RECOVERY_CANDIDATE_FOUND",
    "AMBIGUOUS_PLAUSIBLE_RECOVERY_CANDIDATES",
}
RESULT_FIELDS = {
    "schema_version",
    "mode",
    "issue_number",
    "request_schema_version",
    "decision",
    "authoritative_source_set_complete",
    "designated_root_count",
    "designated_file_count",
    "designated_input_count",
    "complete_recovery_source_count",
    "distinct_complete_identity_count",
    "root_reports",
    "file_reports",
    "plausible_recovery_sources",
    "complete_identities",
    "provenance_binding_complete",
    "historical_recovery_authorized",
    "irrecoverable_decision_recorded",
    "next_step",
    "safety",
    "diagnostic_fingerprint",
}
RESULT_SAFETY_FIELDS = {
    "explicit_inputs_only",
    "explicit_roots_only",
    "exact_file_allowlist_enabled",
    "raw_page_bytes_exported",
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
    "strict_49_plus_41_frozen_contract_unchanged",
}
RESULT_NEXT_STEPS = {
    "NO_CANDIDATE_IN_DESIGNATED_ROOTS": "authorize_additional_explicit_backup_inputs_or_mark_source_set_complete",
    "READY_FOR_IRRECOVERABLE_DECISION": "record_separate_owner_reviewed_irrecoverable_decision",
    "PLAUSIBLE_RECOVERY_CANDIDATE_FOUND": "bind_candidate_to_independent_historical_provenance",
    "AMBIGUOUS_PLAUSIBLE_RECOVERY_CANDIDATES": "bind_and_resolve_distinct_historical_identities",
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
    "input_staging",
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


def nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


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
    require(set(payload) == RESULT_FIELDS, "result field set mismatch")
    require(payload.get("schema_version") == 1, "result schema mismatch")
    require(payload.get("mode") == "ALDI_GATE_D4_BOUNDED_BACKUP_DISCOVERY", "result mode mismatch")
    require(payload.get("issue_number") == ISSUE_NUMBER, "result issue mismatch")
    request_schema = payload.get("request_schema_version")
    require(request_schema in {REQUEST_SCHEMA_V1, REQUEST_SCHEMA_V2}, "request schema mismatch")
    require(payload.get("decision") in ALLOWED_DECISIONS, "result decision mismatch")

    authoritative_complete = payload.get("authoritative_source_set_complete")
    require(isinstance(authoritative_complete, bool), "authoritative completeness invalid")
    for field in (
        "designated_root_count",
        "designated_file_count",
        "designated_input_count",
        "complete_recovery_source_count",
        "distinct_complete_identity_count",
    ):
        require(nonnegative_int(payload.get(field)), f"{field} invalid")

    root_count = payload["designated_root_count"]
    file_count = payload["designated_file_count"]
    input_count = payload["designated_input_count"]
    source_count = payload["complete_recovery_source_count"]
    identity_count = payload["distinct_complete_identity_count"]
    require(input_count == root_count + file_count and input_count > 0, "designated input count mismatch")
    if request_schema == REQUEST_SCHEMA_V1:
        require(file_count == 0, "v1 result cannot contain exact-file inputs")

    root_reports = payload.get("root_reports")
    file_reports = payload.get("file_reports")
    source_rows = payload.get("plausible_recovery_sources")
    identities = payload.get("complete_identities")
    require(isinstance(root_reports, list) and len(root_reports) == root_count, "root report count mismatch")
    require(isinstance(file_reports, list) and len(file_reports) == file_count, "file report count mismatch")
    require(isinstance(source_rows, list) and len(source_rows) == source_count, "source count mismatch")
    require(isinstance(identities, list) and len(identities) == identity_count, "identity count mismatch")
    require(
        all(is_hex(identity, 64) for identity in identities) and identities == sorted(set(identities)),
        "complete identities invalid",
    )

    source_identities: list[str] = []
    for row in source_rows:
        require(isinstance(row, dict), "recovery source row invalid")
        identity = row.get("identity_sha256")
        require(is_hex(identity, 64), "recovery source identity invalid")
        source_identities.append(identity)
    require(sorted(set(source_identities)) == identities, "recovery source identities mismatch")

    if identity_count > 1:
        expected_decision = "AMBIGUOUS_PLAUSIBLE_RECOVERY_CANDIDATES"
    elif identity_count == 1:
        expected_decision = "PLAUSIBLE_RECOVERY_CANDIDATE_FOUND"
    elif authoritative_complete:
        expected_decision = "READY_FOR_IRRECOVERABLE_DECISION"
    else:
        expected_decision = "NO_CANDIDATE_IN_DESIGNATED_ROOTS"
    require(payload.get("decision") == expected_decision, "decision/count semantics mismatch")
    require(payload.get("next_step") == RESULT_NEXT_STEPS[expected_decision], "next-step semantics mismatch")

    require(payload.get("provenance_binding_complete") is False, "provenance binding drift")
    require(payload.get("historical_recovery_authorized") is False, "historical recovery authority drift")
    require(payload.get("irrecoverable_decision_recorded") is False, "irrecoverable decision drift")

    safety = payload.get("safety")
    require(isinstance(safety, dict) and set(safety) == RESULT_SAFETY_FIELDS, "result safety schema mismatch")
    require(safety.get("explicit_inputs_only") is True, "explicit-inputs safety missing")
    require(safety.get("explicit_roots_only") is (file_count == 0), "explicit-roots safety mismatch")
    require(safety.get("exact_file_allowlist_enabled") is (file_count > 0), "exact-file safety mismatch")
    require(safety.get("strict_49_plus_41_frozen_contract_unchanged") is True, "frozen contract drift")
    for key, value in safety.items():
        if key not in {
            "explicit_inputs_only",
            "explicit_roots_only",
            "exact_file_allowlist_enabled",
            "strict_49_plus_41_frozen_contract_unchanged",
        }:
            require(value is False, f"unsafe result flag: {key}")

    fingerprint = payload.get("diagnostic_fingerprint")
    require(is_hex(fingerprint, 64), "fingerprint missing")
    fingerprint_source = dict(payload)
    fingerprint_source.pop("diagnostic_fingerprint", None)
    require(hashlib.sha256(canonical_bytes(fingerprint_source)).hexdigest() == fingerprint, "fingerprint mismatch")
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
    """Legacy helper retained for focused tests; main uses stage_authorized_request."""
    staged = staging / "request.json"
    shutil.copyfile(REQUEST, staged, follow_symlinks=False)
    os.chown(staged, user.pw_uid, user.pw_gid)
    os.chmod(staged, 0o600)
    return staged


def _load_bound_request() -> dict[str, Any]:
    try:
        payload = json.loads(REQUEST.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DispatchError("request invalid") from exc
    require(isinstance(payload, dict), "request root must be an object")
    return payload


def _validate_input_id(raw_id: Any, seen: set[str]) -> str:
    require(isinstance(raw_id, str) and INPUT_ID_RE.fullmatch(raw_id) is not None, "invalid backup input id")
    require(raw_id not in seen, "duplicate backup input id")
    seen.add(raw_id)
    return raw_id


def _resolve_original_root(path_value: Any) -> Path:
    require(isinstance(path_value, str) and path_value.startswith("/"), "backup root must be absolute")
    path = Path(path_value)
    require(".." not in path.parts, "backup root must not contain parent traversal")
    require(not path.is_symlink(), "backup root missing or unsafe")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise DispatchError("backup root missing") from exc
    require(resolved == path, "backup root path must not contain symlinks")
    require(resolved.is_dir() and not resolved.is_symlink(), "backup root missing or unsafe")
    require(resolved not in FORBIDDEN_BROAD_ROOTS, "backup root is too broad")
    require(resolved != GATE_D3_STATE_ROOT, "Gate D3 state root was already exhaustively covered")
    return resolved


def _resolve_original_file(path_value: Any) -> Path:
    require(isinstance(path_value, str) and path_value.startswith("/"), "backup file must be absolute")
    path = Path(path_value)
    require(".." not in path.parts, "backup file must not contain parent traversal")
    require(not path.is_symlink(), "backup file missing or unsafe")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise DispatchError("backup file missing") from exc
    require(resolved == path, "backup file path must not contain symlinks")
    require(resolved.is_file() and not resolved.is_symlink(), "backup file missing or unsafe")
    require(resolved.name.endswith(".tar.gz") or resolved.name.endswith(".tgz"), "backup file must be a supported archive")
    require(
        resolved != GATE_D3_STATE_ROOT and GATE_D3_STATE_ROOT not in resolved.parents,
        "Gate D3 state root was already exhaustively covered",
    )
    return resolved


def _validate_bound_inputs(payload: Mapping[str, Any]) -> tuple[int, bool, list[tuple[str, Path]], list[tuple[str, Path]]]:
    schema = payload.get("schema_version")
    require(schema in {REQUEST_SCHEMA_V1, REQUEST_SCHEMA_V2}, "unsupported request schema_version")
    if schema == REQUEST_SCHEMA_V1:
        require(
            set(payload) == {"schema_version", "issue_number", "authoritative_source_set_complete", "roots"},
            "request fields mismatch",
        )
        raw_files: list[Any] = []
    else:
        require(
            set(payload) == {"schema_version", "issue_number", "authoritative_source_set_complete", "roots", "files"},
            "request fields mismatch",
        )
        raw_files = payload.get("files")
        require(isinstance(raw_files, list), "files must be a list")

    require(payload.get("issue_number") == ISSUE_NUMBER, "request issue_number mismatch")
    complete = payload.get("authoritative_source_set_complete")
    require(isinstance(complete, bool), "authoritative_source_set_complete must be boolean")
    raw_roots = payload.get("roots")
    require(isinstance(raw_roots, list), "roots must be a list")
    if schema == REQUEST_SCHEMA_V1:
        require(raw_roots, "at least one explicit backup root is required")
    else:
        require(raw_roots or raw_files, "at least one explicit backup input is required")
    require(len(raw_roots) + len(raw_files) <= MAX_INPUTS, "too many backup inputs")

    roots: list[tuple[str, Path]] = []
    files: list[tuple[str, Path]] = []
    seen_ids: set[str] = set()
    resolved_roots: set[Path] = set()
    resolved_files: set[Path] = set()
    for raw in raw_roots:
        require(isinstance(raw, dict) and set(raw) == {"id", "path"}, "backup root entry fields mismatch")
        input_id = _validate_input_id(raw.get("id"), seen_ids)
        root = _resolve_original_root(raw.get("path"))
        require(root not in resolved_roots, "duplicate backup root path")
        for _, existing in roots:
            require(root not in existing.parents and existing not in root.parents, "backup roots must not overlap")
        resolved_roots.add(root)
        roots.append((input_id, root))
    for raw in raw_files:
        require(isinstance(raw, dict) and set(raw) == {"id", "path"}, "backup file entry fields mismatch")
        input_id = _validate_input_id(raw.get("id"), seen_ids)
        exact_file = _resolve_original_file(raw.get("path"))
        require(exact_file not in resolved_files, "duplicate backup file path")
        for _, root in roots:
            require(root not in exact_file.parents, "backup file must not be inside a designated root")
        resolved_files.add(exact_file)
        files.append((input_id, exact_file))
    roots.sort(key=lambda row: row[0])
    files.sort(key=lambda row: row[0])
    return int(schema), complete, roots, files


def _make_private_dir(path: Path, user: pwd.struct_passwd) -> None:
    path.mkdir(mode=0o700, parents=False)
    os.chown(path, user.pw_uid, user.pw_gid)
    os.chmod(path, 0o700)


def _copy_regular_file(source: Path, destination: Path, user: pwd.struct_passwd) -> None:
    before = source.lstat()
    require(stat.S_ISREG(before.st_mode) and not source.is_symlink(), "authorized input contains unsupported file type")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(source, flags)
    try:
        opened = os.fstat(fd)
        require(stat.S_ISREG(opened.st_mode), "authorized input file changed type")
        require((opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino), "authorized input changed during staging")
        with os.fdopen(fd, "rb", closefd=False) as src, destination.open("xb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
        closed_snapshot = os.fstat(fd)
        require(
            (closed_snapshot.st_dev, closed_snapshot.st_ino, closed_snapshot.st_size, closed_snapshot.st_mtime_ns, closed_snapshot.st_ctime_ns)
            == (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns),
            "authorized input changed during staging",
        )
    finally:
        os.close(fd)
    os.chown(destination, user.pw_uid, user.pw_gid)
    os.chmod(destination, 0o600)


def _copy_authorized_tree(source: Path, destination: Path, user: pwd.struct_passwd) -> None:
    before = source.lstat()
    require(stat.S_ISDIR(before.st_mode) and not source.is_symlink(), "authorized backup root missing or unsafe")
    _make_private_dir(destination, user)
    try:
        entries = sorted(os.scandir(source), key=lambda item: item.name)
    except OSError as exc:
        raise DispatchError("authorized backup root unreadable by dispatcher") from exc
    entry_names = [entry.name for entry in entries]
    for entry in entries:
        require(entry.name not in {".", ".."}, "authorized input entry invalid")
        src = source / entry.name
        dst = destination / entry.name
        require(not entry.is_symlink(), "authorized input contains symlink")
        if entry.is_dir(follow_symlinks=False):
            _copy_authorized_tree(src, dst, user)
        elif entry.is_file(follow_symlinks=False):
            _copy_regular_file(src, dst, user)
        else:
            raise DispatchError("authorized input contains unsupported file type")
    after = source.lstat()
    require((after.st_dev, after.st_ino) == (before.st_dev, before.st_ino), "authorized backup root changed during staging")
    try:
        after_names = sorted(entry.name for entry in os.scandir(source))
    except OSError as exc:
        raise DispatchError("authorized backup root unreadable by dispatcher") from exc
    require(after_names == entry_names, "authorized backup root changed during staging")


def stage_authorized_request(staging: Path, user: pwd.struct_passwd) -> Path:
    """Root-only staging boundary for the exact immutable request inputs.

    Original paths are validated while privileged, copied without following symlinks
    into one private audit-user-owned staging tree, and replaced only in an internal
    request that is never exported. The unprivileged D4 scanner sees no inaccessible
    root-owned parent and receives no authority to enumerate sibling backup roots.
    """
    payload = _load_bound_request()
    schema, complete, roots, files = _validate_bound_inputs(payload)
    inputs_root = staging / "authorized-inputs"
    _make_private_dir(inputs_root, user)

    staged_roots: list[dict[str, str]] = []
    staged_files: list[dict[str, str]] = []
    for index, (input_id, source) in enumerate(roots):
        destination = inputs_root / f"root-{index:02d}"
        _copy_authorized_tree(source, destination, user)
        staged_roots.append({"id": input_id, "path": str(destination)})
    for index, (input_id, source) in enumerate(files):
        suffix = ".tar.gz" if source.name.endswith(".tar.gz") else ".tgz"
        destination = inputs_root / f"file-{index:02d}{suffix}"
        _copy_regular_file(source, destination, user)
        staged_files.append({"id": input_id, "path": str(destination)})

    rewritten: dict[str, Any] = {
        "schema_version": schema,
        "issue_number": ISSUE_NUMBER,
        "authoritative_source_set_complete": complete,
        "roots": staged_roots,
    }
    if schema == REQUEST_SCHEMA_V2:
        rewritten["files"] = staged_files
    staged_request = staging / "execution-request.json"
    staged_request.write_text(json.dumps(rewritten, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    os.chown(staged_request, user.pw_uid, user.pw_gid)
    os.chmod(staged_request, 0o600)
    return staged_request


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
            failure_stage = "input_staging"
            staged_request = stage_authorized_request(staging, audit_user)
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
