#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import pwd
import grp
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any

AUDIT = "aldi-gate-d1-evidence-discovery"
REPO = Path("/home/andris/hermes-deals-audit-source")
AUDIT_USER = "andris"
AUDIT_GROUP = "andris"
AUDIT_HOME = "/home/andris"
LIBEXEC_ROOT = Path("/usr/local/libexec/hermes-deals-audits/aldi-gate-d1-evidence-discovery")
CONFIG_ROOT = Path("/etc/hermes-deals-audits.d")
CONFIG = CONFIG_ROOT / "aldi-gate-d1-evidence-discovery.json"
DISPATCH_SRC = REPO / "tools/runner/aldi_gate_d1_evidence_discovery_dispatch.py"
DISPATCH_DST = Path("/usr/local/sbin/hermes-deals-aldi-gate-d1-evidence-discovery-dispatch")
SUDOERS = Path("/etc/sudoers.d/hermes-deals-aldi-gate-d1-evidence-discovery")
STAGING_ROOT = Path("/home/andris/hermes-deals-runner-evidence")
RUNNER_SERVICE = "actions.runner.rozkalnsandris-hermes-deals.rpi5-hermes-deals-audit.service"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
BUNDLE_FILES = (
    "tools/aldi_gate_d_rpi5_evidence_discovery.py",
    "tools/aldi_weekly_gate_d_visual_review_pack.py",
    "tools/aldi_weekly_gate_c_shadow_replay_preflight.py",
    "tools/aldi_weekly_gate_c_shadow_replay_preflight_core.py",
    "config/aldi-weekly-gate-b-replay-plan-31105044968.json",
    "config/aldi-weekly-gate-b-replay-plan-31105044968.part-01a.b64",
    "config/aldi-weekly-gate-b-replay-plan-31105044968.part-01b.b64",
    "config/aldi-weekly-gate-b-replay-plan-31105044968.part-01c.b64",
    "config/aldi-weekly-gate-b-replay-plan-31105044968.part-02.b64",
    "config/aldi-weekly-gate-b-replay-plan-31105044968.part-03.b64",
    "config/aldi-weekly-gate-b-replay-plan-31105044968.part-04.b64",
    "config/aldi-weekly-gate-b-replay-plan-31105044968.part-05.b64",
    "config/aldi-weekly-gate-b-replay-plan-31105044968.part-06.b64",
)
FORBIDDEN_GIT_MUTATIONS = {
    "checkout",
    "switch",
    "reset",
    "stash",
    "clean",
    "pull",
    "fetch",
    "merge",
    "rebase",
}


class InstallError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise InstallError(message)


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


def audit_git(*args: str) -> bytes:
    require(not ({arg for arg in args} & FORBIDDEN_GIT_MUTATIONS), "mutating Git command forbidden")
    completed = subprocess.run(
        [
            "/usr/sbin/runuser",
            "-u",
            AUDIT_USER,
            "--",
            "/usr/bin/env",
            "-i",
            f"HOME={AUDIT_HOME}",
            f"USER={AUDIT_USER}",
            f"LOGNAME={AUDIT_USER}",
            "PATH=/usr/local/bin:/usr/bin:/bin",
            "LANG=C.UTF-8",
            "GIT_OPTIONAL_LOCKS=0",
            "/usr/bin/git",
            "-C",
            str(REPO),
            *args,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    require(completed.returncode == 0, f"audit Git command failed: {' '.join(args)}")
    require(not completed.stderr, f"audit Git command emitted stderr: {' '.join(args)}")
    return completed.stdout


def snapshot_index() -> dict[str, Any]:
    index = REPO / ".git/index"
    require(regular_file(index), "audit repo index missing or unsafe")
    info = index.stat()
    expected_uid = pwd.getpwnam(AUDIT_USER).pw_uid
    expected_gid = grp.getgrnam(AUDIT_GROUP).gr_gid
    require(info.st_uid == expected_uid and info.st_gid == expected_gid, "audit repo index owner must be andris:andris")
    return {
        "mode": stat.S_IMODE(info.st_mode),
        "bytes": info.st_size,
        "sha256": sha_file(index),
        "uid": info.st_uid,
        "gid": info.st_gid,
    }


def verify_repo(commit_sha: str) -> dict[str, Any]:
    require(regular_dir(REPO / ".git"), "audit repo git directory missing or unsafe")
    require(not (REPO / ".git/index.lock").exists(), "audit repo index is locked")
    before = snapshot_index()
    branch = audit_git("branch", "--show-current").decode("utf-8").strip()
    head = audit_git("rev-parse", "HEAD").decode("ascii").strip()
    status = audit_git("status", "--porcelain=v1", "-z", "--untracked-files=all")
    require(branch == "main", "audit repo must be on main")
    require(head == commit_sha, "audit repo HEAD does not match registered commit")
    require(status == b"", "audit repo is dirty")
    after = snapshot_index()
    require(after == before, "audit repo index changed during verification")
    return before


def build_bundle(commit_sha: str) -> tuple[Path, str]:
    destination = LIBEXEC_ROOT / commit_sha
    rows = []
    for relative in BUNDLE_FILES:
        source = REPO / relative
        require(regular_file(source), f"required bundle file missing or unsafe: {relative}")
        rows.append(
            {
                "path": relative,
                "bytes": source.stat().st_size,
                "sha256": sha_file(source),
            }
        )
    manifest = {
        "schema_version": 1,
        "audit": AUDIT,
        "commit_sha": commit_sha,
        "files": rows,
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()

    if destination.exists():
        require(regular_dir(destination), "existing bundle destination is unsafe")
        manifest_path = destination / "bundle-manifest.json"
        require(regular_file(manifest_path), "existing bundle manifest missing or unsafe")
        require(manifest_path.read_bytes() == manifest_bytes, "existing bundle manifest differs")
        for row in rows:
            target = destination / row["path"]
            require(regular_file(target), f"existing bundle file missing: {row['path']}")
            require(target.stat().st_size == row["bytes"], f"existing bundle byte drift: {row['path']}")
            require(sha_file(target) == row["sha256"], f"existing bundle SHA drift: {row['path']}")
        return destination, manifest_sha

    LIBEXEC_ROOT.mkdir(parents=True, exist_ok=True, mode=0o755)
    with tempfile.TemporaryDirectory(prefix=f".{commit_sha}.", dir=str(LIBEXEC_ROOT)) as tmp_raw:
        tmp = Path(tmp_raw)
        os.chmod(tmp, 0o755)
        for row in rows:
            source = REPO / row["path"]
            target = tmp / row["path"]
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
            shutil.copyfile(source, target, follow_symlinks=False)
            os.chmod(target, 0o644)
        manifest_path = tmp / "bundle-manifest.json"
        manifest_path.write_bytes(manifest_bytes)
        os.chmod(manifest_path, 0o644)
        os.rename(tmp, destination)
    return destination, manifest_sha


def atomic_write(path: Path, data: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temp = Path(raw)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def install(commit_sha: str) -> None:
    require(os.geteuid() == 0, "installer must run as root")
    require(SHA_RE.fullmatch(commit_sha) is not None, "expected one 40-character lowercase merge SHA")
    require(Path("/usr/sbin/runuser").is_file(), "runuser missing")
    require(Path("/usr/sbin/visudo").is_file(), "visudo missing")
    index_before = verify_repo(commit_sha)
    bundle, manifest_sha = build_bundle(commit_sha)

    require(regular_file(DISPATCH_SRC), "dispatcher source missing or unsafe")
    dispatcher_bytes = DISPATCH_SRC.read_bytes()
    dispatcher_sha = hashlib.sha256(dispatcher_bytes).hexdigest()
    atomic_write(DISPATCH_DST, dispatcher_bytes, 0o755)

    STAGING_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    shutil.chown(STAGING_ROOT, user=AUDIT_USER, group=AUDIT_GROUP)
    os.chmod(STAGING_ROOT, 0o700)

    config = {
        "schema_version": 1,
        "audit": AUDIT,
        "commit_sha": commit_sha,
        "bundle_dir": str(bundle),
        "bundle_manifest_sha256": manifest_sha,
        "dispatcher_sha256": dispatcher_sha,
        "state_root": "/home/andris/.local/state/hermes-deals/aldi-perfect-shadow",
        "production_apply_authorized": False,
        "review_pack_execution_authorized": False,
    }
    atomic_write(CONFIG, (json.dumps(config, indent=2, sort_keys=True) + "\n").encode("utf-8"), 0o600)

    sudoers = (
        "github-runner ALL=(root) NOPASSWD: "
        "/usr/local/sbin/hermes-deals-aldi-gate-d1-evidence-discovery-dispatch *\n"
    ).encode("utf-8")
    with tempfile.NamedTemporaryFile(prefix="aldi-gate-d1-sudoers-", delete=False) as handle:
        handle.write(sudoers)
        sudoers_temp = Path(handle.name)
    try:
        os.chmod(sudoers_temp, 0o440)
        checked = subprocess.run(
            ["/usr/sbin/visudo", "-cf", str(sudoers_temp)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
        )
        require(checked.returncode == 0, "sudoers validation failed")
        atomic_write(SUDOERS, sudoers, 0o440)
    finally:
        sudoers_temp.unlink(missing_ok=True)

    service = subprocess.run(
        ["/usr/bin/systemctl", "is-active", "--quiet", RUNNER_SERVICE],
        check=False,
        timeout=30,
    )
    require(service.returncode == 0, "audit runner service is not active")
    groups = subprocess.run(
        ["/usr/bin/id", "-nG", "github-runner"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    require(groups.returncode == 0, "cannot read github-runner groups")
    require("docker" not in groups.stdout.decode("utf-8").split(), "github-runner must not belong to docker group")

    index_after = snapshot_index()
    require(index_after == index_before, "audit repo index changed during installation")
    print("INSTALL_RESULT=PASS")
    print(f"AUDIT={AUDIT}")
    print(f"REGISTERED_COMMIT={commit_sha}")
    print(f"BUNDLE_MANIFEST_SHA256={manifest_sha}")
    print("INSTALLER_INDEX_OWNERSHIP_PRESERVED=true")
    print("RUNNER_HAS_DOCKER_GROUP=false")
    print("PRODUCTION_APPLY_AUTHORIZED=false")
    print("REVIEW_PACK_EXECUTION_AUTHORIZED=false")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: installer <merged-sha>", file=sys.stderr)
        return 2
    try:
        install(args[0])
        return 0
    except Exception as exc:
        print(f"INSTALL_RESULT=BLOCKED\nreason={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
