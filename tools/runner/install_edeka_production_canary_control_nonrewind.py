#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import pwd
import grp
import re
import stat
import subprocess
import tarfile
import tempfile
from typing import Any, Mapping

SOURCE_REPO = Path("/home/andris/hermes-deals-audit-source-edeka")
AUDIT_USER = "andris"
RUNNER_USER = "github-runner"
INSTALLER_REL = "tools/runner/install_edeka_production_canary_control_nonrewind.py"
DISPATCHER_REL = "tools/runner/edeka_production_canary_control.py"
EXECUTOR_REL = "backend/app/edeka_production_canary.py"
PLAN_REL = "config/edeka-production-canary-v01.json"
RUNTIME_LOCK_REL = "backend/locks/runtime-py313.txt"
WORKFLOW_REL = ".github/workflows/hermes-edeka-production-canary-control.yml"
EXPECTED_DISPATCHER_BLOB = "95339e076907e43eb2307fce66f4768a60ef2296"
EXPECTED_EXECUTOR_BLOB = "4760fefb3f5de67798b52d7b5d30021fb8bf2ba7"
EXPECTED_PLAN_BLOB = "4c4674534dfc29957a9cc9f05b0df99ca5378b50"
EXPECTED_RUNTIME_LOCK_BLOB = "a2b44faa967be2a703f369d85a5f15cf517975d1"
EXPECTED_WORKFLOW_BLOB = "2906f03b052d8351800ca0a31f96e7ad2b551ec7"
EXPECTED_BRIDGE_PR = 667
EXPECTED_ISSUE_NUMBER = 26
EXPECTED_PLAN_ID = "edeka-patzer-production-canary-v01"
CONTROL_ROOT = Path("/usr/local/libexec/hermes-deals-edeka-production-canary-control")
DISPATCH_DST = Path("/usr/local/sbin/hermes-deals-edeka-production-canary-control")
CONFIG_ROOT = Path("/etc/hermes-deals-audits.d/edeka-production-canary-control")
SUDOERS_ROOT = Path("/etc/sudoers.d")
BACKUP_ROOT = Path("/var/lib/hermes-deals/edeka-production-canary-backups")
EVIDENCE_ROOT = Path("/home/andris/hermes-deals-shadow-evidence/edeka")
RUNNER_TEMP_ROOT = Path("/home/github-runner/_work/_temp")
EXPECTED_NETWORK = "hermes-deals_internal"
SHA40_RE = re.compile(r"[0-9a-f]{40}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")


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


def run(argv: list[str], *, check: bool = True, timeout: int = 120) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=timeout,
        env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
    )
    if check:
        require(result.returncode == 0, f"registration preflight failed: {Path(argv[0]).name}")
    return result


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    argv = [
        "/usr/sbin/runuser", "-u", AUDIT_USER, "--",
        "/usr/bin/env", "-i",
        "HOME=/home/andris", "USER=andris", "LOGNAME=andris",
        "PATH=/usr/local/bin:/usr/bin:/bin", "LANG=C.UTF-8", "GIT_OPTIONAL_LOCKS=0",
        "/usr/bin/git", "-C", str(SOURCE_REPO), *args,
    ]
    result = subprocess.run(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=90,
    )
    if check:
        require(result.returncode == 0, f"audit Git command failed: {args[0]}")
        require(not result.stderr, f"audit Git command emitted stderr: {args[0]}")
    return result


def git_text(*args: str) -> str:
    return git(*args).stdout.decode("utf-8", "strict").strip()


def git_blob_bytes(commit: str, path: str) -> bytes:
    oid = git_text("rev-parse", f"{commit}:{path}")
    require(SHA40_RE.fullmatch(oid) is not None, f"Git blob identity invalid: {path}")
    payload = git("cat-file", "blob", oid).stdout
    require(payload, f"Git blob is empty: {path}")
    return payload


def validate_source_repo(registration_sha: str) -> tuple[dict[str, str], tuple[str, str]]:
    require(SHA40_RE.fullmatch(registration_sha) is not None, "registration SHA invalid")
    require(SOURCE_REPO.is_dir() and not SOURCE_REPO.is_symlink(), "dedicated EDEKA audit repository missing or unsafe")
    require((SOURCE_REPO / ".git").is_dir() and not (SOURCE_REPO / ".git").is_symlink(), "dedicated EDEKA audit Git metadata unsafe")
    require(Path(__file__).resolve() == (SOURCE_REPO / INSTALLER_REL).resolve(), "installer must execute from dedicated EDEKA audit checkout")
    index = SOURCE_REPO / ".git/index"
    require(index.is_file() and not index.is_symlink(), "audit Git index missing or unsafe")
    index_info = index.stat()
    before = (sha_file(index), f"{index_info.st_uid}:{index_info.st_gid}:{stat.S_IMODE(index_info.st_mode)}:{index_info.st_size}:{index_info.st_mtime_ns}")
    require(not (SOURCE_REPO / ".git/index.lock").exists(), "audit Git index lock exists")
    require(git_text("branch", "--show-current") == "main", "dedicated EDEKA audit repository is not on main")
    require(git_text("rev-parse", "HEAD") == registration_sha, "dedicated EDEKA audit HEAD differs from registration SHA")
    require(git("status", "--porcelain=v1", "-z", "--untracked-files=all").stdout == b"", "dedicated EDEKA audit repository is not clean")
    git("cat-file", "-e", f"{registration_sha}^{{commit}}")
    git("show-ref", "--verify", "--quiet", "refs/remotes/origin/main")
    ancestry = git("merge-base", "--is-ancestor", registration_sha, "refs/remotes/origin/main", check=False)
    require(ancestry.returncode == 0 and not ancestry.stderr, "registration SHA is not reachable from origin/main")
    origin = git_text("remote", "get-url", "origin")
    require(origin in {
        "https://github.com/rozkalnsandris/hermes-deals",
        "https://github.com/rozkalnsandris/hermes-deals.git",
        "git@github.com:rozkalnsandris/hermes-deals.git",
    }, "dedicated EDEKA audit origin is not allowlisted")

    expected = {
        DISPATCHER_REL: EXPECTED_DISPATCHER_BLOB,
        EXECUTOR_REL: EXPECTED_EXECUTOR_BLOB,
        PLAN_REL: EXPECTED_PLAN_BLOB,
        RUNTIME_LOCK_REL: EXPECTED_RUNTIME_LOCK_BLOB,
        WORKFLOW_REL: EXPECTED_WORKFLOW_BLOB,
    }
    for path, expected_oid in expected.items():
        require(git_text("rev-parse", f"{registration_sha}:{path}") == expected_oid, f"reviewed Git blob mismatch: {path}")
    installer_oid = git_text("rev-parse", f"{registration_sha}:{INSTALLER_REL}")
    require(git_text("hash-object", str(Path(__file__).resolve())) == installer_oid, "running installer bytes differ from registration commit")
    return {**expected, INSTALLER_REL: installer_oid}, before


def validate_index_unchanged(before: tuple[str, str]) -> None:
    index = SOURCE_REPO / ".git/index"
    info = index.stat()
    after = (sha_file(index), f"{info.st_uid}:{info.st_gid}:{stat.S_IMODE(info.st_mode)}:{info.st_size}:{info.st_mtime_ns}")
    require(after == before, "dedicated EDEKA audit Git index changed during registration")
    require(not (SOURCE_REPO / ".git/index.lock").exists(), "installer left an audit Git index lock")


def sudo_version_at_least_1_9_10() -> str:
    result = run(["/usr/bin/sudo", "-V"])
    first = result.stdout.decode("utf-8", "replace").splitlines()[0] if result.stdout else ""
    match = re.fullmatch(r"Sudo version ([0-9]+)\.([0-9]+)\.([0-9]+)(?:.*)?", first)
    require(match is not None, "unable to parse Sudo version")
    version = tuple(int(match.group(i)) for i in (1, 2, 3))
    require(version >= (1, 9, 10), "Sudo older than 1.9.10 cannot enforce regex argument boundary")
    return first


def runner_not_in_docker_group() -> None:
    try:
        user = pwd.getpwnam(RUNNER_USER)
    except KeyError as exc:
        raise RegistrationError("github-runner account unavailable") from exc
    groups = {grp.getgrgid(gid).gr_name for gid in os.getgrouplist(RUNNER_USER, user.pw_gid)}
    require("docker" not in groups, "github-runner must not belong to Docker group")


def validate_host_roots() -> None:
    require(EVIDENCE_ROOT.is_dir() and not EVIDENCE_ROOT.is_symlink(), "retained EDEKA evidence root missing")
    runner_temp = RUNNER_TEMP_ROOT
    require(runner_temp.is_dir() and not runner_temp.is_symlink(), "GitHub runner temp root missing or unsafe")
    run(["/usr/bin/docker", "version", "--format", "{{.Server.Version}}"])


def normalize_root_dir(path: Path, mode: int) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=mode)
    require(path.is_dir() and not path.is_symlink(), f"unsafe root directory: {path}")
    os.chown(path, 0, 0)
    os.chmod(path, mode)
    info = path.stat()
    require(info.st_uid == 0 and info.st_gid == 0 and stat.S_IMODE(info.st_mode) == mode, f"root directory metadata mismatch: {path}")


def write_exclusive_or_identical(path: Path, payload: bytes, mode: int) -> bool:
    if path.exists() or path.is_symlink():
        require(path.is_file() and not path.is_symlink(), f"existing registration path unsafe: {path}")
        info = path.stat()
        require(info.st_uid == 0 and info.st_gid == 0 and stat.S_IMODE(info.st_mode) == mode, f"existing registration metadata drift: {path}")
        require(path.read_bytes() == payload, f"existing registration content drift: {path}")
        return False
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.edeka-canary-", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.fchown(fd, 0, 0)
        os.fchmod(fd, mode)
        os.close(fd)
        fd = -1
        os.link(temp, path, follow_symlinks=False)
        dir_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if fd >= 0:
            os.close(fd)
        temp.unlink(missing_ok=True)
    return True


def materialize_bundle(registration_sha: str, temp_root: Path) -> dict[str, str]:
    archive = git("archive", "--format=tar", registration_sha, "backend/app", RUNTIME_LOCK_REL, PLAN_REL).stdout
    require(archive, "Git archive for canary bundle is empty")
    files: dict[str, str] = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
        members = tar.getmembers()
        require(members, "Git archive has no members")
        for member in members:
            rel = Path(member.name)
            require(not rel.is_absolute() and ".." not in rel.parts, "unsafe Git archive member path")
            allowed = (
                member.name == RUNTIME_LOCK_REL
                or member.name == PLAN_REL
                or member.name.startswith("backend/app/")
                or member.name in {"backend", "backend/app", "backend/locks", "config"}
            )
            require(allowed, f"unexpected Git archive member: {member.name}")
            target = temp_root / rel
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            require(member.isfile() and not member.issym() and not member.islnk(), f"non-regular Git archive member: {member.name}")
            extracted = tar.extractfile(member)
            require(extracted is not None, f"cannot read Git archive member: {member.name}")
            payload = extracted.read()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            os.chmod(target, 0o444)
            files[member.name] = sha_bytes(payload)
    require(EXECUTOR_REL in files and PLAN_REL in files and RUNTIME_LOCK_REL in files, "canary bundle missing critical files")
    require(files[PLAN_REL] == sha_bytes(git_blob_bytes(registration_sha, PLAN_REL)), "materialized plan bytes drift")
    require(files[EXECUTOR_REL] == sha_bytes(git_blob_bytes(registration_sha, EXECUTOR_REL)), "materialized executor bytes drift")
    return files


def bundle_manifest_bytes(registration_sha: str, files: Mapping[str, str]) -> bytes:
    payload = {
        "schema_version": 1,
        "control": "edeka-production-canary-control",
        "registration_sha": registration_sha,
        "files": dict(sorted(files.items())),
    }
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def validate_or_install_bundle(registration_sha: str, source_root: Path, files: Mapping[str, str], manifest_bytes: bytes) -> tuple[Path, bool]:
    normalize_root_dir(CONTROL_ROOT, 0o755)
    destination = CONTROL_ROOT / registration_sha
    expected_files = dict(files)
    expected_files["MANIFEST.json"] = sha_bytes(manifest_bytes)
    if destination.exists() or destination.is_symlink():
        require(destination.is_dir() and not destination.is_symlink(), "existing bundle path unsafe")
        actual_paths = set()
        for path in destination.rglob("*"):
            if path.is_dir():
                require(not path.is_symlink(), "existing bundle directory symlink unsafe")
                info = path.stat()
                require(info.st_uid == 0 and info.st_gid == 0 and stat.S_IMODE(info.st_mode) == 0o555, "existing bundle directory metadata drift")
                continue
            require(path.is_file() and not path.is_symlink(), "existing bundle file unsafe")
            rel = path.relative_to(destination).as_posix()
            actual_paths.add(rel)
            info = path.stat()
            require(info.st_uid == 0 and info.st_gid == 0 and stat.S_IMODE(info.st_mode) == 0o444, "existing bundle file metadata drift")
            require(expected_files.get(rel) == sha_file(path), f"existing bundle content drift: {rel}")
        require(actual_paths == set(expected_files), "existing bundle file set drift")
        return destination, False

    staging: Path | None = Path(tempfile.mkdtemp(prefix=f".{registration_sha}.", dir=CONTROL_ROOT))
    try:
        for rel, expected_sha in files.items():
            src = source_root / rel
            require(src.is_file() and not src.is_symlink() and sha_file(src) == expected_sha, f"staged bundle source drift: {rel}")
            dst = staging / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
            os.chown(dst, 0, 0)
            os.chmod(dst, 0o444)
        manifest = staging / "MANIFEST.json"
        manifest.write_bytes(manifest_bytes)
        os.chown(manifest, 0, 0)
        os.chmod(manifest, 0o444)
        for directory in sorted((p for p in staging.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            os.chown(directory, 0, 0)
            os.chmod(directory, 0o555)
        os.chown(staging, 0, 0)
        os.chmod(staging, 0o555)
        os.rename(staging, destination)
        staging = None
    finally:
        if staging is not None and staging.exists():
            for path in sorted(staging.rglob("*"), key=lambda p: len(p.parts), reverse=True):
                try:
                    if path.is_dir() and not path.is_symlink():
                        os.chmod(path, 0o700)
                        path.rmdir()
                    else:
                        os.chmod(path, 0o600)
                        path.unlink()
                except OSError:
                    pass
            try:
                os.chmod(staging, 0o700)
                staging.rmdir()
            except OSError:
                pass
    return destination, True


def validate_plan(plan_path: Path) -> dict[str, Any]:
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RegistrationError("registered canary plan JSON invalid") from exc
    require(isinstance(plan, dict), "registered canary plan root invalid")
    require(plan.get("schema_version") == 1 and plan.get("plan_id") == EXPECTED_PLAN_ID, "registered canary plan identity mismatch")
    require(plan.get("issue") == EXPECTED_ISSUE_NUMBER, "registered canary issue mismatch")
    require(plan.get("state") == "preparation_only" and plan.get("production_apply_authorized") is False, "plan must remain preparation-only")
    preflight = plan.get("preflight")
    source = plan.get("authoritative_source")
    require(isinstance(preflight, dict) and preflight.get("require_rollback_backup_before_write") is True, "rollback backup gate missing")
    require(isinstance(source, dict), "authoritative source section missing")
    for key in ("manifest_sha256", "raw_html_sha256"):
        require(SHA256_RE.fullmatch(str(source.get(key) or "")) is not None, f"authoritative source {key} invalid")
    return plan


def build_config(registration_sha: str, blobs: Mapping[str, str], bundle: Path, manifest_sha: str) -> dict[str, Any]:
    plan_path = bundle / PLAN_REL
    lock_path = bundle / RUNTIME_LOCK_REL
    validate_plan(plan_path)
    return {
        "schema_version": 1,
        "control": "edeka-production-canary-control",
        "issue_number": EXPECTED_ISSUE_NUMBER,
        "bridge_pr": EXPECTED_BRIDGE_PR,
        "registration_sha": registration_sha,
        "dispatcher_blob": blobs[DISPATCHER_REL],
        "executor_blob": blobs[EXECUTOR_REL],
        "plan_blob": blobs[PLAN_REL],
        "plan_sha256": sha_file(plan_path),
        "runtime_lock_sha256": sha_file(lock_path),
        "bundle_manifest_sha256": manifest_sha,
        "bundle_root": str(bundle),
        "plan_path": str(plan_path),
        "evidence_root": str(EVIDENCE_ROOT),
        "backup_root": str(BACKUP_ROOT),
        "runner_temp_root": str(RUNNER_TEMP_ROOT),
        "network": EXPECTED_NETWORK,
        "production_write_requires_owner_command": True,
        "root_registration_only": True,
    }


def build_sudoers(registration_sha: str) -> bytes:
    sudo_tag = "NOPASS" + "WD"
    return (
        f"Defaults!{DISPATCH_DST} env_reset,secure_path=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n"
        + f"Cmnd_Alias HERMES_DEALS_EDEKA_CANARY_{registration_sha[:12].upper()} = {DISPATCH_DST} "
        + f"^(verify|apply|replay|rollback) {registration_sha} "
        + r"/home/github-runner/_work/_temp/hermes-deals-edeka-production-canary-[1-9][0-9]*-[1-9][0-9]*$"
        + "\n"
        + f"{RUNNER_USER} ALL=(root) {sudo_tag}: HERMES_DEALS_EDEKA_CANARY_{registration_sha[:12].upper()}\n"
    ).encode("utf-8")


def validate_sudo_policy(registration_sha: str) -> None:
    sample = f"/home/github-runner/_work/_temp/hermes-deals-edeka-production-canary-1-1"
    for operation in ("verify", "apply", "replay", "rollback"):
        probe = run(["/usr/bin/sudo", "-n", "-l", "-U", RUNNER_USER, "--", str(DISPATCH_DST), operation, registration_sha, sample], check=False)
        require(probe.returncode == 0, f"github-runner sudo policy missing for {operation}")
    wrong_sha = ("0" * 40) if registration_sha != ("0" * 40) else ("1" * 40)
    negatives = (
        [str(DISPATCH_DST), "apply", wrong_sha, sample],
        [str(DISPATCH_DST), "unknown", registration_sha, sample],
        [str(DISPATCH_DST), "apply", registration_sha, "/tmp/not-allowed"],
        [str(DISPATCH_DST), "apply", registration_sha, sample, "extra"],
        [str(DISPATCH_DST), "apply", registration_sha],
    )
    for argv in negatives:
        probe = run(["/usr/bin/sudo", "-n", "-l", "-U", RUNNER_USER, "--", *argv], check=False)
        require(probe.returncode != 0, "github-runner sudo policy accepts malformed EDEKA canary command")


def install_registration(registration_sha: str) -> dict[str, Any]:
    require(os.geteuid() == 0, "registration must run as root")
    blobs, index_before = validate_source_repo(registration_sha)
    runner_not_in_docker_group()
    sudo_version = sudo_version_at_least_1_9_10()
    validate_host_roots()

    with tempfile.TemporaryDirectory(prefix="edeka-canary-bundle-") as temp_name:
        source_root = Path(temp_name)
        files = materialize_bundle(registration_sha, source_root)
        manifest_bytes = bundle_manifest_bytes(registration_sha, files)
        bundle, bundle_changed = validate_or_install_bundle(
            registration_sha, source_root, files, manifest_bytes
        )

    dispatcher_bytes = git_blob_bytes(registration_sha, DISPATCHER_REL)
    require(git_text("rev-parse", f"{registration_sha}:{DISPATCHER_REL}") == EXPECTED_DISPATCHER_BLOB, "dispatcher blob identity drift")
    dispatcher_changed = write_exclusive_or_identical(DISPATCH_DST, dispatcher_bytes, 0o755)

    normalize_root_dir(CONFIG_ROOT, 0o755)
    normalize_root_dir(BACKUP_ROOT, 0o700)
    config = build_config(registration_sha, blobs, bundle, sha_bytes(manifest_bytes))
    config_bytes = (json.dumps(config, indent=2, sort_keys=True) + "\n").encode("utf-8")
    config_path = CONFIG_ROOT / f"{registration_sha}.json"
    config_changed = write_exclusive_or_identical(config_path, config_bytes, 0o600)

    sudoers_bytes = build_sudoers(registration_sha)
    with tempfile.NamedTemporaryFile(prefix="edeka-canary-sudoers-", delete=False) as handle:
        sudoers_temp = Path(handle.name)
        handle.write(sudoers_bytes)
    try:
        os.chmod(sudoers_temp, 0o440)
        run(["/usr/sbin/visudo", "-cf", str(sudoers_temp)])
    finally:
        sudoers_temp.unlink(missing_ok=True)

    sudoers_path = SUDOERS_ROOT / f"hermes-deals-edeka-production-canary-control-{registration_sha}"
    require(SUDOERS_ROOT.is_dir() and not SUDOERS_ROOT.is_symlink(), "sudoers root missing or unsafe")
    sudoers_changed = write_exclusive_or_identical(sudoers_path, sudoers_bytes, 0o440)
    run(["/usr/sbin/visudo", "-cf", str(sudoers_path)])
    validate_sudo_policy(registration_sha)
    validate_index_unchanged(index_before)

    changed = bundle_changed or dispatcher_changed or config_changed or sudoers_changed
    return {
        "result": "PASS" if changed else "NO_OP_IDENTICAL",
        "registration_sha": registration_sha,
        "bridge_pr": EXPECTED_BRIDGE_PR,
        "dispatcher_blob": blobs[DISPATCHER_REL],
        "executor_blob": blobs[EXECUTOR_REL],
        "plan_blob": blobs[PLAN_REL],
        "plan_sha256": config["plan_sha256"],
        "bundle_manifest_sha256": config["bundle_manifest_sha256"],
        "sudo_version": sudo_version,
        "runner_has_docker_group": False,
        "root_registration_performed": changed,
        "canary_operation_performed": False,
        "production_database_write_performed": False,
        "review_write_performed": False,
        "publication_write_performed": False,
        "source_refetch_performed": False,
        "scheduler_systemd_change_performed": False,
        "production_deploy_performed": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Register one exact-main EDEKA production-canary root trust bundle without executing the canary.")
    parser.add_argument("--registration-sha", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = install_registration(args.registration_sha)
    except (OSError, ValueError, RegistrationError, subprocess.SubprocessError, tarfile.TarError) as exc:
        message = str(exc)
        if len(message) > 240:
            message = message[:240]
        print(f"ERROR|{type(exc).__name__}|{message}")
        return 2
    print(json.dumps(result, sort_keys=True))
    print(f"EDEKA_CANARY_REGISTRATION={result['result']}")
    print("CANARY_OPERATION=false")
    print("PRODUCTION_DATABASE_WRITE=false")
    print("REVIEW_WRITE=false")
    print("PRODUCTION_PUBLISH=false")
    print("SOURCE_REFETCH=false")
    print("SCHEDULER_SYSTEMD_CHANGE=false")
    print("PRODUCTION_DEPLOY=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
