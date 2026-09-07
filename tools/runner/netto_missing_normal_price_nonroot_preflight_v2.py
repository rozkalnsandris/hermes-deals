#!/usr/bin/env python3
from __future__ import annotations

import argparse
import grp
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
import sys
from typing import Any, Mapping, Sequence

CAPABILITY = "netto-missing-normal-price-nonroot-preflight-v2"
REGISTRATION_SCHEMA = "rozkalns.hermes-deals.netto-nonroot-preflight-v2-registration.v1"
RESULT_SCHEMA = "rozkalns.hermes-deals.netto-nonroot-preflight-v2-evidence.v1"

REGISTRATION_PATH = Path(
    "/etc/hermes-deals-audits.d/netto-missing-normal-price-nonroot-preflight-v2.json"
)
INSTALLED_HELPER_PATH = Path(
    "/usr/local/libexec/hermes-deals-audits/netto-missing-normal-price-nonroot-preflight-v2/"
    "netto_missing_normal_price_nonroot_preflight_v2.py"
)

N9_PATH = Path(
    "/home/andris/hermes-deals-audits/"
    "netto-n9-visual-cell-validation-pack-v1-20260802T202304Z/"
    "generated/fixture-manifest.json"
)
N9_SHA256 = "2b180d67af4c5d1e586704088e3d685cff21ae2e12f3052254daf4553dd4e147"
CORPUS_ROOT = Path("/home/andris/hermes-deals-netto-corpus/flyers")
HOME_ANDRIS = Path("/home/andris")

MAX_REGISTRATION_BYTES = 16 * 1024
MAX_RESULT_BYTES = 32 * 1024
SOURCE_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

REGISTRATION_FIELDS = {
    "schema",
    "capability",
    "registered_source_sha",
    "helper_sha256",
}
RESULT_FIELDS = {
    "schema",
    "schema_version",
    "strategy",
    "capability",
    "registered_source_sha",
    "runner_user",
    "runner_uid",
    "n9_manifest_readable",
    "n9_manifest_sha256_match",
    "corpus_root_readable",
    "corpus_root_executable",
    "blocked_at",
    "non_root_ready",
    "safe_permission_metadata",
    "sudo_used",
    "file_contents_exported",
    "parser_executed",
    "database_write_performed",
    "review_write_performed",
    "deployment_performed",
}
PERMISSION_FIELDS = {
    "home_andris_mode",
    "home_andris_uid",
    "home_andris_gid",
    "n9_parent_mode",
    "corpus_root_mode",
}
ALLOWED_BLOCKED_AT = {
    "n9_manifest_unreadable",
    "n9_manifest_identity_mismatch",
    "corpus_root_unreadable",
    "campaign_identity_probe_required",
}
FALSE_POSTCONDITIONS = (
    "sudo_used",
    "file_contents_exported",
    "parser_executed",
    "database_write_performed",
    "review_write_performed",
    "deployment_performed",
)


class ContractError(RuntimeError):
    pass


def _canonical_source_sha(value: str) -> str:
    if not SOURCE_SHA_RE.fullmatch(value):
        raise ContractError("invalid registered source SHA")
    return value


def _reject_json_constant(value: str) -> None:
    raise ContractError(f"non-finite JSON value is forbidden: {value}")


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON key is forbidden: {key}")
        result[key] = value
    return result


def _load_json_bytes(raw: bytes) -> Any:
    if len(raw) > MAX_REGISTRATION_BYTES:
        raise ContractError("registration JSON exceeds 16 KiB")
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContractError("invalid registration JSON") from error


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_secure_file(
    path: Path,
    *,
    expected_mode: int,
    expected_uid: int = 0,
    expected_gid: int = 0,
    expected_sha256: str | None = None,
) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise ContractError(f"required file is missing: {path}") from error
    if not stat.S_ISREG(metadata.st_mode):
        raise ContractError(f"required path is not a regular file: {path}")
    if metadata.st_uid != expected_uid or metadata.st_gid != expected_gid:
        raise ContractError(f"file ownership mismatch: {path}")
    if stat.S_IMODE(metadata.st_mode) != expected_mode:
        raise ContractError(f"file mode mismatch: {path}")
    if expected_sha256 is not None:
        if not SHA256_RE.fullmatch(expected_sha256):
            raise ContractError("invalid registered helper SHA-256")
        if _sha256_file(path) != expected_sha256:
            raise ContractError(f"file content drift: {path}")


def _validate_registration_payload(
    payload: Any,
    expected_source_sha: str,
) -> Mapping[str, str]:
    if not isinstance(payload, dict) or set(payload) != REGISTRATION_FIELDS:
        raise ContractError("unexpected registration fields")
    if payload["schema"] != REGISTRATION_SCHEMA:
        raise ContractError("registration schema mismatch")
    if payload["capability"] != CAPABILITY:
        raise ContractError("registration capability mismatch")
    if payload["registered_source_sha"] != expected_source_sha:
        raise ContractError("requested SHA is not registered")
    helper_sha = payload["helper_sha256"]
    if not isinstance(helper_sha, str) or not SHA256_RE.fullmatch(helper_sha):
        raise ContractError("invalid helper SHA-256 identity")
    return payload


def _load_registration(expected_source_sha: str) -> Mapping[str, str]:
    _validate_secure_file(REGISTRATION_PATH, expected_mode=0o444)
    return _validate_registration_payload(
        _load_json_bytes(REGISTRATION_PATH.read_bytes()),
        expected_source_sha,
    )


def _validate_installed_provenance(registration: Mapping[str, str]) -> None:
    try:
        source_path = Path(__file__).resolve(strict=True)
    except FileNotFoundError as error:
        raise ContractError("helper source path is unavailable") from error
    if source_path != INSTALLED_HELPER_PATH:
        raise ContractError("helper must execute from the fixed installed path")
    _validate_secure_file(
        INSTALLED_HELPER_PATH,
        expected_mode=0o555,
        expected_sha256=registration["helper_sha256"],
    )


def _identity() -> tuple[int, str, set[str]]:
    uid = os.geteuid()
    try:
        user = pwd.getpwuid(uid).pw_name
    except KeyError:
        user = str(uid)

    gids = set(os.getgroups())
    gids.add(os.getegid())
    names: set[str] = set()
    for gid in gids:
        try:
            names.add(grp.getgrgid(gid).gr_name)
        except KeyError:
            names.add(f"gid:{gid}")
    return uid, user, names


def _validate_nonroot_boundary(uid: int, group_names: set[str]) -> None:
    if uid == 0:
        raise ContractError("root execution is forbidden")
    if "docker" in group_names:
        raise ContractError("Docker-group authority is forbidden")


def _mode(path: Path) -> str | None:
    try:
        return f"{stat.S_IMODE(path.stat().st_mode):o}"
    except OSError:
        return None


def _uid(path: Path) -> int | None:
    try:
        return path.stat().st_uid
    except OSError:
        return None


def _gid(path: Path) -> int | None:
    try:
        return path.stat().st_gid
    except OSError:
        return None


def _probe_fixed_paths(source_sha: str, runner_user: str, runner_uid: int) -> dict[str, Any]:
    source_sha = _canonical_source_sha(source_sha)
    n9_read = os.access(N9_PATH, os.R_OK)
    n9_sha_match = False
    if n9_read:
        try:
            n9_sha_match = _sha256_file(N9_PATH) == N9_SHA256
        except OSError:
            n9_sha_match = False

    corpus_read = os.access(CORPUS_ROOT, os.R_OK)
    corpus_exec = os.access(CORPUS_ROOT, os.X_OK)

    if not n9_read:
        blocked = "n9_manifest_unreadable"
    elif not n9_sha_match:
        blocked = "n9_manifest_identity_mismatch"
    elif not (corpus_read and corpus_exec):
        blocked = "corpus_root_unreadable"
    else:
        blocked = "campaign_identity_probe_required"

    result = {
        "schema": RESULT_SCHEMA,
        "schema_version": 2,
        "strategy": "netto_missing_normal_price_nonroot_access_preflight_v2",
        "capability": CAPABILITY,
        "registered_source_sha": source_sha,
        "runner_user": runner_user,
        "runner_uid": runner_uid,
        "n9_manifest_readable": n9_read,
        "n9_manifest_sha256_match": n9_sha_match,
        "corpus_root_readable": corpus_read,
        "corpus_root_executable": corpus_exec,
        "blocked_at": blocked,
        "non_root_ready": blocked == "none",
        "safe_permission_metadata": {
            "home_andris_mode": _mode(HOME_ANDRIS),
            "home_andris_uid": _uid(HOME_ANDRIS),
            "home_andris_gid": _gid(HOME_ANDRIS),
            "n9_parent_mode": _mode(N9_PATH.parent),
            "corpus_root_mode": _mode(CORPUS_ROOT),
        },
        "sudo_used": False,
        "file_contents_exported": False,
        "parser_executed": False,
        "database_write_performed": False,
        "review_write_performed": False,
        "deployment_performed": False,
    }
    return _validate_result_payload(result, source_sha)


def _validate_optional_mode(value: Any, *, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not re.fullmatch(r"[0-7]{3,4}", value):
        raise ContractError(f"unsafe permission metadata: {field}")


def _validate_optional_id(value: Any, *, field: str) -> None:
    if value is None:
        return
    if type(value) is not int or value < 0:
        raise ContractError(f"unsafe permission metadata: {field}")


def _validate_result_payload(payload: Any, expected_source_sha: str) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != RESULT_FIELDS:
        raise ContractError("unexpected evidence fields")
    if payload["schema"] != RESULT_SCHEMA or payload["schema_version"] != 2:
        raise ContractError("evidence schema mismatch")
    if payload["strategy"] != "netto_missing_normal_price_nonroot_access_preflight_v2":
        raise ContractError("evidence strategy mismatch")
    if payload["capability"] != CAPABILITY:
        raise ContractError("evidence capability mismatch")
    if payload["registered_source_sha"] != expected_source_sha:
        raise ContractError("evidence source identity mismatch")

    user = payload["runner_user"]
    if not isinstance(user, str) or not user or len(user) > 64:
        raise ContractError("unsafe runner user")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in user):
        raise ContractError("unsafe runner user")
    if type(payload["runner_uid"]) is not int or payload["runner_uid"] <= 0:
        raise ContractError("runner uid must be non-root")

    for field in (
        "n9_manifest_readable",
        "n9_manifest_sha256_match",
        "corpus_root_readable",
        "corpus_root_executable",
        "non_root_ready",
    ):
        if type(payload[field]) is not bool:
            raise ContractError(f"invalid evidence boolean: {field}")

    blocked = payload["blocked_at"]
    if blocked not in ALLOWED_BLOCKED_AT:
        raise ContractError("unexpected blocked_at value")
    if payload["non_root_ready"] is not False:
        raise ContractError("v2 preflight must remain blocked on campaign identity probe")

    metadata = payload["safe_permission_metadata"]
    if not isinstance(metadata, dict) or set(metadata) != PERMISSION_FIELDS:
        raise ContractError("unexpected permission metadata fields")
    for field in ("home_andris_mode", "n9_parent_mode", "corpus_root_mode"):
        _validate_optional_mode(metadata[field], field=field)
    for field in ("home_andris_uid", "home_andris_gid"):
        _validate_optional_id(metadata[field], field=field)

    for field in FALSE_POSTCONDITIONS:
        if payload[field] is not False:
            raise ContractError(f"mutation postcondition must remain false: {field}")
    return payload


def _canonical_result(payload: Mapping[str, Any], expected_source_sha: str) -> bytes:
    validated = _validate_result_payload(dict(payload), expected_source_sha)
    encoded = (json.dumps(validated, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    if len(encoded) > MAX_RESULT_BYTES:
        raise ContractError("bounded evidence exceeds 32 KiB")
    return encoded


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Runner-independent Netto non-root corpus preflight v2"
    )
    parser.add_argument("registered_sha")
    args = parser.parse_args(argv)
    args.registered_sha = _canonical_source_sha(args.registered_sha)
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    registration = _load_registration(args.registered_sha)
    _validate_installed_provenance(registration)
    uid, user, group_names = _identity()
    _validate_nonroot_boundary(uid, group_names)
    result = _probe_fixed_paths(args.registered_sha, user, uid)
    sys.stdout.buffer.write(_canonical_result(result, args.registered_sha))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ContractError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2)
