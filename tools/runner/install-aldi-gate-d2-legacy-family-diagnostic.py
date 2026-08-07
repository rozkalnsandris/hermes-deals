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

REPO = Path("/home/andris/hermes-deals-audit-source")
AUDIT_USER = "andris"
AUDIT_HOME = "/home/andris"
RUNNER_USER = "github-runner"
AUDIT = "aldi-gate-d2-legacy-family-diagnostic"
V1_COMMIT = "690a0a09364b59e323230d24af006542bbdb1012"
V1_BUNDLE = Path("/usr/local/libexec/hermes-deals-audits/aldi-gate-d1-evidence-discovery") / V1_COMMIT
V1_MANIFEST_SHA256 = "481bd9ea014afb928f9f2b4b5d5f84c6f571c72c2524d7b442b16124ca73169f"
FROZEN_GATE_D_RELATIVE = "tools/aldi_weekly_gate_d_visual_review_pack.py"
INSTALL_ROOT = Path("/usr/local/libexec/hermes-deals-audits/aldi-gate-d2-legacy-family-diagnostic")
DIAGNOSTIC_SOURCE = REPO / "tools/aldi_gate_d2_legacy_family_diagnostic.py"
DISPATCH_SOURCE = REPO / "tools/runner/aldi_gate_d2_legacy_family_diagnostic_dispatch.py"
DISPATCH_DST = Path("/usr/local/sbin/hermes-deals-aldi-gate-d2-legacy-family-diagnostic")
CONFIG_DST = Path("/etc/hermes-deals-audits.d/aldi-gate-d2-legacy-family-diagnostic.json")
SUDOERS_DST = Path("/etc/sudoers.d/hermes-deals-aldi-gate-d2-legacy-family-diagnostic")
RUNNER_SERVICE = "actions.runner.rozkalnsandris-hermes-deals.rpi5-hermes-deals-audit.service"


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


def index_snapshot() -> tuple[str, int, int, str]:
    index = REPO / ".git/index"
    require(index.is_file() and not index.is_symlink(), "audit repo index missing or unsafe")
    require(not (REPO / ".git/index.lock").exists(), "audit repo index locked")
    info = index.stat()
    owner = f"{pwd.getpwuid(info.st_uid).pw_name}:{grp.getgrgid(info.st_gid).gr_name}"
    require(owner == "andris:andris", "audit repo index owner mismatch")
    return owner, stat.S_IMODE(info.st_mode), info.st_size, sha_file(index)


def audit_git(*args: str) -> bytes:
    command = [
        "/usr/sbin/runuser", "-u", AUDIT_USER, "--",
        "/usr/bin/env", "-i",
        f"HOME={AUDIT_HOME}", f"USER={AUDIT_USER}", f"LOGNAME={AUDIT_USER}",
        "PATH=/usr/local/bin:/usr/bin:/bin", "LANG=C.UTF-8", "GIT_OPTIONAL_LOCKS=0",
        "/usr/bin/git", "-C", str(REPO), *args,
    ]
    completed = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    require(completed.returncode == 0, f"audit git failed: {args[0]}")
    require(not completed.stderr, f"audit git emitted stderr: {args[0]}")
    return completed.stdout


def validate_repo(commit_sha: str) -> tuple[str, int, int, str]:
    before = index_snapshot()
    require(audit_git("branch", "--show-current").decode().strip() == "main", "audit repo branch mismatch")
    require(audit_git("rev-parse", "HEAD").decode().strip() == commit_sha, "audit repo SHA mismatch")
    require(audit_git("status", "--porcelain=v1", "-z", "--untracked-files=all") == b"", "audit repo dirty")
    require(index_snapshot() == before, "audit repo index changed during verification")
    return before


def validate_frozen_gate_d() -> tuple[Path, str]:
    manifest_path = V1_BUNDLE / "bundle-manifest.json"
    require(V1_BUNDLE.is_dir() and not V1_BUNDLE.is_symlink(), "registered V1 bundle missing")
    require(manifest_path.is_file() and not manifest_path.is_symlink(), "registered V1 manifest missing")
    require(sha_file(manifest_path) == V1_MANIFEST_SHA256, "registered V1 manifest drift")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = payload.get("files")
    require(isinstance(rows, list), "V1 manifest files missing")
    match = [row for row in rows if isinstance(row, dict) and row.get("path") == FROZEN_GATE_D_RELATIVE]
    require(len(match) == 1, "frozen Gate D manifest row missing")
    row = match[0]
    tool = V1_BUNDLE / FROZEN_GATE_D_RELATIVE
    require(tool.is_file() and not tool.is_symlink(), "frozen Gate D tool missing")
    require(tool.stat().st_size == row.get("bytes"), "frozen Gate D bytes drift")
    digest = sha_file(tool)
    require(digest == row.get("sha256"), "frozen Gate D SHA drift")
    return tool, digest


def validate_runner() -> None:
    active = subprocess.run(["/usr/bin/systemctl", "is-active", "--quiet", RUNNER_SERVICE], check=False)
    require(active.returncode == 0, "audit runner inactive")
    groups = {entry.gr_name for entry in grp.getgrall() if RUNNER_USER in entry.gr_mem}
    groups.add(grp.getgrgid(pwd.getpwnam(RUNNER_USER).pw_gid).gr_name)
    require("docker" not in groups, "github-runner is in docker group")


def install_diagnostic(commit_sha: str) -> tuple[Path, str]:
    target = INSTALL_ROOT / commit_sha
    require(not target.exists(), "diagnostic target already exists")
    target.mkdir(parents=True, mode=0o755)
    try:
        destination = target / "aldi_gate_d2_legacy_family_diagnostic.py"
        shutil.copyfile(DIAGNOSTIC_SOURCE, destination, follow_symlinks=False)
        os.chmod(destination, 0o444)
        return destination, sha_file(destination)
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise


def install_dispatcher(
    commit_sha: str,
    diagnostic: Path,
    diagnostic_sha: str,
    frozen_gate_d: Path,
    frozen_gate_d_sha: str,
) -> None:
    DISPATCH_DST.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_DST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DISPATCH_SOURCE, DISPATCH_DST, follow_symlinks=False)
    os.chmod(DISPATCH_DST, 0o755)
    config = {
        "schema_version": 1,
        "audit": AUDIT,
        "commit_sha": commit_sha,
        "diagnostic_file": str(diagnostic),
        "diagnostic_sha256": diagnostic_sha,
        "dispatcher_sha256": sha_file(DISPATCH_DST),
        "frozen_gate_d_tool": str(frozen_gate_d),
        "frozen_gate_d_sha256": frozen_gate_d_sha,
        "v1_commit": V1_COMMIT,
        "v1_bundle_manifest_sha256": V1_MANIFEST_SHA256,
        "raw_evidence_export_authorized": False,
        "raw_exception_export_authorized": False,
        "review_pack_execution_authorized": False,
        "production_apply_authorized": False,
    }
    CONFIG_DST.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(CONFIG_DST, 0o600)

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir="/etc/sudoers.d") as handle:
        handle.write(f"{RUNNER_USER} ALL=(root) NOPASSWD: {DISPATCH_DST} *\n")
        temp = Path(handle.name)
    try:
        os.chmod(temp, 0o440)
        check = subprocess.run(["/usr/sbin/visudo", "-cf", str(temp)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        require(check.returncode == 0, "sudoers validation failed")
        os.replace(temp, SUDOERS_DST)
        os.chmod(SUDOERS_DST, 0o440)
    finally:
        if temp.exists():
            temp.unlink()


def main() -> int:
    if os.geteuid() != 0:
        print("run as root", file=sys.stderr)
        return 1
    if len(sys.argv) != 2 or len(sys.argv[1]) != 40 or any(ch not in "0123456789abcdef" for ch in sys.argv[1]):
        print("usage: gate-d2-installer <merged-sha>", file=sys.stderr)
        return 2
    commit_sha = sys.argv[1]
    try:
        before = validate_repo(commit_sha)
        frozen_gate_d, frozen_gate_d_sha = validate_frozen_gate_d()
        validate_runner()
        diagnostic, diagnostic_sha = install_diagnostic(commit_sha)
        install_dispatcher(commit_sha, diagnostic, diagnostic_sha, frozen_gate_d, frozen_gate_d_sha)
        require(index_snapshot() == before, "audit repo index changed during installation")
        print("INSTALL_RESULT=PASS")
        print(f"AUDIT={AUDIT}")
        print(f"REGISTERED_COMMIT={commit_sha}")
        print(f"V1_REGISTERED_COMMIT={V1_COMMIT}")
        print(f"V1_BUNDLE_MANIFEST_SHA256={V1_MANIFEST_SHA256}")
        print(f"FROZEN_GATE_D_SHA256={frozen_gate_d_sha}")
        print(f"DIAGNOSTIC_SHA256={diagnostic_sha}")
        print("INSTALLER_INDEX_OWNERSHIP_PRESERVED=true")
        print("RUNNER_HAS_DOCKER_GROUP=false")
        print("RAW_EVIDENCE_EXPORT_AUTHORIZED=false")
        print("RAW_EXCEPTION_EXPORT_AUTHORIZED=false")
        print("PRODUCTION_APPLY_AUTHORIZED=false")
        print("REVIEW_PACK_EXECUTION_AUTHORIZED=false")
        return 0
    except Exception as exc:
        print(f"INSTALL_RESULT=BLOCKED error_type={type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
