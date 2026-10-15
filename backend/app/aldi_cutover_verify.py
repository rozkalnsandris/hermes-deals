"""Read-only, sanitized verification of one new ALDI collector snapshot.

This is a post-collector cutover check, not a collector or deployment entrypoint.
The live caller must separately prove the API container image and host bind.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import resource
import stat
from uuid import UUID

RAW_ROOT = Path("/data/raw")
SOURCE = "aldi_nord"
MAX_FILE = 32 * 1024 * 1024
MAX_API_RESPONSE = 64 * 1024
MAX_AGE = timedelta(minutes=15)
NOFOLLOW_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
NOFOLLOW_FILE = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


class Stop(Exception):
    """Fail closed without exposing paths, source data or database details."""


def require(value: object) -> None:
    if not value:
        raise Stop()


def _no_acl(fd: int) -> None:
    require(not {"system.posix_acl_access", "system.posix_acl_default"} & set(os.listxattr(fd)))


def _file_digest(path: str, root: Path, *, root_owner: int = 0,
                 collector_uid: int = 1000, collector_gid: int = 1000) -> tuple[str, int]:
    candidate = Path(path)
    require(candidate.is_absolute() and root.is_absolute())
    require(".." not in candidate.parts and ".." not in root.parts)
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise Stop() from exc
    require(len(relative.parts) == 2 and relative.parts[0] == SOURCE)
    require(all(part and not part.startswith(".") for part in relative.parts))

    descriptors: list[int] = []
    try:
        fd = os.open("/", NOFOLLOW_DIR)
        descriptors.append(fd)
        for name in root.parts[1:]:
            fd = os.open(name, NOFOLLOW_DIR, dir_fd=fd)
            descriptors.append(fd)
        root_fd = fd
        base = os.fstat(fd)
        require(stat.S_ISDIR(base.st_mode) and base.st_uid == root_owner
                and base.st_gid == collector_gid)
        require(stat.S_IMODE(base.st_mode) == 0o3775)
        _no_acl(fd)
        for name in relative.parts[:-1]:
            fd = os.open(name, NOFOLLOW_DIR, dir_fd=fd)
            descriptors.append(fd)
            folder = os.fstat(fd)
            require(stat.S_ISDIR(folder.st_mode) and folder.st_dev == base.st_dev)
            require(folder.st_uid in (root_owner, collector_uid)
                    and folder.st_gid == collector_gid)
            require(not folder.st_mode & 0o002)
            require(not folder.st_mode & 0o020 or folder.st_mode & stat.S_ISVTX)
            _no_acl(fd)

        name = relative.parts[-1]
        before = os.stat(name, dir_fd=fd, follow_symlinks=False)
        child = os.open(name, NOFOLLOW_FILE, dir_fd=fd)
        descriptors.append(child)
        opened = os.fstat(child)
        require(stat.S_ISREG(opened.st_mode) and opened.st_nlink == 1)
        require(opened.st_dev == base.st_dev and opened.st_uid == collector_uid
                and opened.st_gid == collector_gid)
        require(not opened.st_mode & 0o022 and 0 < opened.st_size <= MAX_FILE)
        _no_acl(child)
        identity = lambda value: (value.st_dev, value.st_ino, value.st_size,
                                  value.st_mtime_ns, value.st_ctime_ns)
        folder_identity = identity(os.fstat(fd))
        require(identity(before) == identity(opened))
        digest = hashlib.sha256()
        size = 0
        while True:
            chunk = os.read(child, min(65536, MAX_FILE + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            require(size <= MAX_FILE)
            digest.update(chunk)
        require(size == opened.st_size)
        require(identity(os.fstat(child)) == identity(opened))
        require(identity(os.stat(name, dir_fd=fd, follow_symlinks=False)) == identity(opened))
        require(identity(os.fstat(fd)) == folder_identity)
        require(identity(os.stat(relative.parts[0], dir_fd=root_fd,
                                 follow_symlinks=False)) == folder_identity)
        require(identity(os.stat(root, follow_symlinks=False)) == identity(base))
        return digest.hexdigest(), size
    except (OSError, ValueError) as exc:
        raise Stop() from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _api_latest() -> list[dict[str, object]]:
    connection = http.client.HTTPConnection("127.0.0.1", 8000, timeout=3)
    try:
        connection.request("GET", "/api/v1/sources/latest")
        response = connection.getresponse()
        require(response.status == 200)
        require(response.getheader("Content-Type", "").split(";", 1)[0].strip() == "application/json")
        length = response.getheader("Content-Length")
        require(length is None or 0 <= int(length) <= MAX_API_RESPONSE)
        raw = response.read(MAX_API_RESPONSE + 1)
        require(len(raw) <= MAX_API_RESPONSE)
        rows = json.loads(raw)
        require(isinstance(rows, list) and len(rows) <= 4)
        require(all(isinstance(row, dict) for row in rows))
        return rows
    except (OSError, ValueError, TypeError, http.client.HTTPException) as exc:
        raise Stop() from exc
    finally:
        connection.close()


def verify(db, snapshot_id: UUID, after: datetime, *, root: Path = RAW_ROOT,
           now: datetime | None = None, api_latest=_api_latest,
           root_owner: int = 0, collector_uid: int = 1000,
           collector_gid: int = 1000, snapshot_model=None) -> None:
    now = now or datetime.now(timezone.utc)
    require(after.tzinfo is not None and after.utcoffset() == timedelta(0))
    require(now - MAX_AGE <= after <= now)
    if snapshot_model is None:
        from app.models import SourceSnapshot

        snapshot_model = SourceSnapshot
    row = db.get(snapshot_model, snapshot_id)
    require(row is not None and row.source_chain == SOURCE and row.success is True)
    require(row.collected_at is not None and row.collected_at.tzinfo is not None)
    require(after <= row.collected_at <= now + timedelta(seconds=60))
    require(row.snapshot_path and row.sha256 and re.fullmatch(r"[0-9a-f]{64}", row.sha256))
    digest, size = _file_digest(row.snapshot_path, root, root_owner=root_owner,
                                collector_uid=collector_uid, collector_gid=collector_gid)
    require(digest == row.sha256 and size == row.content_bytes)
    matches = [entry for entry in api_latest() if entry.get("source_chain") == SOURCE]
    require(len(matches) == 1)
    api = matches[0]
    require(api.get("id") == str(snapshot_id) and api.get("sha256") == digest)
    require(api.get("content_bytes") == size and api.get("success") is True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a recent ALDI cutover snapshot without writes")
    parser.add_argument("--snapshot-id", type=UUID, required=True)
    parser.add_argument("--after-utc", required=True,
                        help="UTC timestamp recorded before the collector invocation")
    args = parser.parse_args(argv)
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        after = datetime.fromisoformat(args.after_utc.replace("Z", "+00:00"))
        require(after.tzinfo is not None)
        from app.db import SessionLocal
        from app.settings import get_settings

        require(get_settings().raw_snapshot_dir == RAW_ROOT)
        with SessionLocal() as db:
            verify(db, args.snapshot_id, after)
    except Exception:
        print("COLLECTOR_CUTOVER_VERIFY=STOP")
        return 2
    print("COLLECTOR_CUTOVER_VERIFY=PASS")
    print("RAW_WRITES=false")
    print("DATABASE_WRITES=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
