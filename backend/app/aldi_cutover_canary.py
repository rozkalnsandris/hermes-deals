"""One bounded ALDI raw/DB/API provenance canary for a separately approved cutover.

This is a LIVE write entrypoint. It must only run after the host selection proof,
inside that exact API container as numeric UID:GID 1000:1000.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import resource
import stat
import sys


RAW_ROOT = Path("/data/raw")
CONFIG = Path("/app/config/sources.json")
SOURCE = "aldi_nord"
MAX_RESPONSE = 32 * 1024 * 1024


class Stop(Exception):
    """The canary cannot establish its exact write/provenance contract."""


def require(value: object) -> None:
    if not value:
        raise Stop()


def _check_raw_root(root: Path = RAW_ROOT, *, owner: int = 0,
                    collector_gid: int = 1000) -> None:
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        details = os.fstat(fd)
        require(stat.S_ISDIR(details.st_mode) and details.st_uid == owner
                and details.st_gid == collector_gid)
        require(stat.S_IMODE(details.st_mode) == 0o3775)
        require(not {"system.posix_acl_access", "system.posix_acl_default"}
                & set(os.listxattr(fd)))
    finally:
        os.close(fd)


def run_canary() -> None:
    from app.aldi_cutover_verify import verify
    from app.db import SessionLocal
    from app.probe import probe_source
    from app.settings import get_settings
    from app.source_config import load_sources

    require(os.geteuid() == 1000 and os.getegid() == 1000)
    settings = get_settings()
    require(settings.raw_snapshot_dir == RAW_ROOT and settings.sources_config == CONFIG)
    _check_raw_root()
    sources = [source for source in load_sources(CONFIG)
               if source.enabled and source.chain == SOURCE]
    require(len(sources) == 1)

    after = datetime.now(timezone.utc)
    with SessionLocal() as db:
        snapshot = probe_source(db, sources[0], max_content_bytes=MAX_RESPONSE)
        require(snapshot.success is True and snapshot.snapshot_path)
        verify(db, snapshot.id, after, now=datetime.now(timezone.utc))


def main(argv: list[str] | None = None) -> int:
    # Capture only a descriptor for the fixed receipt. Everything from network,
    # database and verifier libraries remains suppressed, including tracebacks.
    original_stdout = os.dup(1)
    null = os.open(os.devnull, os.O_WRONLY | os.O_CLOEXEC)
    os.dup2(null, 1)
    os.dup2(null, 2)
    os.close(null)
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        require((sys.argv[1:] if argv is None else argv) == [])
        run_canary()
    except BaseException:
        receipt = b"ALDI_CUTOVER_CANARY=STOP\nMUTATION_OUTCOME=UNKNOWN\n"
        status = 2
    else:
        receipt = (b"ALDI_CUTOVER_CANARY=PASS\nRAW_SNAPSHOT_WRITTEN=true\n"
                   b"SOURCE_SNAPSHOT_ROW_WRITTEN=true\nOFFER_CANDIDATES_WRITTEN=false\n")
        status = 0
    os.write(original_stdout, receipt)
    os.close(original_stdout)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
