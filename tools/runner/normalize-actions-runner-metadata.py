#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import pwd
import stat
import sys
from typing import Any


UTF8_BOM = b"\xef\xbb\xbf"


class MetadataError(RuntimeError):
    pass


def _load_bound_metadata(
    raw: bytes,
    *,
    expected_name: str,
    expected_url: str,
) -> dict[str, Any]:
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MetadataError("runner metadata is not valid UTF-8 JSON") from exc
    if not isinstance(data, dict):
        raise MetadataError("runner metadata root must be an object")
    if data.get("agentName") != expected_name:
        raise MetadataError("configured runner name mismatch")
    actual_url = str(data.get("gitHubUrl") or "").rstrip("/")
    if actual_url != expected_url.rstrip("/"):
        raise MetadataError("configured runner repository mismatch")
    return data


def normalize(
    path: Path,
    *,
    expected_name: str,
    expected_url: str,
    expected_uid: int | None = None,
    expected_gid: int | None = None,
) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise MetadataError("runner metadata file is missing") from exc
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise MetadataError("runner metadata path is unsafe")
    if expected_uid is not None and metadata.st_uid != expected_uid:
        raise MetadataError("runner metadata owner mismatch")
    if expected_gid is not None and metadata.st_gid != expected_gid:
        raise MetadataError("runner metadata group mismatch")

    raw = path.read_bytes()
    _load_bound_metadata(
        raw,
        expected_name=expected_name,
        expected_url=expected_url,
    )
    if not raw.startswith(UTF8_BOM):
        return False

    normalized = raw[len(UTF8_BOM) :]
    _load_bound_metadata(
        normalized,
        expected_name=expected_name,
        expected_url=expected_url,
    )

    temporary = path.with_name(f".{path.name}.bomfix.{os.getpid()}.tmp")
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
            0o600,
        )
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(normalized)
            handle.flush()
            os.fsync(handle.fileno())
        os.chown(temporary, metadata.st_uid, metadata.st_gid)
        os.chmod(temporary, stat.S_IMODE(metadata.st_mode))
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return True


def main() -> int:
    if os.geteuid() != 0:
        raise MetadataError("runner metadata repair must run as root")
    if len(sys.argv) != 4:
        print(
            "usage: normalize-actions-runner-metadata.py "
            "<metadata-path> <runner-name> <repository-url>",
            file=sys.stderr,
        )
        return 2
    path = Path(sys.argv[1])
    account = pwd.getpwnam("github-release-runner")
    repaired = normalize(
        path,
        expected_name=sys.argv[2],
        expected_url=sys.argv[3],
        expected_uid=account.pw_uid,
        expected_gid=account.pw_gid,
    )
    if not repaired:
        print("RUNNER_METADATA_BOM_REPAIRED=false")
        return 3
    print("RUNNER_METADATA_BOM_REPAIRED=true")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (MetadataError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
