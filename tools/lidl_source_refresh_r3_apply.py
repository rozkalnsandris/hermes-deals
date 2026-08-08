#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import shutil
import stat
import sys
import tempfile
from typing import Any, Mapping
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import lidl_source_refresh_r3_plan as r3  # noqa: E402
from lidl_source_refresh_r3_plan_v2 import install_r2_digest_contract  # noqa: E402

install_r2_digest_contract()

APPLY_VERSION = "lidl-source-refresh-r3-promotion-apply-v1"
EXPECTED_PLAN_FINGERPRINT = "8aaf1f96a119e51c980a45da80031d5abd2db65d4cdc3516bd5368fd0537c7f9"
EXPECTED_R2_ARTIFACT_ID = 9021545332
EXPECTED_R2_ARTIFACT_DIGEST = "d4f9be1a19592a45739e4cc6a2827833682460e1c41bdd6496e0375077ef33c4"
EXPECTED_R3_PLAN_ARTIFACT_ID = 9024741383
EXPECTED_R3_PLAN_ARTIFACT_DIGEST = "c1432c05d3975094d2e56ae70fc216c8e8def4199ac312c92b2ff50afc9032dc"
EXPECTED_AUTHORIZATION_COMMENT_ID = 5227260615
EXPECTED_OWNER_LOGIN = "andris"
EXPECTED_APPROVED_BY = "Andris Rožkalns"
EXPECTED_CORPUS_ROOT = Path("/home/andris/hermes-deals-lidl-corpus")
EXPECTED_FAMILY = r3.EXPECTED_FAMILY
EXPECTED_SCAN_NAME = r3.EXPECTED_SCAN_NAME
EXPECTED_LIVE_INPUT_SHA = r3.EXPECTED_LIVE_INPUT_SHA256
EXPECTED_SCAN_TREE_SHA = r3.EXPECTED_SCAN_TREE_SHA256
EXPECTED_SOURCE_REVIEW_SHA = r3.EXPECTED_REVIEW_SHA256
EXPECTED_AUTHORITY_CORE_SHA = "3e1555a155dfb7f1eb16b12e837bc9fba1c38d36212616633468f58b0ee106cc"

RENAME_NOREPLACE = 1
AT_FDCWD = -100


class R3ApplyError(RuntimeError):
    pass


def _sha256_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_bytes(payload: Any) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _semantic_digest(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _require_sha(value: Any, label: str) -> str:
    text = str(value or "")
    if len(text) != 64 or any(c not in "0123456789abcdef" for c in text):
        raise R3ApplyError(f"{label} must be a lowercase SHA-256")
    return text


def _load_object_bytes(data: bytes, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise R3ApplyError(f"{label} is invalid JSON") from exc
    if not isinstance(payload, Mapping):
        raise R3ApplyError(f"{label} must contain an object")
    return dict(payload)


def _load_object(path: Path, label: str, *, max_bytes: int = 512 * 1024) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise R3ApplyError(f"{label} is missing or unsafe")
    if path.stat().st_size > max_bytes:
        raise R3ApplyError(f"{label} exceeds size limit")
    return _load_object_bytes(path.read_bytes(), label)


def _safe_zip_files(path: Path, *, expected_digest: str, expected_members: int | None = None) -> dict[str, bytes]:
    if not path.is_file() or path.is_symlink():
        raise R3ApplyError(f"artifact ZIP is missing or unsafe: {path}")
    if _sha256_file(path) != expected_digest:
        raise R3ApplyError("artifact ZIP digest mismatch")
    files: dict[str, bytes] = {}
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if expected_members is not None and len(infos) != expected_members:
            raise R3ApplyError("artifact member count mismatch")
        for info in infos:
            p = PurePosixPath(info.filename)
            if p.is_absolute() or not p.parts or ".." in p.parts:
                raise R3ApplyError(f"unsafe artifact path: {info.filename}")
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise R3ApplyError(f"artifact symlink is forbidden: {info.filename}")
            if info.is_dir():
                raise R3ApplyError("directory entries are not expected in artifact")
            if mode and not stat.S_ISREG(mode):
                raise R3ApplyError(f"unsupported artifact entry: {info.filename}")
            if info.filename in files:
                raise R3ApplyError("duplicate artifact member")
            files[info.filename] = archive.read(info)
    return files


def _load_r3_plan(plan_zip: Path) -> dict[str, Any]:
    files = _safe_zip_files(
        plan_zip,
        expected_digest=EXPECTED_R3_PLAN_ARTIFACT_DIGEST,
        expected_members=1,
    )
    if set(files) != {"r3-plan-v2.json"}:
        raise R3ApplyError("unexpected R3 plan artifact member set")
    plan = _load_object_bytes(files["r3-plan-v2.json"], "R3 plan")
    if plan.get("result") != "R3_PLAN_READY":
        raise R3ApplyError("R3 plan result mismatch")
    if plan.get("plan_fingerprint") != EXPECTED_PLAN_FINGERPRINT:
        raise R3ApplyError("R3 plan fingerprint mismatch")
    return plan


def _rebuild_r3_plan(r2_zip: Path) -> dict[str, Any]:
    try:
        return r3.build_plan(
            artifact_zip=r2_zip,
            artifact_id=EXPECTED_R2_ARTIFACT_ID,
            artifact_digest=EXPECTED_R2_ARTIFACT_DIGEST,
        )
    except Exception as exc:
        raise R3ApplyError(f"R2/R3 plan replay failed: {type(exc).__name__}: {exc}") from exc


def _validate_plan(plan: Mapping[str, Any], replay: Mapping[str, Any]) -> None:
    if dict(plan) != dict(replay):
        raise R3ApplyError("retained R3 plan differs from deterministic R2 replay")
    if plan.get("plan_fingerprint") != EXPECTED_PLAN_FINGERPRINT:
        raise R3ApplyError("retained R3 plan fingerprint drift")
    exact = plan.get("exact_payloads")
    if not isinstance(exact, Mapping):
        raise R3ApplyError("R3 exact payloads missing")
    if exact.get("scan_tree_sha256") != EXPECTED_SCAN_TREE_SHA:
        raise R3ApplyError("R3 scan tree SHA mismatch")
    if exact.get("source_review_sha256") != EXPECTED_SOURCE_REVIEW_SHA:
        raise R3ApplyError("R3 source-review SHA mismatch")
    if exact.get("authority_core_sha256") != EXPECTED_AUTHORITY_CORE_SHA:
        raise R3ApplyError("R3 authority-core SHA mismatch")
    core = plan.get("authority_core")
    if not isinstance(core, Mapping) or _semantic_digest(core) != EXPECTED_AUTHORITY_CORE_SHA:
        raise R3ApplyError("R3 authority-core payload mismatch")
    prediction = plan.get("prediction")
    if not isinstance(prediction, Mapping):
        raise R3ApplyError("R3 prediction missing")
    if prediction.get("expected_gate_a_state_after_valid_promotion") != "WAIT_PROFILE":
        raise R3ApplyError("R3 Gate A prediction mismatch")
    if prediction.get("ready_is_forbidden_without_independent_rev05_profile") is not True:
        raise R3ApplyError("R3 plan incorrectly permits READY")


def _validate_authorization(path: Path) -> dict[str, Any]:
    auth = _load_object(path, "R3 promotion authorization")
    expected_fields = {
        "schema_version",
        "authorization_version",
        "decision",
        "approved_by",
        "approved_at",
        "authorization_comment_id",
        "plan_fingerprint",
        "r2_artifact_id",
        "r2_artifact_digest",
        "r3_plan_artifact_id",
        "r3_plan_artifact_digest",
        "permissions",
    }
    if set(auth) != expected_fields:
        raise R3ApplyError("R3 authorization field set mismatch")
    if auth.get("schema_version") != 1:
        raise R3ApplyError("R3 authorization schema mismatch")
    if auth.get("authorization_version") != "lidl-source-refresh-r3-promotion-authorization-v1":
        raise R3ApplyError("R3 authorization version mismatch")
    if auth.get("decision") != "approve_exact_r3_promotion":
        raise R3ApplyError("R3 authorization decision mismatch")
    if auth.get("approved_by") != EXPECTED_APPROVED_BY:
        raise R3ApplyError("R3 authorization approver mismatch")
    approved_at = str(auth.get("approved_at") or "")
    try:
        parsed = datetime.fromisoformat(approved_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise R3ApplyError("R3 authorization timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise R3ApplyError("R3 authorization timestamp must be timezone-aware")
    if auth.get("authorization_comment_id") != EXPECTED_AUTHORIZATION_COMMENT_ID:
        raise R3ApplyError("R3 authorization comment ID mismatch")
    if auth.get("plan_fingerprint") != EXPECTED_PLAN_FINGERPRINT:
        raise R3ApplyError("R3 authorization fingerprint mismatch")
    if auth.get("r2_artifact_id") != EXPECTED_R2_ARTIFACT_ID:
        raise R3ApplyError("R3 authorization R2 artifact ID mismatch")
    if auth.get("r2_artifact_digest") != EXPECTED_R2_ARTIFACT_DIGEST:
        raise R3ApplyError("R3 authorization R2 artifact digest mismatch")
    if auth.get("r3_plan_artifact_id") != EXPECTED_R3_PLAN_ARTIFACT_ID:
        raise R3ApplyError("R3 authorization plan artifact ID mismatch")
    if auth.get("r3_plan_artifact_digest") != EXPECTED_R3_PLAN_ARTIFACT_DIGEST:
        raise R3ApplyError("R3 authorization plan artifact digest mismatch")
    expected_permissions = {
        "corpus_write": True,
        "scan_promotion": True,
        "source_review_promotion": True,
        "authority_promotion": True,
        "profile_promotion": False,
        "database_write": False,
        "review_write": False,
        "auto_approve": False,
        "auto_publish": False,
        "production_deploy": False,
        "systemd_change": False,
        "automatic_retry": False,
        "gate_c_d": False,
        "b15m2_v08": False,
    }
    if auth.get("permissions") != expected_permissions:
        raise R3ApplyError("R3 authorization permissions mismatch")
    return auth


def _tree_manifest(root: Path) -> list[dict[str, Any]]:
    if not root.is_dir() or root.is_symlink():
        raise R3ApplyError("scan root is missing or unsafe")
    rows: list[dict[str, Any]] = []
    for p in sorted(root.rglob("*")):
        if p.is_symlink():
            raise R3ApplyError("scan contains a symlink")
        if p.is_dir():
            continue
        if not p.is_file():
            raise R3ApplyError("scan contains unsupported entry")
        rows.append({
            "path": p.relative_to(root).as_posix(),
            "bytes": p.stat().st_size,
            "sha256": _sha256_file(p),
        })
    return rows


def _tree_digest(rows: list[dict[str, Any]]) -> str:
    content = "\n".join(
        f"{row['path']}|{row['bytes']}|{row['sha256']}" for row in rows
    ) + "\n"
    return sha256(content.encode("utf-8")).hexdigest()


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_exclusive(path: Path, data: bytes, *, mode: int = 0o600) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    fd = os.open(path, flags, mode)
    try:
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(path, mode, follow_symlinks=False)
    finally:
        os.close(fd)


def _rename_noreplace(source: Path, target: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    fn = getattr(libc, "renameat2", None)
    if fn is None:
        raise R3ApplyError("renameat2 is unavailable; refusing non-exclusive commit")
    fn.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    fn.restype = ctypes.c_int
    rc = fn(
        AT_FDCWD,
        os.fsencode(source),
        AT_FDCWD,
        os.fsencode(target),
        RENAME_NOREPLACE,
    )
    if rc != 0:
        err = ctypes.get_errno()
        raise R3ApplyError(f"exclusive rename failed errno={err}: {os.strerror(err)}")


def _ensure_directory(path: Path, *, mode: int = 0o700) -> bool:
    if path.exists():
        if not path.is_dir() or path.is_symlink():
            raise R3ApplyError(f"unsafe directory: {path}")
        meta = path.stat()
        if stat.S_IMODE(meta.st_mode) != mode or meta.st_uid != os.geteuid() or meta.st_gid != os.getegid():
            raise R3ApplyError(f"directory ownership/mode mismatch: {path}")
        return False
    path.mkdir(mode=mode)
    os.chmod(path, mode)
    _fsync_dir(path.parent)
    return True


def _extract_r2_payloads(r2_zip: Path) -> tuple[dict[str, bytes], bytes]:
    files = _safe_zip_files(
        r2_zip,
        expected_digest=EXPECTED_R2_ARTIFACT_DIGEST,
        expected_members=15,
    )
    prefix = f"staging-scan/{EXPECTED_SCAN_NAME}/"
    scan_files = {
        name[len(prefix):]: data
        for name, data in files.items()
        if name.startswith(prefix) and name[len(prefix):]
    }
    if len(scan_files) != 11:
        raise R3ApplyError("R2 scan payload member count mismatch")
    review = files.get("evidence/approved-source-review.json")
    if review is None or _sha256_bytes(review) != EXPECTED_SOURCE_REVIEW_SHA:
        raise R3ApplyError("R2 source-review payload mismatch")
    if any("/" in name or name in {"", ".", ".."} for name in scan_files):
        raise R3ApplyError("R2 scan payload contains nested/unsafe name")
    return scan_files, review


def _verify_scan_payload(scan_files: Mapping[str, bytes], plan: Mapping[str, Any]) -> None:
    manifest = [
        {"path": name, "bytes": len(data), "sha256": _sha256_bytes(data)}
        for name, data in sorted(scan_files.items())
    ]
    if _tree_digest(manifest) != EXPECTED_SCAN_TREE_SHA:
        raise R3ApplyError("R2 scan payload tree SHA mismatch")
    expected = plan.get("scan_tree_manifest")
    if manifest != expected:
        raise R3ApplyError("R2 scan payload manifest differs from R3 plan")


def _build_authority(plan: Mapping[str, Any], auth: Mapping[str, Any]) -> dict[str, Any]:
    core = plan.get("authority_core")
    if not isinstance(core, Mapping):
        raise R3ApplyError("R3 authority core missing")
    authority = dict(core)
    authority["promotion"] = {
        "approved_by": auth["approved_by"],
        "approved_at": auth["approved_at"],
        "authorization_comment_id": auth["authorization_comment_id"],
        "r2_artifact_id": auth["r2_artifact_id"],
        "r2_artifact_digest": auth["r2_artifact_digest"],
    }
    return authority


def _build_receipt(
    *,
    plan: Mapping[str, Any],
    auth: Mapping[str, Any],
    authority_sha: str,
    authorization_sha: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "apply_version": APPLY_VERSION,
        "result": "PROMOTED",
        "plan_fingerprint": EXPECTED_PLAN_FINGERPRINT,
        "authorization_comment_id": EXPECTED_AUTHORIZATION_COMMENT_ID,
        "authorization_sha256": authorization_sha,
        "r2_artifact": {
            "id": EXPECTED_R2_ARTIFACT_ID,
            "digest": EXPECTED_R2_ARTIFACT_DIGEST,
        },
        "r3_plan_artifact": {
            "id": EXPECTED_R3_PLAN_ARTIFACT_ID,
            "digest": EXPECTED_R3_PLAN_ARTIFACT_DIGEST,
        },
        "payloads": {
            "scan_tree_sha256": EXPECTED_SCAN_TREE_SHA,
            "source_review_sha256": EXPECTED_SOURCE_REVIEW_SHA,
            "authority_core_sha256": EXPECTED_AUTHORITY_CORE_SHA,
            "authority_sha256": authority_sha,
        },
        "targets": dict(plan["targets"]),
        "prediction": {
            "expected_gate_a_state": "WAIT_PROFILE",
            "rev04_profile_reuse_forbidden": True,
        },
        "safety": {
            "corpus_write_performed": True,
            "scan_promotion_performed": True,
            "source_review_promotion_performed": True,
            "authority_promotion_performed": True,
            "profile_promotion_performed": False,
            "database_write_performed": False,
            "review_write_performed": False,
            "auto_approve_performed": False,
            "auto_publish_performed": False,
            "production_deploy_performed": False,
            "systemd_change_performed": False,
            "automatic_retry_performed": False,
            "gate_c_d_authorized": False,
            "b15m2_v08_authorized": False,
        },
    }


def _verify_frozen_family(corpus_root: Path, plan: Mapping[str, Any]) -> Path:
    corpus_root = corpus_root.resolve()
    if corpus_root != EXPECTED_CORPUS_ROOT:
        raise R3ApplyError("unexpected corpus root")
    if not corpus_root.is_dir() or corpus_root.is_symlink():
        raise R3ApplyError("corpus root is missing or unsafe")
    family = corpus_root / "flyers" / EXPECTED_FAMILY
    if not family.is_dir() or family.is_symlink():
        raise R3ApplyError("rev05 family is missing or unsafe")
    family_meta = family.stat()
    if stat.S_IMODE(family_meta.st_mode) != 0o700 or family_meta.st_uid != os.geteuid() or family_meta.st_gid != os.getegid():
        raise R3ApplyError("rev05 family ownership/mode mismatch")
    source_pdf = family / "source.pdf"
    source_json = family / "source.json"
    for source in (source_pdf, source_json):
        if not source.is_file() or source.is_symlink():
            raise R3ApplyError("immutable rev05 source file is missing or unsafe")
        meta = source.stat()
        if stat.S_IMODE(meta.st_mode) != 0o600 or meta.st_uid != os.geteuid() or meta.st_gid != os.getegid():
            raise R3ApplyError("immutable rev05 source metadata mismatch")
    if _sha256_file(source_pdf) != r3.EXPECTED_PDF_SHA256:
        raise R3ApplyError("immutable rev05 PDF SHA mismatch")
    if _sha256_file(source_json) != r3.EXPECTED_FROZEN_RAW_SHA256:
        raise R3ApplyError("immutable rev05 source JSON SHA mismatch")
    profile = family / "review-profile.json"
    if profile.exists() or profile.is_symlink():
        raise R3ApplyError("rev05 review-profile must remain absent for R3")
    expected_targets = {
        family / "scans" / EXPECTED_SCAN_NAME,
        family / "source-refresh" / EXPECTED_LIVE_INPUT_SHA / "source-review.json",
        family / "source-refresh" / EXPECTED_LIVE_INPUT_SHA / "authority.json",
        family / "source-refresh" / EXPECTED_LIVE_INPUT_SHA / "promotion-receipt.json",
    }
    for target in expected_targets:
        if target.exists() or target.is_symlink():
            raise R3ApplyError(f"R3 target is already occupied: {target}")
    if set(plan["preconditions"]["all_targets_must_be_absent"]) != set(plan["targets"].values()):
        raise R3ApplyError("R3 target precondition mismatch")
    return family


def apply_exact_promotion(
    *,
    corpus_root: Path,
    r2_zip: Path,
    r3_plan_zip: Path,
    authorization_file: Path,
) -> dict[str, Any]:
    if pwd.getpwuid(os.geteuid()).pw_name != EXPECTED_OWNER_LOGIN:
        raise R3ApplyError("R3 promotion must run as andris")
    plan = _load_r3_plan(r3_plan_zip)
    replay = _rebuild_r3_plan(r2_zip)
    _validate_plan(plan, replay)
    auth = _validate_authorization(authorization_file)
    authorization_sha = _sha256_file(authorization_file)
    scan_files, review_bytes = _extract_r2_payloads(r2_zip)
    _verify_scan_payload(scan_files, plan)
    family = _verify_frozen_family(corpus_root, plan)

    authority = _build_authority(plan, auth)
    authority_bytes = _canonical_bytes(authority)
    authority_sha = _sha256_bytes(authority_bytes)
    receipt = _build_receipt(
        plan=plan,
        auth=auth,
        authority_sha=authority_sha,
        authorization_sha=authorization_sha,
    )
    receipt_bytes = _canonical_bytes(receipt)

    scans_root = family / "scans"
    refresh_root = family / "source-refresh"
    created_scans_root = _ensure_directory(scans_root)
    created_refresh_root = _ensure_directory(refresh_root)

    scan_target = scans_root / EXPECTED_SCAN_NAME
    refresh_target = refresh_root / EXPECTED_LIVE_INPUT_SHA
    if scan_target.exists() or scan_target.is_symlink():
        raise R3ApplyError("scan target became occupied before commit")
    if refresh_target.exists() or refresh_target.is_symlink():
        raise R3ApplyError("refresh target became occupied before commit")

    scan_stage = Path(tempfile.mkdtemp(prefix=".r3-scan-", dir=scans_root))
    refresh_stage = Path(tempfile.mkdtemp(prefix=".r3-refresh-", dir=refresh_root))
    os.chmod(scan_stage, 0o700)
    os.chmod(refresh_stage, 0o700)
    scan_committed = False
    refresh_committed = False
    try:
        for name, data in sorted(scan_files.items()):
            _write_exclusive(scan_stage / name, data)
        if _tree_digest(_tree_manifest(scan_stage)) != EXPECTED_SCAN_TREE_SHA:
            raise R3ApplyError("scan staging verification failed")
        _fsync_dir(scan_stage)

        _write_exclusive(refresh_stage / "source-review.json", review_bytes)
        _write_exclusive(refresh_stage / "authority.json", authority_bytes)
        _write_exclusive(refresh_stage / "promotion-receipt.json", receipt_bytes)
        if _sha256_file(refresh_stage / "source-review.json") != EXPECTED_SOURCE_REVIEW_SHA:
            raise R3ApplyError("source-review staging SHA mismatch")
        if _sha256_file(refresh_stage / "authority.json") != authority_sha:
            raise R3ApplyError("authority staging SHA mismatch")
        _fsync_dir(refresh_stage)

        # Commit scan first. Without authority Gate A remains fail-closed.
        _rename_noreplace(scan_stage, scan_target)
        scan_committed = True
        _fsync_dir(scans_root)

        # Commit source-review + authority + receipt as one refresh directory.
        _rename_noreplace(refresh_stage, refresh_target)
        refresh_committed = True
        _fsync_dir(refresh_root)
    finally:
        if not scan_committed:
            shutil.rmtree(scan_stage, ignore_errors=True)
        if not refresh_committed:
            shutil.rmtree(refresh_stage, ignore_errors=True)
        if created_refresh_root and not refresh_committed and refresh_root.exists() and not any(refresh_root.iterdir()):
            refresh_root.rmdir()
            _fsync_dir(family)
        if created_scans_root and not scan_committed and scans_root.exists() and not any(scans_root.iterdir()):
            scans_root.rmdir()
            _fsync_dir(family)

    if _tree_digest(_tree_manifest(scan_target)) != EXPECTED_SCAN_TREE_SHA:
        raise R3ApplyError("committed scan tree mismatch")
    if _sha256_file(refresh_target / "source-review.json") != EXPECTED_SOURCE_REVIEW_SHA:
        raise R3ApplyError("committed source-review SHA mismatch")
    if _sha256_file(refresh_target / "authority.json") != authority_sha:
        raise R3ApplyError("committed authority SHA mismatch")
    committed_receipt = _load_object(refresh_target / "promotion-receipt.json", "promotion receipt")
    if committed_receipt != receipt:
        raise R3ApplyError("committed promotion receipt mismatch")
    if (family / "review-profile.json").exists() or (family / "review-profile.json").is_symlink():
        raise R3ApplyError("rev05 review-profile appeared during R3 promotion")
    if _sha256_file(family / "source.pdf") != r3.EXPECTED_PDF_SHA256:
        raise R3ApplyError("immutable source PDF changed during promotion")
    if _sha256_file(family / "source.json") != r3.EXPECTED_FROZEN_RAW_SHA256:
        raise R3ApplyError("immutable source JSON changed during promotion")

    return {
        "schema_version": 1,
        "apply_version": APPLY_VERSION,
        "result": "R3_PROMOTION_PASS",
        "plan_fingerprint": EXPECTED_PLAN_FINGERPRINT,
        "scan_tree_sha256": EXPECTED_SCAN_TREE_SHA,
        "source_review_sha256": EXPECTED_SOURCE_REVIEW_SHA,
        "authority_core_sha256": EXPECTED_AUTHORITY_CORE_SHA,
        "authority_sha256": authority_sha,
        "authorization_sha256": authorization_sha,
        "authorization_comment_id": EXPECTED_AUTHORIZATION_COMMENT_ID,
        "expected_gate_a_state": "WAIT_PROFILE",
        "writes_performed": {
            "scan_directory": True,
            "source_refresh_directory": True,
            "review_profile": False,
        },
        "safety": receipt["safety"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply the exact owner-authorized Lidl rev05 R3 source-refresh promotion"
    )
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--r2-artifact-zip", type=Path, required=True)
    parser.add_argument("--r3-plan-artifact-zip", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.output.exists() or args.output.is_symlink():
            raise R3ApplyError("output path already exists")
        result = apply_exact_promotion(
            corpus_root=args.corpus_root,
            r2_zip=args.r2_artifact_zip,
            r3_plan_zip=args.r3_plan_artifact_zip,
            authorization_file=args.authorization,
        )
        _write_exclusive(args.output, _canonical_bytes(result))
    except Exception as exc:
        print(f"R3_PROMOTION_BLOCKED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 30
    print(json.dumps(result, sort_keys=True))
    print("RESULT=R3_PROMOTION_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
