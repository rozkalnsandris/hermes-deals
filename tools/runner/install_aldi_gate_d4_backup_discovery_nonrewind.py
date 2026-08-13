#!/usr/bin/env python3
from __future__ import annotations

import grp
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import re
import stat
import subprocess
import sys
import tempfile
from typing import Any, Mapping

REPO = Path("/home/andris/hermes-deals-audit-source")
AUDIT_USER = "andris"
AUDIT_HOME = "/home/andris"
RUNNER_USER = "github-runner"
AUDIT = "aldi-gate-d4-backup-discovery"
EXPECTED_TARGET_SHA = "8b9b7e66c754cb7f8a82d4d67503d59fd2ff000e"
D4_PATH = "tools/aldi_gate_d4_backup_discovery.py"
D3_PATH = "tools/aldi_gate_d3_recovery_inventory.py"
DISPATCHER_PATH = "tools/runner/aldi_gate_d4_backup_discovery_dispatch.py"
EXPECTED_D4_BLOB = "f8ec4abb3f0c416335144f0f18e8a7c323353f4a"
EXPECTED_D3_BLOB = "4c4432baa048011ac9dfd427d8e2a0d0b4cfd2a7"
EXPECTED_DISPATCHER_BLOB = "2e7f8dd4f5b0dece36403072b6dfa6dab3aadd35"
EXPECTED_D3_SHA256 = "606976346177b3a6a2965c6aab536f249f2097c41e08e76f3704990fe0473cb8"
AUDITS_ROOT = Path("/usr/local/libexec/hermes-deals-audits")
INSTALL_ROOT = AUDITS_ROOT / AUDIT
DISPATCH_DST = Path("/usr/local/sbin/hermes-deals-aldi-gate-d4-backup-discovery")
CONFIG_DST = Path("/etc/hermes-deals-audits.d/aldi-gate-d4-backup-discovery.json")
REQUEST_DST = Path("/etc/hermes-deals-audits.d/aldi-gate-d4-backup-discovery-request.json")
SUDOERS_DST = Path("/etc/sudoers.d/hermes-deals-aldi-gate-d4-backup-discovery")
RUNNER_SERVICE = "actions.runner.rozkalnsandris-hermes-deals.rpi5-hermes-deals-audit.service"
INPUT_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
MAX_INPUTS = 8
FORBIDDEN_BROAD_ROOTS = {"/", "/home", "/home/andris"}
EXHAUSTED_D3_ROOT = "/home/andris/.local/state/hermes-deals/aldi-perfect-shadow"
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


class RegistrationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RegistrationError(message)


def sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def index_snapshot() -> tuple[str, int, int, str]:
    index = REPO / ".git/index"
    require(index.is_file() and not index.is_symlink(), "audit repo index missing or unsafe")
    require(not (REPO / ".git/index.lock").exists(), "audit repo index locked")
    info = index.stat()
    owner = f"{pwd.getpwuid(info.st_uid).pw_name}:{grp.getgrgid(info.st_gid).gr_name}"
    require(owner == "andris:andris", "audit repo index owner mismatch")
    return owner, stat.S_IMODE(info.st_mode), info.st_size, sha_file(index)


def audit_git(*args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    command = [
        "/usr/sbin/runuser", "-u", AUDIT_USER, "--",
        "/usr/bin/env", "-i",
        f"HOME={AUDIT_HOME}", f"USER={AUDIT_USER}", f"LOGNAME={AUDIT_USER}",
        "PATH=/usr/local/bin:/usr/bin:/bin", "LANG=C.UTF-8", "GIT_OPTIONAL_LOCKS=0",
        "/usr/bin/git", "-C", str(REPO), *args,
    ]
    completed = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    if check:
        require(completed.returncode == 0, f"audit git failed: {args[0]}")
        require(not completed.stderr, f"audit git emitted stderr: {args[0]}")
    return completed


def validate_source_repo(target_sha: str) -> tuple[tuple[str, int, int, str], str]:
    require(target_sha == EXPECTED_TARGET_SHA, "target SHA is not reviewed Gate D4 runtime SHA")
    before = index_snapshot()
    require(audit_git("branch", "--show-current").stdout.decode().strip() == "main", "audit repo branch mismatch")
    head = audit_git("rev-parse", "HEAD").stdout.decode().strip()
    require(len(head) == 40, "audit repo HEAD invalid")
    require(audit_git("status", "--porcelain=v1", "-z", "--untracked-files=all").stdout == b"", "audit repo dirty")

    target = audit_git("rev-parse", "--verify", f"{target_sha}^{{commit}}").stdout.decode().strip()
    require(target == target_sha, "reviewed target commit object unavailable")
    ancestry = audit_git("merge-base", "--is-ancestor", target_sha, head, check=False)
    require(ancestry.returncode == 0, "reviewed target is not an ancestor of audit repo HEAD")
    require(not ancestry.stderr, "ancestry check emitted stderr")

    expected = {
        D4_PATH: EXPECTED_D4_BLOB,
        D3_PATH: EXPECTED_D3_BLOB,
        DISPATCHER_PATH: EXPECTED_DISPATCHER_BLOB,
    }
    for path, blob in expected.items():
        actual = audit_git("rev-parse", f"{target_sha}:{path}").stdout.decode().strip()
        require(actual == blob, f"reviewed Git blob mismatch: {path}")
    require(index_snapshot() == before, "audit repo index changed during source validation")
    return before, head


def read_exact_blob(blob_oid: str) -> bytes:
    completed = audit_git("cat-file", "blob", blob_oid)
    require(completed.stdout, "reviewed Git blob is empty")
    return completed.stdout


def regular_root_file(path: Path, mode: int) -> bool:
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


def _canonical_absolute_string(value: Any, *, kind: str) -> str:
    require(isinstance(value, str) and value.startswith("/"), f"backup {kind} must be absolute")
    path = PurePosixPath(value)
    require(".." not in path.parts, f"backup {kind} must not contain parent traversal")
    normalized = str(path)
    require(normalized == value, f"backup {kind} path must be canonical")
    return normalized


def _canonical_root_string(value: Any) -> str:
    normalized = _canonical_absolute_string(value, kind="root")
    require(normalized not in FORBIDDEN_BROAD_ROOTS, "backup root is too broad")
    require(normalized != EXHAUSTED_D3_ROOT, "Gate D3 state root was already covered")
    return normalized


def _canonical_file_string(value: Any) -> str:
    normalized = _canonical_absolute_string(value, kind="file")
    require(
        normalized.endswith(".tar.gz") or normalized.endswith(".tgz"),
        "backup file must be a supported archive",
    )
    exhausted = PurePosixPath(EXHAUSTED_D3_ROOT)
    path = PurePosixPath(normalized)
    require(path != exhausted and exhausted not in path.parents, "Gate D3 state root was already covered")
    return normalized


def _validate_input_id(raw_id: Any, ids: set[str]) -> str:
    require(isinstance(raw_id, str) and INPUT_ID_RE.fullmatch(raw_id) is not None, "request input id invalid")
    require(raw_id not in ids, "duplicate request input id")
    ids.add(raw_id)
    return raw_id


def validate_request_payload(payload: Mapping[str, Any]) -> None:
    schema = payload.get("schema_version")
    require(schema in {1, 2}, "request schema mismatch")
    if schema == 1:
        require(
            set(payload) == {"schema_version", "issue_number", "authoritative_source_set_complete", "roots"},
            "request fields mismatch",
        )
        files: list[Any] = []
    else:
        require(
            set(payload) == {"schema_version", "issue_number", "authoritative_source_set_complete", "roots", "files"},
            "request fields mismatch",
        )
        files = payload.get("files")
        require(isinstance(files, list), "request files invalid")

    require(payload.get("issue_number") == 631, "request issue mismatch")
    require(isinstance(payload.get("authoritative_source_set_complete"), bool), "request completeness flag invalid")
    roots = payload.get("roots")
    require(isinstance(roots, list), "request roots invalid")
    if schema == 1:
        require(1 <= len(roots) <= MAX_INPUTS, "request root count invalid")
    else:
        require(roots or files, "at least one explicit backup input is required")
        require(len(roots) + len(files) <= MAX_INPUTS, "request input count invalid")

    ids: set[str] = set()
    root_paths: list[PurePosixPath] = []
    file_paths: set[PurePosixPath] = set()
    for row in roots:
        require(isinstance(row, Mapping) and set(row) == {"id", "path"}, "request root entry invalid")
        _validate_input_id(row.get("id"), ids)
        normalized = PurePosixPath(_canonical_root_string(row.get("path")))
        require(normalized not in root_paths, "duplicate request root path")
        for existing in root_paths:
            require(
                normalized not in existing.parents and existing not in normalized.parents,
                "request roots must not overlap",
            )
        root_paths.append(normalized)

    for row in files:
        require(isinstance(row, Mapping) and set(row) == {"id", "path"}, "request file entry invalid")
        _validate_input_id(row.get("id"), ids)
        normalized = PurePosixPath(_canonical_file_string(row.get("path")))
        require(normalized not in file_paths, "duplicate request file path")
        for root in root_paths:
            require(root not in normalized.parents, "backup file must not be inside a designated root")
        file_paths.add(normalized)


def validate_owner_request() -> str:
    require(regular_root_file(REQUEST_DST, 0o600), "owner request missing or unsafe")
    try:
        payload = json.loads(REQUEST_DST.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RegistrationError("owner request JSON invalid") from exc
    require(isinstance(payload, Mapping), "owner request root invalid")
    validate_request_payload(payload)
    return sha_file(REQUEST_DST)


def normalize_root_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o755)
    require(path.is_dir() and not path.is_symlink(), f"unsafe install directory: {path}")
    os.chown(path, 0, 0)
    os.chmod(path, 0o755)
    info = path.stat()
    require(info.st_uid == 0 and info.st_gid == 0, f"install directory owner mismatch: {path}")
    require(stat.S_IMODE(info.st_mode) == 0o755, f"install directory mode mismatch: {path}")


def atomic_root_write(path: Path, payload: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chown(temp, 0, 0)
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def install_or_verify_runtime(target_sha: str, d4: bytes, d3: bytes) -> tuple[Path, str, str]:
    normalize_root_dir(AUDITS_ROOT)
    normalize_root_dir(INSTALL_ROOT)
    target = INSTALL_ROOT / target_sha
    if target.exists():
        require(target.is_dir() and not target.is_symlink(), "existing target install path unsafe")
        info = target.stat()
        require(info.st_uid == 0 and info.st_gid == 0 and stat.S_IMODE(info.st_mode) == 0o755, "existing target directory metadata mismatch")
    else:
        target.mkdir(mode=0o755)
        os.chown(target, 0, 0)
        os.chmod(target, 0o755)

    expected = {
        "aldi_gate_d4_backup_discovery.py": d4,
        "aldi_gate_d3_recovery_inventory.py": d3,
    }
    hashes: dict[str, str] = {}
    for name, payload in expected.items():
        path = target / name
        digest = sha_bytes(payload)
        hashes[name] = digest
        if path.exists():
            require(path.is_file() and not path.is_symlink(), f"existing runtime path unsafe: {name}")
            info = path.stat()
            require(info.st_uid == 0 and info.st_gid == 0 and stat.S_IMODE(info.st_mode) == 0o444, f"runtime metadata mismatch: {name}")
            require(sha_file(path) == digest, f"runtime content mismatch: {name}")
        else:
            atomic_root_write(path, payload, 0o444)

    require(hashes["aldi_gate_d3_recovery_inventory.py"] == EXPECTED_D3_SHA256, "reviewed D3 SHA256 mismatch")
    unexpected = sorted(entry.name for entry in target.iterdir() if entry.name not in expected)
    require(not unexpected, "unexpected member in exact target install directory")
    return target, hashes["aldi_gate_d4_backup_discovery.py"], hashes["aldi_gate_d3_recovery_inventory.py"]


def validate_d4_cli_as_audit_user(d4: Path) -> None:
    completed = subprocess.run(
        [
            "/usr/sbin/runuser", "-u", AUDIT_USER, "--",
            "/usr/bin/env", "-i",
            f"HOME={AUDIT_HOME}", f"USER={AUDIT_USER}", f"LOGNAME={AUDIT_USER}",
            "PATH=/usr/local/bin:/usr/bin:/bin", "LANG=C.UTF-8",
            "/usr/bin/python3", str(d4), "--help",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    require(completed.returncode == 0, "installed D4 CLI preflight failed for audit user")
    require(not completed.stderr, "installed D4 CLI preflight emitted stderr")


def validate_runner() -> None:
    active = subprocess.run(["/usr/bin/systemctl", "is-active", "--quiet", RUNNER_SERVICE], check=False)
    require(active.returncode == 0, "audit runner inactive")
    user = pwd.getpwnam(RUNNER_USER)
    groups = {entry.gr_name for entry in grp.getgrall() if RUNNER_USER in entry.gr_mem}
    groups.add(grp.getgrgid(user.pw_gid).gr_name)
    require("docker" not in groups, "github-runner is in docker group")


def install_sudoers() -> None:
    SUDOERS_DST.parent.mkdir(parents=True, exist_ok=True)
    command = f"{DISPATCH_DST} {EXPECTED_TARGET_SHA} /home/github-runner/_work/_temp/hermes-deals-aldi-gate-d4-backup-discovery-*"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=SUDOERS_DST.parent) as handle:
        handle.write(f"{RUNNER_USER} ALL=(root) NOPASSWD: {command}\n")
        temp = Path(handle.name)
    try:
        os.chown(temp, 0, 0)
        os.chmod(temp, 0o440)
        check = subprocess.run(
            ["/usr/sbin/visudo", "-cf", str(temp)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
        )
        require(check.returncode == 0, "sudoers validation failed")
        os.replace(temp, SUDOERS_DST)
        os.chown(SUDOERS_DST, 0, 0)
        os.chmod(SUDOERS_DST, 0o440)
    finally:
        if temp.exists():
            temp.unlink()


def register_runtime(
    target_sha: str,
    runtime: Path,
    d4_sha: str,
    d3_sha: str,
    dispatcher: bytes,
    request_sha: str,
) -> str:
    dispatcher_sha = sha_bytes(dispatcher)
    atomic_root_write(DISPATCH_DST, dispatcher, 0o755)
    install_sudoers()
    config: dict[str, Any] = {
        "schema_version": 1,
        "audit": AUDIT,
        "commit_sha": target_sha,
        "d4_file": str(runtime / "aldi_gate_d4_backup_discovery.py"),
        "d4_sha256": d4_sha,
        "d3_file": str(runtime / "aldi_gate_d3_recovery_inventory.py"),
        "d3_sha256": d3_sha,
        "request_file": str(REQUEST_DST),
        "request_sha256": request_sha,
        "dispatcher_sha256": dispatcher_sha,
    }
    config.update({flag: False for flag in AUTHORITY_FLAGS})
    atomic_root_write(CONFIG_DST, (json.dumps(config, indent=2, sort_keys=True) + "\n").encode(), 0o600)
    return dispatcher_sha


def main() -> int:
    if os.geteuid() != 0:
        print("REGISTRATION_RESULT=BLOCKED reason=requires_root", file=sys.stderr)
        return 1
    if len(sys.argv) != 2 or sys.argv[1] != EXPECTED_TARGET_SHA:
        print("REGISTRATION_RESULT=BLOCKED reason=unexpected_target_sha", file=sys.stderr)
        return 2

    target_sha = sys.argv[1]
    try:
        before, head = validate_source_repo(target_sha)
        validate_runner()
        request_sha = validate_owner_request()
        d4_bytes = read_exact_blob(EXPECTED_D4_BLOB)
        d3_bytes = read_exact_blob(EXPECTED_D3_BLOB)
        dispatcher_bytes = read_exact_blob(EXPECTED_DISPATCHER_BLOB)
        require(index_snapshot() == before, "audit repo index changed while reading reviewed blobs")

        runtime, d4_sha, d3_sha = install_or_verify_runtime(target_sha, d4_bytes, d3_bytes)
        validate_d4_cli_as_audit_user(runtime / "aldi_gate_d4_backup_discovery.py")
        dispatcher_sha = register_runtime(target_sha, runtime, d4_sha, d3_sha, dispatcher_bytes, request_sha)
        require(index_snapshot() == before, "audit repo index changed during non-rewind registration")
        require(audit_git("rev-parse", "HEAD").stdout.decode().strip() == head, "audit repo HEAD changed during registration")
        require(audit_git("status", "--porcelain=v1", "-z", "--untracked-files=all").stdout == b"", "audit repo became dirty")

        print("REGISTRATION_RESULT=PASS")
        print(f"AUDIT={AUDIT}")
        print(f"REGISTERED_COMMIT={target_sha}")
        print(f"AUDIT_REPO_HEAD_UNCHANGED={head}")
        print(f"D4_GIT_BLOB={EXPECTED_D4_BLOB}")
        print(f"D3_GIT_BLOB={EXPECTED_D3_BLOB}")
        print(f"DISPATCHER_GIT_BLOB={EXPECTED_DISPATCHER_BLOB}")
        print(f"D4_SHA256={d4_sha}")
        print(f"D3_SHA256={d3_sha}")
        print(f"DISPATCHER_SHA256={dispatcher_sha}")
        print(f"REQUEST_SHA256={request_sha}")
        print("REQUEST_CONTENT_EXPORTED=false")
        print("NON_REWIND_REGISTRATION=true")
        print("AUDIT_REPO_INDEX_PRESERVED=true")
        print("RUNNER_HAS_DOCKER_GROUP=false")
        for flag in AUTHORITY_FLAGS:
            print(f"{flag.upper()}=false")
        return 0
    except Exception as exc:
        print(f"REGISTRATION_RESULT=BLOCKED error_type={type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
