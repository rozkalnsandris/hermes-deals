#!/usr/bin/env python3
"""Read-only exact-source proof of four installed Hermes collector/monitor units.

Source-only tooling for #992. Installed-unit inspection is a separate owner
READ-ONLY gate; this script never starts, reloads, enables or writes anything.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess

REPO = Path("/home/andris/hermes-deals")
SYSTEMD = Path("/etc/systemd/system")
ORIGINS = frozenset({
    "https://github.com/rozkalnsandris/hermes-deals",
    "https://github.com/rozkalnsandris/hermes-deals.git",
    "git@github.com:rozkalnsandris/hermes-deals.git",
})
UNITS = (
    "hermes-deals-netto-collector.service",
    "hermes-deals-aldi-collector.service",
    "hermes-deals-edeka-collector.service",
    "hermes-deals-edeka-monitor.service",
)
SOURCE_PREFIX = "infra/systemd/"
NETTO_DROPIN_SOURCE = "infra/systemd/netto-collector-dropins/10-skip-sunday.conf"
NETTO_DROPIN_PATH = (
    SYSTEMD / "hermes-deals-netto-collector.service.d" / "10-skip-sunday.conf"
)
NETTO_DROPIN_SIZE = 379
NETTO_DROPIN_SHA256 = (
    "7470b0b5dcd97db62eb6b521e7376b5044e4f5ce234d436118d66f1536066c72"
)
MAX_BYTES = 64 * 1024
HEX_SHA = re.compile(r"[0-9a-f]{40}\Z")


class Stop(Exception):
    """Expected fail-closed state: never relay host/source exceptions."""


def require(value: object) -> None:
    if not value:
        raise Stop()


def _command(*args: str) -> bytes:
    # No user-controlled shell or Git configuration and no Git index locks.
    environment = {
        "PATH": "/usr/bin:/bin", "HOME": "/home/andris", "LC_ALL": "C",
        "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
        "SYSTEMD_PAGER": "cat",
    }
    try:
        completed = subprocess.run(
            args, capture_output=True, check=True, timeout=12,
            env=environment, cwd=str(REPO),
        )
        require(len(completed.stdout) <= MAX_BYTES)
        return completed.stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise Stop() from exc


def _git(run, *args: str) -> bytes:
    return run("git", "-C", str(REPO), *args)


def _properties(unit: str, run) -> dict[str, str]:
    raw = run(
        "systemctl", "show", "--no-pager",
        "--property=LoadState", "--property=FragmentPath",
        "--property=DropInPaths", "--property=NeedDaemonReload", unit,
    )
    try:
        lines = raw.decode("utf-8").splitlines()
        require(len(lines) == 4)
        values = {}
        for line in lines:
            require("=" in line)
            name, value = line.split("=", 1)
            require(name not in values)
            values[name] = value
        require(set(values) == {
            "LoadState", "FragmentPath", "DropInPaths", "NeedDaemonReload",
        })
    except (UnicodeError, ValueError) as exc:
        raise Stop() from exc
    return values


def _check_metadata(info: os.stat_result) -> None:
    require(stat.S_ISREG(info.st_mode))
    require(info.st_uid == 0 and info.st_gid == 0)
    require(stat.S_IMODE(info.st_mode) == 0o644 and info.st_nlink == 1)
    require(0 < info.st_size <= MAX_BYTES)


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev, info.st_ino, info.st_uid, info.st_gid,
        info.st_mode, info.st_nlink, info.st_size,
        info.st_mtime_ns, info.st_ctime_ns,
    )


def _installed_equal_to_git_blob(path: Path, blob: bytes) -> None:
    require(0 < len(blob) <= MAX_BYTES)
    require(
        (path.parent == SYSTEMD and path.name in UNITS)
        or path == NETTO_DROPIN_PATH
    )
    # Pin the directory identity as well as the leaf. In particular, the
    # one allowed drop-in directory must not itself be a symlink or writable
    # by the collector; a matching leaf checksum alone is not sufficient.
    parent_before = os.stat(path.parent, follow_symlinks=False)
    require(stat.S_ISDIR(parent_before.st_mode))
    require(parent_before.st_uid == parent_before.st_gid == 0)
    require(not parent_before.st_mode & 0o022)
    parent_fd = os.open(
        path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        require(_identity(os.fstat(parent_fd)) == _identity(parent_before))
        require(not {
            "system.posix_acl_access", "system.posix_acl_default",
        }.intersection(os.listxattr(parent_fd)))
        before = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        _check_metadata(before)
        fd = os.open(
            path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
            dir_fd=parent_fd,
        )
        try:
            opened = os.fstat(fd)
            require(_identity(before) == _identity(opened))
            require(not {
                "system.posix_acl_access", "system.posix_acl_default",
            }.intersection(os.listxattr(fd)))
            contents = os.read(fd, MAX_BYTES + 1)
            require(len(contents) == opened.st_size)
            require(
                hashlib.sha256(contents).digest() == hashlib.sha256(blob).digest()
            )
            require(_identity(os.fstat(fd)) == _identity(opened))
            require(_identity(
                os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            ) == _identity(before))
        finally:
            os.close(fd)
        require(_identity(os.fstat(parent_fd)) == _identity(parent_before))
        require(
            _identity(os.stat(path.parent, follow_symlinks=False))
            == _identity(parent_before)
        )
    finally:
        os.close(parent_fd)


def verify(
    sha: str, *, run=_command, scan=_installed_equal_to_git_blob,
) -> None:
    require(bool(HEX_SHA.fullmatch(sha)))
    require(REPO.is_dir() and (REPO / ".git").is_dir())
    require(not (REPO / ".git").is_symlink())
    require(_git(run, "branch", "--show-current").strip() == b"main")
    require(_git(run, "rev-parse", "HEAD").strip() == sha.encode())
    require(_git(run, "status", "--porcelain") == b"")
    require(
        _git(run, "remote", "get-url", "origin").decode("utf-8").strip()
        in ORIGINS
    )
    for unit in UNITS:
        path = SYSTEMD / unit
        netto = unit == UNITS[0]
        expected = {
            "LoadState": "loaded",
            "FragmentPath": str(path),
            "DropInPaths": str(NETTO_DROPIN_PATH) if netto else "",
            "NeedDaemonReload": "no",
        }
        require(_properties(unit, run) == expected)
        tracked_path = SOURCE_PREFIX + unit
        blob = _git(run, "cat-file", "blob", sha + ":" + tracked_path)
        scan(path, blob)
        if netto:
            # Historical host observation from 2026-10-23 pins this *one*
            # intentional current-only Sunday skip. No other drop-ins pass.
            extra = _git(run, "cat-file", "blob", sha + ":" + NETTO_DROPIN_SOURCE)
            require(len(extra) == NETTO_DROPIN_SIZE)
            require(hashlib.sha256(extra).hexdigest() == NETTO_DROPIN_SHA256)
            scan(NETTO_DROPIN_PATH, extra)
        # Re-read systemd state after both the unit and any reviewed drop-in.
        # A changed registration or pending reload is STOP, not a mutation.
        require(_properties(unit, run) == expected)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only installed Hermes unit/source equality proof"
    )
    parser.add_argument("--expected-source-sha", required=True)
    args = parser.parse_args(argv)
    try:
        require(pwd.getpwuid(os.geteuid()).pw_name == "andris")
        verify(args.expected_source_sha)
    except Exception:
        print("HERMES_INSTALLED_COLLECTOR_UNITS=STOP")
        return 2
    print("HERMES_INSTALLED_COLLECTOR_UNITS=PASS")
    print("INSTALLED_UNITS_MATCH_EXACT_SOURCE=true")
    print("HOST_MUTATIONS=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
