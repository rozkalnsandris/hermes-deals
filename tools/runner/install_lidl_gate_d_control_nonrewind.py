#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import grp
import re
import stat
import subprocess
import tempfile
from typing import Any, Mapping

SOURCE_REPO = Path("/home/andris/hermes-deals-audit-source-lidl")
AUDIT_USER = "andris"
RUNNER_USER = "github-runner"
INSTALLER_REL = "tools/runner/install_lidl_gate_d_control_nonrewind.py"
DISPATCHER_REL = "tools/runner/lidl_gate_d_control.py"
PLANNER_REL = "tools/lidl_weekly_gate_d_activation_plan.py"
RUNTIME_REL = "tools/lidl_weekly_gate_d_runtime.py"
EXPECTED_DISPATCHER_BLOB = "a96c8817e1e3d6bd386dcf36eb5cc1fe68c05b0f"
EXPECTED_PLANNER_BLOB = "6cbb09daa3a770e80e37ba761a2f878cdd27e0c4"
EXPECTED_RUNTIME_BLOB = "7085fd9fe9656bdbbeb33e5c1c840cd01ffb32c2"
EXPECTED_BRIDGE_PR = 656
EXPECTED_ISSUE_NUMBER = 24
SERVICE_UNIT = "hermes-lidl-weekly.service"
TIMER_UNIT = "hermes-lidl-weekly.timer"
ALERT_UNIT = "hermes-lidl-weekly-failure@.service"
UNIT_NAMES = (SERVICE_UNIT, TIMER_UNIT, ALERT_UNIT)
REPO_ROOT = SOURCE_REPO
PYTHON_PATH = Path("/usr/bin/python3")
CORPUS_ROOT = Path("/home/andris/hermes-deals-lidl-corpus")
EVIDENCE_ROOT = Path("/home/andris/hermes-deals-lidl-weekly-evidence")
CONTROL_ROOT = Path("/usr/local/libexec/hermes-deals-lidl-gate-d-control")
DISPATCH_DST = Path("/usr/local/sbin/hermes-deals-lidl-gate-d-control")
CONFIG_DST = Path("/etc/hermes-deals-audits.d/lidl-gate-d-control.json")
SUDOERS_DST = Path("/etc/sudoers.d/hermes-deals-lidl-gate-d-control")
SHA40_RE = re.compile(r"[0-9a-f]{40}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
SPAN_RE = re.compile(r"[1-9][0-9]*(?:ms|s|min|h|d|w)")
CALENDAR_RE = re.compile(r"[A-Za-z0-9*:/.,~+_ -]{1,160}")


class RegistrationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RegistrationError(message)


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str, check: bool = True, text: bool = False) -> subprocess.CompletedProcess[Any]:
    command = [
        "/usr/sbin/runuser", "-u", AUDIT_USER, "--",
        "/usr/bin/env", "-i",
        "HOME=/home/andris", "USER=andris", "LOGNAME=andris",
        "PATH=/usr/local/bin:/usr/bin:/bin", "LANG=C.UTF-8", "GIT_OPTIONAL_LOCKS=0",
        "/usr/bin/git", "-C", str(SOURCE_REPO), *args,
    ]
    result = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=45,
        text=text,
    )
    if check:
        require(result.returncode == 0, f"audit Git command failed: {args[0]}")
        require(not result.stderr, f"audit Git command emitted stderr: {args[0]}")
    return result


def git_text(*args: str) -> str:
    return str(git(*args, text=True).stdout).strip()


def git_blob_bytes(commit: str, path: str) -> bytes:
    blob = git_text("rev-parse", f"{commit}:{path}")
    result = git("cat-file", "blob", blob)
    payload = bytes(result.stdout)
    require(payload, f"Git blob is empty: {path}")
    return payload


def validate_source_repo(registration_sha: str) -> dict[str, str]:
    require(SHA40_RE.fullmatch(registration_sha) is not None, "registration SHA is invalid")
    require(SOURCE_REPO.is_dir() and not SOURCE_REPO.is_symlink(), "dedicated Lidl audit repository is missing or unsafe")
    require((SOURCE_REPO / ".git").exists(), "dedicated Lidl audit repository is not a Git checkout")
    require(Path(__file__).resolve() == (SOURCE_REPO / INSTALLER_REL).resolve(), "installer must execute from the dedicated Lidl audit checkout")
    require(git_text("branch", "--show-current") == "main", "dedicated Lidl audit repository is not on main")
    require(git_text("rev-parse", "HEAD") == registration_sha, "dedicated Lidl audit repository HEAD is not the registration SHA")
    require(git("status", "--porcelain=v1", "-z", "--untracked-files=all").stdout == b"", "dedicated Lidl audit repository is not clean")
    git("cat-file", "-e", f"{registration_sha}^{{commit}}")
    git("show-ref", "--verify", "--quiet", "refs/remotes/origin/main")
    ancestry = git("merge-base", "--is-ancestor", registration_sha, "refs/remotes/origin/main", check=False)
    require(ancestry.returncode == 0 and not ancestry.stderr, "registration SHA is not reachable from origin/main")

    expected = {
        DISPATCHER_REL: EXPECTED_DISPATCHER_BLOB,
        PLANNER_REL: EXPECTED_PLANNER_BLOB,
        RUNTIME_REL: EXPECTED_RUNTIME_BLOB,
    }
    for path, oid in expected.items():
        require(git_text("rev-parse", f"{registration_sha}:{path}") == oid, f"reviewed Git blob mismatch: {path}")
    installer_blob = git_text("rev-parse", f"{registration_sha}:{INSTALLER_REL}")
    require(git_text("hash-object", str(Path(__file__).resolve())) == installer_blob, "running installer bytes differ from the registration commit")
    return {**expected, INSTALLER_REL: installer_blob}


def validate_inputs(on_calendar: str, retry_delay: str, retry_window: str, max_attempts: int, timeout_start: str) -> None:
    require("\n" not in on_calendar and "\r" not in on_calendar and CALENDAR_RE.fullmatch(on_calendar) is not None, "OnCalendar is invalid")
    for value, label in ((retry_delay, "retry delay"), (retry_window, "retry window"), (timeout_start, "timeout start")):
        require(SPAN_RE.fullmatch(value) is not None, f"{label} is invalid")
    require(2 <= max_attempts <= 5, "max attempts must be between 2 and 5")


def run(argv: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=120,
        env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
    )
    if check:
        require(result.returncode == 0, f"registration preflight failed: {Path(argv[0]).name}")
    return result


def validate_generated_plan(plan: Mapping[str, Any], *, registration_sha: str, on_calendar: str, retry_delay: str, retry_window: str, max_attempts: int, timeout_start: str, output_dir: Path) -> dict[str, str]:
    require(plan.get("schema_version") == 1, "Gate D plan schema mismatch")
    require(plan.get("planner_version") == "lidl-weekly-gate-d-activation-plan-v1", "Gate D planner version mismatch")
    require(plan.get("repo_sha") == registration_sha and plan.get("target") == "current", "Gate D plan runtime identity mismatch")
    schedule = plan.get("schedule")
    require(isinstance(schedule, Mapping), "Gate D plan schedule missing")
    expected_schedule = {
        "on_calendar": on_calendar,
        "persistent": True,
        "max_attempts_per_retry_window": max_attempts,
        "retry_delay": retry_delay,
        "retry_window": retry_window,
        "timeout_start": timeout_start,
    }
    require(dict(schedule) == expected_schedule, "Gate D plan schedule drift")
    require(plan.get("activation_requires_explicit_owner_authorization") is True, "Gate D owner authorization gate missing")
    require(plan.get("preflight_before_mutation") is True, "Gate D preflight gate missing")
    require(plan.get("rollback_preserves_evidence_root") is True, "Gate D evidence preservation gate missing")
    for key in (
        "systemd_change_authorized",
        "systemd_change_performed",
        "bounded_retry_authorized",
        "production_write_authorized",
        "database_write_authorized",
        "review_write_authorized",
        "publication_authorized",
        "deployment_authorized",
    ):
        require(plan.get(key) is False, f"unsafe generated Gate D plan flag: {key}")

    unit_sha = plan.get("unit_sha256")
    require(isinstance(unit_sha, Mapping) and set(unit_sha) == set(UNIT_NAMES), "Gate D plan unit set mismatch")
    actual: dict[str, str] = {}
    for name in UNIT_NAMES:
        path = output_dir / name
        require(path.is_file() and not path.is_symlink(), f"generated unit missing: {name}")
        digest = sha_file(path)
        require(unit_sha.get(name) == digest, f"generated unit SHA mismatch: {name}")
        actual[name] = digest
    return actual


def generate_plan(registration_sha: str, *, on_calendar: str, retry_delay: str, retry_window: str, max_attempts: int, timeout_start: str, output_dir: Path) -> tuple[dict[str, Any], dict[str, str]]:
    planner = SOURCE_REPO / PLANNER_REL
    result = run([
        str(PYTHON_PATH), str(planner),
        "--output-dir", str(output_dir),
        "--repo-root", str(REPO_ROOT),
        "--repo-sha", registration_sha,
        "--python", str(PYTHON_PATH),
        "--corpus-root", str(CORPUS_ROOT),
        "--evidence-root", str(EVIDENCE_ROOT),
        "--on-calendar", on_calendar,
        "--retry-delay", retry_delay,
        "--retry-window", retry_window,
        "--max-attempts", str(max_attempts),
        "--timeout-start", timeout_start,
        "--target", "current",
    ])
    require(result.stdout.strip().startswith("{"), "Gate D planner did not emit a plan")
    plan_path = output_dir / "activation-plan.json"
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RegistrationError("generated activation plan JSON invalid") from exc
    require(isinstance(plan, dict), "generated activation plan root invalid")
    hashes = validate_generated_plan(
        plan,
        registration_sha=registration_sha,
        on_calendar=on_calendar,
        retry_delay=retry_delay,
        retry_window=retry_window,
        max_attempts=max_attempts,
        timeout_start=timeout_start,
        output_dir=output_dir,
    )
    run(["/usr/bin/systemd-analyze", "calendar", on_calendar])
    run(["/usr/bin/systemd-analyze", "verify", *(str(output_dir / name) for name in UNIT_NAMES)])
    return plan, hashes


def fingerprint_payload(*, registration_sha: str, on_calendar: str, retry_delay: str, retry_window: str, max_attempts: int, timeout_start: str, unit_hashes: Mapping[str, str]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "registration_sha": registration_sha,
        "target": "current",
        "repo_root": str(REPO_ROOT),
        "python_path": str(PYTHON_PATH),
        "corpus_root": str(CORPUS_ROOT),
        "evidence_root": str(EVIDENCE_ROOT),
        "schedule": {
            "on_calendar": on_calendar,
            "retry_delay": retry_delay,
            "retry_window": retry_window,
            "max_attempts": max_attempts,
            "timeout_start": timeout_start,
        },
        "unit_sha256": {name: unit_hashes[name] for name in UNIT_NAMES},
    }


def normalize_root_dir(path: Path, mode: int = 0o755) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=mode)
    require(path.is_dir() and not path.is_symlink(), f"unsafe registration directory: {path}")
    os.chown(path, 0, 0)
    os.chmod(path, mode)
    info = path.stat()
    require(info.st_uid == 0 and info.st_gid == 0 and stat.S_IMODE(info.st_mode) == mode, f"registration directory metadata mismatch: {path}")


def write_exclusive_or_identical(path: Path, payload: bytes, mode: int) -> bool:
    if path.exists() or path.is_symlink():
        require(path.is_file() and not path.is_symlink(), f"existing registration path unsafe: {path}")
        info = path.stat()
        require(info.st_uid == 0 and info.st_gid == 0 and stat.S_IMODE(info.st_mode) == mode, f"existing registration metadata drift: {path}")
        require(path.read_bytes() == payload, f"existing registration content drift: {path}")
        return False
    require(path.parent.is_dir() and not path.parent.is_symlink(), f"registration parent is missing or unsafe: {path.parent}")
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.gate-d-", dir=path.parent)
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
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if fd >= 0:
            os.close(fd)
        temp.unlink(missing_ok=True)
    return True


def sudo_version_at_least_1_9_10() -> str:
    result = run(["/usr/bin/sudo", "-V"])
    line = result.stdout.splitlines()[0] if result.stdout else ""
    match = re.fullmatch(r"Sudo version ([0-9]+)\.([0-9]+)\.([0-9]+)(?:.*)?", line)
    require(match is not None, "unable to parse host Sudo version")
    version = tuple(int(match.group(i)) for i in (1, 2, 3))
    require(version >= (1, 9, 10), "host Sudo is older than 1.9.10")
    return line


def runner_not_in_docker_group() -> None:
    try:
        user = pwd.getpwnam(RUNNER_USER)
    except KeyError as exc:
        raise RegistrationError("github-runner account is unavailable") from exc
    groups = {grp.getgrgid(gid).gr_name for gid in os.getgrouplist(RUNNER_USER, user.pw_gid)}
    require("docker" not in groups, "github-runner must not belong to Docker group")


def build_config(*, registration_sha: str, fingerprint: str, on_calendar: str, retry_delay: str, retry_window: str, max_attempts: int, timeout_start: str, unit_hashes: Mapping[str, str], staged_root: Path) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "control": "lidl-gate-d-control",
        "issue_number": EXPECTED_ISSUE_NUMBER,
        "bridge_pr": EXPECTED_BRIDGE_PR,
        "registration_sha": registration_sha,
        "plan_fingerprint": fingerprint,
        "repo_root": str(REPO_ROOT),
        "python_path": str(PYTHON_PATH),
        "corpus_root": str(CORPUS_ROOT),
        "evidence_root": str(EVIDENCE_ROOT),
        "target": "current",
        "schedule": {
            "on_calendar": on_calendar,
            "retry_delay": retry_delay,
            "retry_window": retry_window,
            "max_attempts": max_attempts,
            "timeout_start": timeout_start,
        },
        "units": {name: {"path": str(staged_root / name), "sha256": unit_hashes[name]} for name in UNIT_NAMES},
        "activation_requires_explicit_owner_authorization": True,
        "root_registration_only": True,
        "production_write_authorized": False,
        "database_write_authorized": False,
        "review_write_authorized": False,
        "publication_authorized": False,
        "deployment_authorized": False,
    }


def install_registration(args: argparse.Namespace) -> dict[str, Any]:
    require(os.geteuid() == 0, "registration must run as root")
    validate_inputs(args.on_calendar, args.retry_delay, args.retry_window, args.max_attempts, args.timeout_start)
    blobs = validate_source_repo(args.registration_sha)
    runner_not_in_docker_group()
    sudo_version = sudo_version_at_least_1_9_10()

    with tempfile.TemporaryDirectory(prefix="lidl-gate-d-registration-") as temp_name:
        generated = Path(temp_name) / "generated"
        generated.mkdir(mode=0o700)
        _plan, unit_hashes = generate_plan(
            args.registration_sha,
            on_calendar=args.on_calendar,
            retry_delay=args.retry_delay,
            retry_window=args.retry_window,
            max_attempts=args.max_attempts,
            timeout_start=args.timeout_start,
            output_dir=generated,
        )
        payload = fingerprint_payload(
            registration_sha=args.registration_sha,
            on_calendar=args.on_calendar,
            retry_delay=args.retry_delay,
            retry_window=args.retry_window,
            max_attempts=args.max_attempts,
            timeout_start=args.timeout_start,
            unit_hashes=unit_hashes,
        )
        fingerprint = sha_bytes(canonical_bytes(payload))
        require(SHA256_RE.fullmatch(fingerprint) is not None, "plan fingerprint generation failed")

        normalize_root_dir(CONTROL_ROOT)
        staged_root = CONTROL_ROOT / args.registration_sha
        normalize_root_dir(staged_root)
        changed = False
        for name in UNIT_NAMES:
            changed |= write_exclusive_or_identical(staged_root / name, (generated / name).read_bytes(), 0o444)

        dispatcher = git_blob_bytes(args.registration_sha, DISPATCHER_REL)
        # The Git object identity was verified before materialization; this SHA-1 check
        # also protects the exact bytes copied into the root-owned dispatcher path.
        require(git_text("rev-parse", f"{args.registration_sha}:{DISPATCHER_REL}") == EXPECTED_DISPATCHER_BLOB, "dispatcher source identity drift")
        changed |= write_exclusive_or_identical(DISPATCH_DST, dispatcher, 0o755)

        config = build_config(
            registration_sha=args.registration_sha,
            fingerprint=fingerprint,
            on_calendar=args.on_calendar,
            retry_delay=args.retry_delay,
            retry_window=args.retry_window,
            max_attempts=args.max_attempts,
            timeout_start=args.timeout_start,
            unit_hashes=unit_hashes,
            staged_root=staged_root,
        )
        config_bytes = json.dumps(config, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        normalize_root_dir(CONFIG_DST.parent)
        changed |= write_exclusive_or_identical(CONFIG_DST, config_bytes, 0o600)

        sudoers = (
            f"Cmnd_Alias HERMES_DEALS_LIDL_GATE_D_CONTROL = {DISPATCH_DST} ^(activate|disable|rollback) {fingerprint}$\n"
            + "github-runner ALL=(root) "
            + "NOPASS"
            + "WD: HERMES_DEALS_LIDL_GATE_D_CONTROL\n"
        ).encode("utf-8")
        sudoers_temp = Path(temp_name) / "sudoers"
        sudoers_temp.write_bytes(sudoers)
        os.chmod(sudoers_temp, 0o440)
        run(["/usr/sbin/visudo", "-cf", str(sudoers_temp)])
        require(SUDOERS_DST.parent.is_dir() and not SUDOERS_DST.parent.is_symlink(), "sudoers directory is missing or unsafe")
        sudoers_dir_info = SUDOERS_DST.parent.stat()
        require(sudoers_dir_info.st_uid == 0 and sudoers_dir_info.st_gid == 0, "sudoers directory owner mismatch")
        changed |= write_exclusive_or_identical(SUDOERS_DST, sudoers, 0o440)
        run(["/usr/sbin/visudo", "-cf", str(SUDOERS_DST)])

    for operation in ("activate", "disable", "rollback"):
        probe = run(["/usr/bin/sudo", "-n", "-l", "-U", RUNNER_USER, "--", str(DISPATCH_DST), operation, fingerprint], check=False)
        require(probe.returncode == 0, f"github-runner sudo policy missing for {operation}")
    wrong_plan = "0" * 64 if fingerprint != "0" * 64 else "1" * 64
    for argv in (
        [str(DISPATCH_DST), "activate", wrong_plan],
        [str(DISPATCH_DST), "unknown", fingerprint],
        [str(DISPATCH_DST), "activate"],
        [str(DISPATCH_DST), "activate", fingerprint, "extra"],
    ):
        probe = run(["/usr/bin/sudo", "-n", "-l", "-U", RUNNER_USER, "--", *argv], check=False)
        require(probe.returncode != 0, "github-runner sudo policy accepts malformed Gate D arguments")

    return {
        "result": "PASS" if changed else "NO_OP_IDENTICAL",
        "registration_sha": args.registration_sha,
        "bridge_pr": EXPECTED_BRIDGE_PR,
        "plan_fingerprint": fingerprint,
        "dispatcher_blob": blobs[DISPATCHER_REL],
        "planner_blob": blobs[PLANNER_REL],
        "runtime_blob": blobs[RUNTIME_REL],
        "sudo_version": sudo_version,
        "root_registration_performed": changed,
        "systemd_change_performed": False,
        "timer_activation_performed": False,
        "production_write_performed": False,
        "database_write_performed": False,
        "review_write_performed": False,
        "publication_performed": False,
        "deployment_performed": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Register the non-activating Lidl Gate D owner-control trust root.")
    parser.add_argument("--registration-sha", required=True)
    parser.add_argument("--on-calendar", required=True)
    parser.add_argument("--retry-delay", required=True)
    parser.add_argument("--retry-window", required=True)
    parser.add_argument("--max-attempts", type=int, required=True)
    parser.add_argument("--timeout-start", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = install_registration(args)
    except (OSError, ValueError, RegistrationError, subprocess.SubprocessError) as exc:
        print(f"ERROR|{type(exc).__name__}|{exc}")
        return 2
    print(json.dumps(result, sort_keys=True))
    print(f"LIDL_GATE_D_REGISTRATION={result['result']}")
    print(f"PLAN_FINGERPRINT={result['plan_fingerprint']}")
    print("SYSTEMD_CHANGE=false")
    print("TIMER_ACTIVATION=false")
    print("PRODUCTION_DATABASE_WRITE=false")
    print("REVIEW_WRITE=false")
    print("PRODUCTION_PUBLISH=false")
    print("PRODUCTION_DEPLOY=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
