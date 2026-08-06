#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import errno
import grp
from hashlib import sha256
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import stat
import sys
from typing import Any, Mapping

TOOLS_ROOT = Path(__file__).resolve().parent
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from lidl_gate_b_freeze_plan import (
    PLAN_VERSION,
    LidlGateBFreezePlanError,
    build_freeze_plan,
)


APPLY_VERSION = "lidl-gate-b-freeze-apply-v1"
AUTHORIZATION_VERSION = "lidl-gate-b-freeze-authorization-v1"
AUTHORIZATION_ACTION = "freeze_exact_gate_a_source"
RECEIPT_NAME = "gate-b-freeze-receipt.json"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
STAGING_RE = re.compile(r"^\.gate-b-freeze-[0-9a-f]{16}\.staging$")
AT_FDCWD = -100
RENAME_NOREPLACE = 1


class LidlGateBFreezeApplyError(RuntimeError):
    def __init__(self, message: str, *, committed: bool = False) -> None:
        super().__init__(message)
        self.committed = committed


def _require(condition: bool, message: str, *, committed: bool = False) -> None:
    if not condition:
        raise LidlGateBFreezeApplyError(message, committed=committed)


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _sha256_path(path: Path) -> str:
    _require(path.is_file() and not path.is_symlink(), f"unsafe or missing file: {path}")
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_authorization(
    path: Path,
    *,
    expected_uid: int,
    expected_gid: int,
) -> dict[str, Any]:
    _require(path.is_file() and not path.is_symlink(), f"authorization file is missing or unsafe: {path}")
    metadata = path.stat(follow_symlinks=False)
    _require(stat.S_ISREG(metadata.st_mode), "authorization path is not a regular file")
    _require(metadata.st_uid == expected_uid, "authorization owner UID mismatch")
    _require(metadata.st_gid == expected_gid, "authorization owner GID mismatch")
    _require(stat.S_IMODE(metadata.st_mode) == 0o600, "authorization mode must be 0600")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LidlGateBFreezeApplyError(
            f"authorization file is unreadable: {type(exc).__name__}"
        ) from exc
    _require(isinstance(payload, dict), "authorization root must be an object")
    return payload


def _validate_plan(
    plan: Mapping[str, Any],
    *,
    expected_plan_fingerprint: str,
    corpus_root: Path,
) -> tuple[Path, list[dict[str, Any]]]:
    _require(plan.get("schema_version") == 1, "plan schema mismatch")
    _require(plan.get("plan_version") == PLAN_VERSION, "plan version mismatch")
    _require(plan.get("result") == "READY_TO_FREEZE", "plan is not READY_TO_FREEZE")
    fingerprint = str(plan.get("plan_fingerprint") or "")
    _require(bool(SHA256_RE.fullmatch(fingerprint)), "plan fingerprint is invalid")
    _require(fingerprint == expected_plan_fingerprint, "plan fingerprint does not match owner request")

    apply_contract = plan.get("apply_contract")
    _require(isinstance(apply_contract, Mapping), "apply contract is missing")
    expected_contract = {
        "mode": "exclusive_create_only",
        "required_owner": "andris:andris",
        "directory_mode": "0700",
        "file_mode": "0600",
        "post_copy_sha256_verification_required": True,
        "rollback_before_commit": "remove_private_staging_only",
        "separate_owner_authorization_required": True,
    }
    for key, value in expected_contract.items():
        _require(apply_contract.get(key) == value, f"apply contract mismatch: {key}")

    safety = plan.get("safety")
    _require(isinstance(safety, Mapping), "plan safety block is missing")
    expected_safety = {
        "plan_only": True,
        "corpus_write_authorized": False,
        "database_write_authorized": False,
        "review_write_authorized": False,
        "production_publish_authorized": False,
        "production_deploy_authorized": False,
        "systemd_change_authorized": False,
        "bounded_retry_authorized": False,
    }
    for key, value in expected_safety.items():
        _require(safety.get(key) is value, f"plan safety mismatch: {key}")

    corpus_root = corpus_root.resolve()
    flyers_root = (corpus_root / "flyers").resolve()
    _require(
        corpus_root.is_dir() and not corpus_root.is_symlink(),
        "authoritative corpus root is missing or unsafe",
    )
    _require(
        flyers_root.is_dir() and not flyers_root.is_symlink(),
        "authoritative flyers root is missing or unsafe",
    )

    destination_block = plan.get("destination")
    _require(isinstance(destination_block, Mapping), "plan destination block is missing")
    _require(destination_block.get("must_not_exist") is True, "destination must_not_exist contract mismatch")
    destination = Path(str(destination_block.get("flyer_dir") or ""))
    _require(destination.is_absolute(), "planned destination is not absolute")
    _require(destination.parent == flyers_root, "planned destination is not a direct flyers-root child")
    _require(not destination.exists() and not destination.is_symlink(), "planned destination already exists")

    files = destination_block.get("files")
    _require(isinstance(files, list) and len(files) == 3, "plan must contain exactly three source files")
    expected_destinations = {
        "source.pdf": destination / "source.pdf",
        "source.json": destination / "source.json",
        "meta.json": destination / "discovery-meta.json",
    }
    seen: set[str] = set()
    validated: list[dict[str, Any]] = []
    for raw in files:
        _require(isinstance(raw, Mapping), "plan file descriptor must be an object")
        name = str(raw.get("name") or "")
        _require(name in expected_destinations and name not in seen, f"unexpected or duplicate plan file: {name!r}")
        seen.add(name)
        source = Path(str(raw.get("source") or ""))
        planned_destination = Path(str(raw.get("destination") or ""))
        digest = str(raw.get("sha256") or "")
        byte_count = raw.get("bytes")
        _require(source.is_absolute(), f"source path is not absolute: {name}")
        _require(source.is_file() and not source.is_symlink(), f"source path is missing or unsafe: {name}")
        _require(planned_destination == expected_destinations[name], f"destination path mismatch: {name}")
        _require(bool(SHA256_RE.fullmatch(digest)), f"source SHA256 is invalid: {name}")
        _require(isinstance(byte_count, int) and byte_count >= 0, f"source byte count is invalid: {name}")
        validated.append(
            {
                "name": name,
                "source": source,
                "destination_name": planned_destination.name,
                "sha256": digest,
                "bytes": byte_count,
            }
        )
    _require(seen == set(expected_destinations), "plan source-file set is incomplete")
    return destination, validated


def _validate_authorization(
    authorization: Mapping[str, Any],
    *,
    plan: Mapping[str, Any],
    destination: Path,
    authorized_by: str,
) -> str:
    required_keys = {
        "schema_version",
        "authorization_version",
        "action",
        "authorized_by",
        "authorization_nonce",
        "plan_fingerprint",
        "issued_for_commit",
        "gate_a_run_dir",
        "destination",
        "source_pdf_sha256",
        "source_raw_sha256",
        "corpus_write_authorized",
        "parser_scan_authorized",
        "database_write_authorized",
        "review_write_authorized",
        "production_publish_authorized",
        "production_deploy_authorized",
        "systemd_change_authorized",
        "automatic_retry_authorized",
        "gate_c_d_authorized",
    }
    _require(set(authorization) == required_keys, "authorization field set mismatch")
    _require(authorization.get("schema_version") == 1, "authorization schema mismatch")
    _require(
        authorization.get("authorization_version") == AUTHORIZATION_VERSION,
        "authorization version mismatch",
    )
    _require(authorization.get("action") == AUTHORIZATION_ACTION, "authorization action mismatch")
    _require(authorization.get("authorized_by") == authorized_by, "authorization owner mismatch")
    nonce = str(authorization.get("authorization_nonce") or "")
    _require(bool(SHA256_RE.fullmatch(nonce)), "authorization nonce is invalid")
    _require(
        authorization.get("plan_fingerprint") == plan.get("plan_fingerprint"),
        "authorization plan fingerprint mismatch",
    )
    gate_a = plan.get("gate_a")
    source = plan.get("source")
    _require(isinstance(gate_a, Mapping), "plan Gate A block is missing")
    _require(isinstance(source, Mapping), "plan source block is missing")
    _require(
        authorization.get("issued_for_commit") == gate_a.get("registered_commit"),
        "authorization commit mismatch",
    )
    _require(
        authorization.get("gate_a_run_dir") == gate_a.get("run_dir"),
        "authorization Gate A run mismatch",
    )
    _require(authorization.get("destination") == str(destination), "authorization destination mismatch")
    _require(
        authorization.get("source_pdf_sha256") == source.get("pdf_sha256"),
        "authorization PDF SHA mismatch",
    )
    _require(
        authorization.get("source_raw_sha256") == source.get("raw_sha256"),
        "authorization raw SHA mismatch",
    )
    expected_flags = {
        "corpus_write_authorized": True,
        "parser_scan_authorized": False,
        "database_write_authorized": False,
        "review_write_authorized": False,
        "production_publish_authorized": False,
        "production_deploy_authorized": False,
        "systemd_change_authorized": False,
        "automatic_retry_authorized": False,
        "gate_c_d_authorized": False,
    }
    for key, value in expected_flags.items():
        _require(authorization.get(key) is value, f"authorization safety mismatch: {key}")
    return nonce


def _snapshot(metadata: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        _require(written > 0, "short destination write")
        view = view[written:]


def _copy_exact_file(
    descriptor: Mapping[str, Any],
    *,
    staging: Path,
    expected_uid: int,
    expected_gid: int,
) -> dict[str, Any]:
    source = Path(descriptor["source"])
    destination = staging / str(descriptor["destination_name"])
    source_flags = os.O_RDONLY | os.O_CLOEXEC
    destination_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        source_flags |= os.O_NOFOLLOW
        destination_flags |= os.O_NOFOLLOW

    source_fd = os.open(source, source_flags)
    destination_fd: int | None = None
    try:
        before = os.fstat(source_fd)
        _require(stat.S_ISREG(before.st_mode), f"source is not a regular file: {source}")
        _require(before.st_size == descriptor["bytes"], f"source byte count drift: {descriptor['name']}")
        destination_fd = os.open(destination, destination_flags, 0o600)
        digest = sha256()
        total = 0
        while True:
            chunk = os.read(source_fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            total += len(chunk)
            _write_all(destination_fd, chunk)
        os.fchmod(destination_fd, 0o600)
        os.fsync(destination_fd)
        destination_meta = os.fstat(destination_fd)
        _require(destination_meta.st_uid == expected_uid, f"destination owner UID mismatch: {descriptor['name']}")
        _require(destination_meta.st_gid == expected_gid, f"destination owner GID mismatch: {descriptor['name']}")
        _require(stat.S_IMODE(destination_meta.st_mode) == 0o600, f"destination mode mismatch: {descriptor['name']}")
        _require(total == descriptor["bytes"], f"copied byte count drift: {descriptor['name']}")
        actual_digest = digest.hexdigest()
        _require(actual_digest == descriptor["sha256"], f"copied SHA256 drift: {descriptor['name']}")
        after_fd = os.fstat(source_fd)
        after_path = source.stat(follow_symlinks=False)
        _require(_snapshot(before) == _snapshot(after_fd), f"source changed while copying: {descriptor['name']}")
        _require(_snapshot(before) == _snapshot(after_path), f"source path identity changed while copying: {descriptor['name']}")
        return {
            "name": descriptor["name"],
            "path": destination.name,
            "bytes": total,
            "sha256": actual_digest,
            "mode": "0600",
        }
    finally:
        if destination_fd is not None:
            os.close(destination_fd)
        os.close(source_fd)


def _write_receipt_file(
    staging: Path,
    receipt: Mapping[str, Any],
    *,
    expected_uid: int,
    expected_gid: int,
) -> dict[str, Any]:
    path = staging / RECEIPT_NAME
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    payload = _canonical_bytes(receipt)
    try:
        _write_all(fd, payload)
        os.fchmod(fd, 0o600)
        os.fsync(fd)
        metadata = os.fstat(fd)
        _require(metadata.st_uid == expected_uid, "receipt owner UID mismatch")
        _require(metadata.st_gid == expected_gid, "receipt owner GID mismatch")
        _require(stat.S_IMODE(metadata.st_mode) == 0o600, "receipt mode mismatch")
    finally:
        os.close(fd)
    return {
        "name": RECEIPT_NAME,
        "path": RECEIPT_NAME,
        "bytes": len(payload),
        "sha256": sha256(payload).hexdigest(),
        "mode": "0600",
    }


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _rename_noreplace(source: Path, destination: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    _require(renameat2 is not None, "renameat2 is unavailable; refusing non-exclusive commit")
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    result = renameat2(
        AT_FDCWD,
        os.fsencode(source),
        AT_FDCWD,
        os.fsencode(destination),
        RENAME_NOREPLACE,
    )
    if result != 0:
        error_number = ctypes.get_errno()
        if error_number == errno.EEXIST:
            raise LidlGateBFreezeApplyError("exclusive corpus destination already exists")
        raise LidlGateBFreezeApplyError(
            f"exclusive corpus commit failed: errno={error_number}"
        )


def _remove_private_staging(staging: Path, *, flyers_root: Path) -> None:
    if not staging.exists() and not staging.is_symlink():
        return
    _require(staging.parent == flyers_root, "refusing cleanup outside flyers root")
    _require(bool(STAGING_RE.fullmatch(staging.name)), "refusing cleanup of unexpected staging path")
    _require(not staging.is_symlink(), "refusing cleanup of symlinked staging path")
    shutil.rmtree(staging)


def _verify_committed_snapshot(
    destination: Path,
    *,
    expected_files: list[dict[str, Any]],
    expected_uid: int,
    expected_gid: int,
) -> None:
    _require(destination.is_dir() and not destination.is_symlink(), "committed destination is missing or unsafe", committed=True)
    metadata = destination.stat(follow_symlinks=False)
    _require(metadata.st_uid == expected_uid, "committed directory owner UID mismatch", committed=True)
    _require(metadata.st_gid == expected_gid, "committed directory owner GID mismatch", committed=True)
    _require(stat.S_IMODE(metadata.st_mode) == 0o700, "committed directory mode mismatch", committed=True)
    expected_names = {row["path"] for row in expected_files}
    actual_names = {path.name for path in destination.iterdir()}
    _require(actual_names == expected_names, "committed file set mismatch", committed=True)
    for row in expected_files:
        path = destination / row["path"]
        _require(path.is_file() and not path.is_symlink(), f"committed file is missing or unsafe: {row['path']}", committed=True)
        file_meta = path.stat(follow_symlinks=False)
        _require(file_meta.st_uid == expected_uid, f"committed file owner UID mismatch: {row['path']}", committed=True)
        _require(file_meta.st_gid == expected_gid, f"committed file owner GID mismatch: {row['path']}", committed=True)
        _require(stat.S_IMODE(file_meta.st_mode) == 0o600, f"committed file mode mismatch: {row['path']}", committed=True)
        _require(file_meta.st_size == row["bytes"], f"committed byte count mismatch: {row['path']}", committed=True)
        _require(_sha256_path(path) == row["sha256"], f"committed SHA256 mismatch: {row['path']}", committed=True)


def apply_freeze(
    *,
    gate_a_run_dir: Path,
    evidence_root: Path,
    corpus_root: Path,
    expected_plan_fingerprint: str,
    authorization_file: Path,
    expected_uid: int,
    expected_gid: int,
    authorized_by: str,
) -> dict[str, Any]:
    _require(bool(SHA256_RE.fullmatch(expected_plan_fingerprint)), "expected plan fingerprint is invalid")
    plan = build_freeze_plan(
        gate_a_run_dir=gate_a_run_dir,
        evidence_root=evidence_root,
        corpus_root=corpus_root,
    )
    destination, file_descriptors = _validate_plan(
        plan,
        expected_plan_fingerprint=expected_plan_fingerprint,
        corpus_root=corpus_root,
    )
    authorization = _load_authorization(
        authorization_file,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    nonce = _validate_authorization(
        authorization,
        plan=plan,
        destination=destination,
        authorized_by=authorized_by,
    )

    flyers_root = destination.parent
    staging = flyers_root / f".gate-b-freeze-{expected_plan_fingerprint[:16]}.staging"
    _require(not staging.exists() and not staging.is_symlink(), "private staging path already exists")
    os.mkdir(staging, 0o700)
    committed = False
    try:
        stage_meta = staging.stat(follow_symlinks=False)
        _require(stage_meta.st_uid == expected_uid, "staging owner UID mismatch")
        _require(stage_meta.st_gid == expected_gid, "staging owner GID mismatch")
        _require(stat.S_IMODE(stage_meta.st_mode) == 0o700, "staging mode mismatch")

        copied_files = [
            _copy_exact_file(
                descriptor,
                staging=staging,
                expected_uid=expected_uid,
                expected_gid=expected_gid,
            )
            for descriptor in file_descriptors
        ]
        rebuilt_plan = build_freeze_plan(
            gate_a_run_dir=gate_a_run_dir,
            evidence_root=evidence_root,
            corpus_root=corpus_root,
        )
        _require(
            _canonical_bytes(rebuilt_plan) == _canonical_bytes(plan),
            "freeze plan drifted after staging copy",
        )

        receipt: dict[str, Any] = {
            "schema_version": 1,
            "apply_version": APPLY_VERSION,
            "result": "FROZEN",
            "reason": "exact_authorized_source_committed_exclusively",
            "plan_version": plan["plan_version"],
            "plan_fingerprint": plan["plan_fingerprint"],
            "authorization_version": AUTHORIZATION_VERSION,
            "authorization_nonce": nonce,
            "authorized_by": authorized_by,
            "gate_a": plan["gate_a"],
            "source": plan["source"],
            "destination": str(destination),
            "files": copied_files,
            "safety": {
                "corpus_write_performed": True,
                "parser_scan_performed": False,
                "database_write_performed": False,
                "review_write_performed": False,
                "production_publish_performed": False,
                "production_deploy_performed": False,
                "systemd_change_performed": False,
                "automatic_retry_performed": False,
                "gate_c_d_authorized": False,
            },
        }
        receipt_descriptor = _write_receipt_file(
            staging,
            receipt,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        expected_committed_files = [*copied_files, receipt_descriptor]
        _fsync_directory(staging)
        _rename_noreplace(staging, destination)
        committed = True
        _fsync_directory(flyers_root)
        _verify_committed_snapshot(
            destination,
            expected_files=expected_committed_files,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        return receipt
    except Exception as exc:
        if not committed:
            _remove_private_staging(staging, flyers_root=flyers_root)
        if isinstance(exc, LidlGateBFreezeApplyError):
            raise
        if isinstance(exc, LidlGateBFreezePlanError):
            raise LidlGateBFreezeApplyError(str(exc), committed=committed) from exc
        raise LidlGateBFreezeApplyError(
            f"unexpected apply failure: {type(exc).__name__}: {exc}",
            committed=committed,
        ) from exc


def _cli_owner() -> tuple[int, int, str]:
    user = pwd.getpwnam("andris")
    group = grp.getgrnam("andris")
    _require(os.geteuid() == user.pw_uid, "apply must run as andris, not through sudo/root")
    _require(os.getegid() == group.gr_gid, "apply primary group must be andris")
    return user.pw_uid, group.gr_gid, user.pw_name


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Apply one separately owner-authorized Lidl Gate B source freeze. "
            "The exact validated source is copied into private staging and "
            "committed atomically with renameat2(RENAME_NOREPLACE)."
        )
    )
    parser.add_argument("--gate-a-run-dir", type=Path, required=True)
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=Path("/home/andris/hermes-deals-lidl-gate-a-evidence"),
    )
    parser.add_argument(
        "--corpus-root",
        type=Path,
        default=Path("/home/andris/hermes-deals-lidl-corpus"),
    )
    parser.add_argument("--expected-plan-fingerprint", required=True)
    parser.add_argument("--authorization-file", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        expected_uid, expected_gid, authorized_by = _cli_owner()
        receipt = apply_freeze(
            gate_a_run_dir=args.gate_a_run_dir,
            evidence_root=args.evidence_root,
            corpus_root=args.corpus_root,
            expected_plan_fingerprint=args.expected_plan_fingerprint,
            authorization_file=args.authorization_file,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
            authorized_by=authorized_by,
        )
    except LidlGateBFreezeApplyError as exc:
        prefix = "COMMITTED_BLOCKED" if exc.committed else "BLOCKED"
        print(f"{prefix}: {exc}")
        return 31 if exc.committed else 30
    except LidlGateBFreezePlanError as exc:
        print(f"BLOCKED: {exc}")
        return 30
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    print("RESULT=FROZEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
