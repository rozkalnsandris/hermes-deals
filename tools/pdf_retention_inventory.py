#!/usr/bin/env python3
"""Read-only local inventory for #1069; never an expiry or deletion plan."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import sys


def _roots(values: list[Path]) -> list[Path]:
    if not values or len(values) > 16:
        raise ValueError("provide 1 to 16 explicit storage roots")
    roots = []
    for value in values:
        path = Path(value)
        if not path.is_absolute() or ".." in path.parts or path == Path("/"):
            raise ValueError("roots must be absolute, bounded directories without '..'")
        # Do not silently resolve a symlink supplied as a root or ancestor.
        for part in [*reversed(path.parents), path]:
            if part.is_symlink():
                raise ValueError("root or ancestor is a symlink")
        if not path.is_dir():
            raise ValueError("root is not an existing directory")
        if any(path == other or path in other.parents or other in path.parents for other in roots):
            raise ValueError("roots must not overlap")
        roots.append(path)
    return sorted(roots)


def _kind(header: bytes, name: str) -> str | None:
    lower = name.lower()
    # A ZIP with an uncompressed PDF member also contains %PDF- near its start.
    # Recognize archive containers before inspecting embedded PDF signatures.
    if (
        header.startswith((b"PK\x03\x04", b"PK\x05\x06", b"\x1f\x8b", b"BZh",
                           b"\xfd7zXZ\x00", b"7z\xbc\xaf\x27\x1c", b"Rar!"))
        or header[257:262] == b"ustar"
    ):
        return "archive_uninspected"
    if b"%PDF-" in header[:1024]:
        return "pdf"
    if lower.endswith(".pdf"):
        return "invalid_pdf_header"
    if lower.endswith((".zip", ".tar", ".tgz", ".tar.gz", ".gz", ".bz2", ".xz", ".7z", ".rar")):
        return "archive_uninspected"
    if (
        header.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a", b"II*\x00", b"MM\x00*"))
        or (header.startswith(b"RIFF") and header[8:12] == b"WEBP")
        or lower.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".tif", ".tiff"))
    ):
        return "image_candidate"
    return None


def inventory(
    roots: list[Path], *, max_files: int = 10000,
    max_file_bytes: int = 256 * 1024 * 1024,
    max_total_bytes: int = 4 * 1024 * 1024 * 1024,
) -> dict:
    """Hash candidates within explicit roots; dates and parent links stay unknown."""
    roots = _roots(roots)
    if min(max_files, max_file_bytes, max_total_bytes) < 1:
        raise ValueError("limits must be positive")
    assets: dict[tuple[str, str], dict] = {}
    findings = []
    visited = read_bytes = scanned_files = 0
    stopped = False

    def finding(root: int, path: str, reason: str) -> None:
        findings.append({"root": root, "path": path, "reason": reason})

    for root_index, root in enumerate(roots):
        if stopped:
            break
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            def walk_error(error: OSError) -> None:
                raise error

            # Relative, descriptor-based traversal keeps child opens within the
            # opened directory even if a directory is renamed during inventory.
            for directory, dirs, files, directory_fd in os.fwalk(
                ".", topdown=True, follow_symlinks=False,
                dir_fd=root_fd, onerror=walk_error,
            ):
                dirs.sort()
                for name in sorted(dirs + files):
                    relative = (Path(directory) / name).as_posix()
                    visited += 1
                    if visited > max_files:
                        finding(root_index, relative, "entry_limit")
                        stopped = True
                        break
                    try:
                        before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                        if stat.S_ISLNK(before.st_mode):
                            if name in dirs:
                                dirs.remove(name)
                            finding(root_index, relative, "symlink_skipped")
                            continue
                        if stat.S_ISDIR(before.st_mode):
                            continue
                        if not stat.S_ISREG(before.st_mode):
                            finding(root_index, relative, "nonregular_skipped")
                            continue
                        scanned_files += 1
                        if before.st_size > max_file_bytes:
                            finding(root_index, relative, "file_size_limit")
                            continue
                        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                        with os.fdopen(os.open(name, flags, dir_fd=directory_fd), "rb", buffering=0) as handle:
                            opened = os.fstat(handle.fileno())
                            if not stat.S_ISREG(opened.st_mode) or (
                                opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns
                            ) != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns):
                                finding(root_index, relative, "file_changed")
                                continue
                            remaining = max_total_bytes - read_bytes
                            if remaining < min(4096, opened.st_size):
                                finding(root_index, relative, "total_read_limit")
                                stopped = True
                                break
                            header = handle.read(min(4096, opened.st_size))
                            read_bytes += len(header)
                            kind = _kind(header, name)
                            if kind is None:
                                continue
                            if opened.st_size - len(header) > max_total_bytes - read_bytes:
                                finding(root_index, relative, "total_read_limit")
                                stopped = True
                                break
                            digest = hashlib.sha256(header)
                            size = len(header)
                            while size < opened.st_size:
                                chunk = handle.read(min(1024 * 1024, opened.st_size - size))
                                if not chunk:
                                    break
                                digest.update(chunk)
                                size += len(chunk)
                                read_bytes += len(chunk)
                            after = os.fstat(handle.fileno())
                            if size != opened.st_size or (
                                after.st_size, after.st_mtime_ns, after.st_ctime_ns
                            ) != (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns):
                                finding(root_index, relative, "file_changed")
                                continue
                        sha = digest.hexdigest()
                        row = assets.setdefault((kind, sha), {
                            "kind": kind, "sha256": sha, "bytes": size, "copies": [],
                            "first_acquired_at": None, "expires_at": None,
                            "acquisition_status": "unknown",
                        })
                        row["copies"].append({"root": root_index, "path": relative})
                        if kind == "invalid_pdf_header":
                            finding(root_index, relative, "invalid_pdf_header")
                    except OSError as error:
                        finding(root_index, relative, f"read_error:{error.errno}")
                if stopped:
                    break
        except OSError as error:
            finding(root_index, ".", f"walk_error:{error.errno}")
        finally:
            os.close(root_fd)

    rows = [assets[key] for key in sorted(assets)]
    return {
        "schema_version": 1,
        "status": "inventory_partial" if findings else "inventory_complete",
        "roots": [str(root) for root in roots],
        "scanned_files": scanned_files,
        "read_bytes": read_bytes,
        "assets": rows,
        "findings": findings,
        "archive_contents_inspected": False,
        "image_parent_bindings_verified": False,
        "all_storage_locations_verified": False,
        "retention_compliance": "unknown",
        "deletion_authorized": False,
    }


def retention_report(report: dict, db, *, as_of: datetime) -> dict:
    """Annotate observed PDF groups; never infer age, mutate input, or write DB."""
    from app.pdf_retention import pdf_retention

    if not isinstance(as_of, datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("registry evaluation time must include a timezone")
    as_of = as_of.astimezone(timezone.utc)
    result = deepcopy(report)
    result["schema_version"] = 2
    result["registry_checked_at"] = as_of.isoformat()
    # A caller's pending ORM changes must not be flushed by a report query.
    with db.no_autoflush:
        for asset in result["assets"]:
            if asset["kind"] != "pdf":
                continue
            retention = pdf_retention(db, asset["sha256"], as_of=as_of)
            asset["acquisition_status"] = retention.state
            asset["first_acquired_at"] = (
                retention.first_acquired_at.isoformat() if retention.first_acquired_at else None
            )
            asset["expires_at"] = retention.expires_at.isoformat() if retention.expires_at else None
    return result


def expired_pdf_dry_run(report: dict) -> dict:
    """List observed expired PDF copies without deleting or authorizing anything.

    This consumes only a registry-enriched inventory report. It is deliberately
    stricter than a filesystem age scan: unknown acquisition age, incomplete
    storage coverage, uninspected archives and unbound image derivatives remain
    explicit blockers. A future apply step must be separately implemented and
    explicitly authorized; this function never mutates files or the registry.
    """
    if not isinstance(report, dict) or report.get("schema_version") != 2:
        raise ValueError("expiry dry-run requires registry-enriched schema_version 2")
    if not isinstance(report.get("registry_checked_at"), str) or not report["registry_checked_at"]:
        raise ValueError("expiry dry-run requires registry evaluation time")
    roots = report.get("roots")
    assets = report.get("assets")
    if not isinstance(roots, list) or not all(isinstance(root, str) and root for root in roots):
        raise ValueError("expiry dry-run requires inventory roots")
    if not isinstance(assets, list):
        raise ValueError("expiry dry-run requires inventory assets")

    blockers = []
    if report.get("status") != "inventory_complete":
        blockers.append({"type": "inventory_incomplete"})
    if report.get("all_storage_locations_verified") is not True:
        blockers.append({"type": "storage_locations_unverified"})
    if report.get("archive_contents_inspected") is not True:
        blockers.append({"type": "archive_contents_uninspected"})
    if report.get("image_parent_bindings_verified") is not True:
        blockers.append({"type": "image_parent_bindings_unverified"})

    candidates = []
    candidate_shas: set[str] = set()
    seen_copies: set[tuple[int, str]] = set()
    allowed_states = {
        "within_retention", "raw_expired", "unregistered",
        "acquisition_unknown", "not_yet_acquired",
    }
    for asset in assets:
        if not isinstance(asset, dict) or asset.get("kind") != "pdf":
            continue
        digest = asset.get("sha256")
        state = asset.get("acquisition_status")
        copies = asset.get("copies")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
            or state not in allowed_states
            or not isinstance(copies, list)
        ):
            raise ValueError("expiry dry-run received malformed PDF inventory data")
        if state in {"unregistered", "acquisition_unknown", "not_yet_acquired"}:
            blockers.append({
                "type": "pdf_acquisition_state",
                "pdf_sha256": digest,
                "state": state,
            })
        if state != "raw_expired":
            continue
        expires_at = asset.get("expires_at")
        if not isinstance(expires_at, str) or not expires_at:
            raise ValueError("expired PDF is missing registry expiry")
        for copy in copies:
            if not isinstance(copy, dict):
                raise ValueError("expiry dry-run received malformed PDF copy")
            root = copy.get("root")
            path = copy.get("path")
            if (
                type(root) is not int
                or not 0 <= root < len(roots)
                or not isinstance(path, str)
                or not path
                or path.startswith("/")
                or ".." in Path(path).parts
            ):
                raise ValueError("expiry dry-run received unsafe PDF copy path")
            key = (root, path)
            if key in seen_copies:
                raise ValueError("expiry dry-run received duplicate PDF copy")
            seen_copies.add(key)
            candidate_shas.add(digest)
            candidates.append({
                "root": root,
                "path": path,
                "pdf_sha256": digest,
                "expires_at": expires_at,
            })

    candidates.sort(key=lambda row: (row["root"], row["path"], row["pdf_sha256"]))
    blockers.sort(key=lambda row: (
        row["type"], row.get("pdf_sha256", ""), row.get("state", "")
    ))
    result = deepcopy(report)
    result["expiry_dry_run"] = {
        "mode": "observed_expired_pdf_copies_only",
        "candidate_pdf_sha_count": len(candidate_shas),
        "candidate_copy_count": len(candidates),
        "candidates": candidates,
        "blockers": blockers,
        "ready_for_explicit_apply_gate": bool(candidates) and not blockers,
        "apply_supported": False,
    }
    # A report or dry-run is evidence, never deletion authority.
    result["deletion_authorized"] = False
    return result


def registry_report(report: dict, database_url: str) -> dict:
    """Use the existing backend registry in one owned, read-only PostgreSQL snapshot."""
    # Keep the default inventory standard-library-only and independent of app.db.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import NullPool

    url = make_url(database_url)
    if url.drivername != "postgresql+psycopg":
        raise ValueError("registry inventory requires postgresql+psycopg DATABASE_URL")
    engine = create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 10})
    try:
        with engine.connect().execution_options(
            isolation_level="REPEATABLE READ", postgresql_readonly=True,
        ) as connection:
            with Session(bind=connection, autoflush=False) as db:
                db.execute(text("SET LOCAL statement_timeout = '10s'"))
                # Verify the actual server transaction, not merely a client setting.
                if db.scalar(text("SHOW transaction_read_only")) != "on":
                    raise RuntimeError("registry transaction is not read-only")
                return retention_report(report, db, as_of=datetime.now(timezone.utc))
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="+", type=Path, help="explicit absolute storage directories")
    parser.add_argument("--max-files", type=int, default=10000, help="maximum directory entries")
    parser.add_argument("--max-file-bytes", type=int, default=256 * 1024 * 1024)
    parser.add_argument("--max-total-bytes", type=int, default=4 * 1024 * 1024 * 1024)
    parser.add_argument("--with-registry", action="store_true",
                        help="annotate PDFs using a read-only PostgreSQL DATABASE_URL from the environment")
    parser.add_argument("--plan-expired", action="store_true",
                        help="append a dry-run plan for observed expired PDF copies; never deletes")
    args = parser.parse_args()
    if args.plan_expired and not args.with_registry:
        parser.error("--plan-expired requires --with-registry")
    try:
        report = inventory(args.roots, max_files=args.max_files,
                           max_file_bytes=args.max_file_bytes, max_total_bytes=args.max_total_bytes)
    except (ValueError, OSError) as error:
        parser.exit(2, f"inventory failed: {error}\n")
    if args.with_registry:
        try:
            report = registry_report(report, os.environ.get("DATABASE_URL", ""))
        except Exception:
            # Driver/SQL errors may include credentials, server addresses or SQL.
            # Fail without JSON rather than publishing a partially enriched report.
            parser.exit(2, "registry lookup failed; verify PostgreSQL DATABASE_URL, schema and read access\n")
    if args.plan_expired:
        try:
            report = expired_pdf_dry_run(report)
        except ValueError as error:
            parser.exit(2, f"expiry dry-run failed: {error}\n")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if report["status"] == "inventory_complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
