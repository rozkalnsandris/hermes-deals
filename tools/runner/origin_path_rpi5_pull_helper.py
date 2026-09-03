#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlencode

CAPABILITY = "origin-path-audit"
REGISTRATION_SCHEMA = "rozkalns.hermes-deals.origin-path-rpi5-pull-registration.v1"
EVIDENCE_SCHEMA = "rozkalns.hermes-deals.origin-path-rpi5-pull-evidence.v1"
MACHINE_ID = "rpi5"
REGISTRATION_PATH = Path("/etc/hermes-deals-audits.d/origin-path-rpi5-pull.json")
INSTALLED_HELPER_PATH = Path("/usr/local/sbin/hermes-deals-origin-path-rpi5-pull-dispatch")
PROBE_PATH = Path("/usr/local/libexec/hermes-deals-audits/origin-path-probe.py")
EVIDENCE_ROOT = Path("/var/lib/hermes-deals-audits/origin-path-audit/evidence")
MACHINE_ROOT = EVIDENCE_ROOT / MACHINE_ID
RUNUSER_PATH = Path("/usr/sbin/runuser")
PYTHON_PATH = Path("/usr/bin/python3")
ENV_PATH = Path("/usr/bin/env")
AUDIT_USER = "andris"
PUBLIC_BASE_URL = "https://deals.rozkalns.net"
ORIGIN_BASE_URL = "http://192.168.0.180:9128"
ORIGIN_HOST = "deals.rozkalns.net"
TIMEOUT_SECONDS = 5
PROCESS_TIMEOUT_SECONDS = 45
MAX_REPORT_BYTES = 1024 * 1024
SOURCE_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_CLASSIFICATIONS = {
    "healthy": ("ok", 0),
    "edge_or_tunnel_failure": ("failed", 2),
    "public_path_failure": ("degraded", 1),
    "origin_or_application_failure": ("failed", 2),
    "local_origin_probe_failure": ("degraded", 1),
    "mixed_failure": ("degraded", 1),
}
ALLOWED_HEADERS = {
    "cf-ray",
    "retry-after",
    "server",
    "content-type",
    "cf-cache-status",
}
ALLOWED_PROBLEM_FIELDS = {
    "status",
    "error_code",
    "error_name",
    "ray_id",
    "retryable",
    "retry_after",
}
ALLOWED_TRANSPORT_ERRORS = {None, "timeout", "connection_error", "transport_error"}
REPORT_FIELDS = {
    "schema_version",
    "captured_at",
    "as_of",
    "classification",
    "severity",
    "probes",
}
PROBE_FIELDS = {
    "target",
    "endpoint",
    "url",
    "ok",
    "status",
    "elapsed_ms",
    "transport_error",
    "headers",
    "problem",
}
REGISTRATION_FIELDS = {
    "schema",
    "capability",
    "registered_source_sha",
    "helper_sha256",
    "probe_sha256",
}
ROOT_SUBPROCESS_ENV = {
    "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
    "LANG": "C.UTF-8",
}


class ContractError(RuntimeError):
    pass


def _canonical_source_sha(value: str) -> str:
    if not SOURCE_SHA_RE.fullmatch(value):
        raise ContractError("invalid registered source SHA")
    return value


def _canonical_as_of(value: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ContractError("invalid as_of date") from error
    if parsed.isoformat() != value:
        raise ContractError("as_of must use canonical YYYY-MM-DD format")
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
    if len(raw) > MAX_REPORT_BYTES:
        raise ContractError("JSON input exceeds 1 MiB")
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContractError("invalid JSON") from error


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
    expected_sha256: str | None = None,
    expected_uid: int = 0,
    expected_gid: int = 0,
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
            raise ContractError("invalid registered SHA-256 identity")
        if _sha256_file(path) != expected_sha256:
            raise ContractError(f"file content drift: {path}")


def _validate_secure_directory(
    path: Path,
    *,
    expected_mode: int = 0o700,
    expected_uid: int = 0,
    expected_gid: int = 0,
) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise ContractError(f"required directory is missing: {path}") from error
    if not stat.S_ISDIR(metadata.st_mode):
        raise ContractError(f"required path is not a directory: {path}")
    if metadata.st_uid != expected_uid or metadata.st_gid != expected_gid:
        raise ContractError(f"directory ownership mismatch: {path}")
    if stat.S_IMODE(metadata.st_mode) != expected_mode:
        raise ContractError(f"directory mode mismatch: {path}")


def _validate_registration_payload(payload: Any, expected_source_sha: str) -> Mapping[str, str]:
    if not isinstance(payload, dict) or set(payload) != REGISTRATION_FIELDS:
        raise ContractError("unexpected registration fields")
    if payload["schema"] != REGISTRATION_SCHEMA:
        raise ContractError("registration schema mismatch")
    if payload["capability"] != CAPABILITY:
        raise ContractError("registration capability mismatch")
    if payload["registered_source_sha"] != expected_source_sha:
        raise ContractError("requested SHA is not registered")
    for field in ("helper_sha256", "probe_sha256"):
        value = payload[field]
        if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
            raise ContractError(f"invalid registration identity: {field}")
    return payload


def _load_registration(expected_source_sha: str) -> Mapping[str, str]:
    _validate_secure_file(REGISTRATION_PATH, expected_mode=0o600)
    payload = _load_json_bytes(REGISTRATION_PATH.read_bytes())
    return _validate_registration_payload(payload, expected_source_sha)


def _validate_installed_provenance(registration: Mapping[str, str]) -> None:
    try:
        source_path = Path(__file__).resolve(strict=True)
    except FileNotFoundError as error:
        raise ContractError("helper source path is unavailable") from error
    if source_path != INSTALLED_HELPER_PATH:
        raise ContractError("helper must execute from the fixed installed path")
    _validate_secure_file(
        INSTALLED_HELPER_PATH,
        expected_mode=0o755,
        expected_sha256=registration["helper_sha256"],
    )
    _validate_secure_file(
        PROBE_PATH,
        expected_mode=0o755,
        expected_sha256=registration["probe_sha256"],
    )


def _expected_urls(as_of: str) -> dict[tuple[str, str], str]:
    overview = "/api/v1/ui/overview?" + urlencode({"as_of": as_of})
    deals = "/api/v1/deals/current?" + urlencode(
        {"as_of": as_of, "view": "current", "limit": "1", "offset": "0"}
    )
    endpoints = {
        "health": "/api/health",
        "overview": overview,
        "deals": deals,
    }
    result: dict[tuple[str, str], str] = {}
    for endpoint, suffix in endpoints.items():
        result[("public", endpoint)] = PUBLIC_BASE_URL + suffix
        result[("origin", endpoint)] = ORIGIN_BASE_URL + suffix
    return result


def _validate_problem_value(value: Any) -> None:
    if type(value) not in (str, int, float, bool):
        raise ContractError("unexpected problem value type")
    if isinstance(value, str) and (len(value) > 256 or "\r" in value or "\n" in value):
        raise ContractError("unsafe problem value entered report")
    if isinstance(value, float) and not math.isfinite(value):
        raise ContractError("non-finite problem value entered report")


def _validate_and_canonicalize_report(
    raw: bytes,
    as_of: str,
    probe_rc: int,
) -> tuple[dict[str, Any], bytes]:
    report = _load_json_bytes(raw)
    if not isinstance(report, dict) or set(report) != REPORT_FIELDS:
        raise ContractError("unexpected probe report fields")
    if report["schema_version"] != "1" or report["as_of"] != as_of:
        raise ContractError("probe report identity mismatch")
    captured_at = report["captured_at"]
    if not isinstance(captured_at, str) or len(captured_at) > 64:
        raise ContractError("captured_at is invalid")
    try:
        datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise ContractError("captured_at is invalid") from error
    classification = report["classification"]
    if not isinstance(classification, str) or classification not in ALLOWED_CLASSIFICATIONS:
        raise ContractError("unexpected classification")
    expected_severity, expected_rc = ALLOWED_CLASSIFICATIONS[classification]
    if report["severity"] != expected_severity or probe_rc != expected_rc:
        raise ContractError("classification, severity and exit code disagree")
    probes = report["probes"]
    if not isinstance(probes, list) or len(probes) != 6:
        raise ContractError("expected exactly six probes")
    expected_urls = _expected_urls(as_of)
    seen: set[tuple[str, str]] = set()
    for item in probes:
        if not isinstance(item, dict) or set(item) != PROBE_FIELDS:
            raise ContractError("unexpected probe fields")
        target = item["target"]
        endpoint = item["endpoint"]
        if not isinstance(target, str) or not isinstance(endpoint, str):
            raise ContractError("probe target/endpoint coverage mismatch")
        pair = (target, endpoint)
        if pair not in expected_urls or pair in seen:
            raise ContractError("probe target/endpoint coverage mismatch")
        seen.add(pair)
        if item["url"] != expected_urls[pair]:
            raise ContractError("probe URL escaped fixed allowlist")
        if type(item["ok"]) is not bool:
            raise ContractError("probe ok flag is invalid")
        if item["status"] is not None and (
            type(item["status"]) is not int or not 100 <= item["status"] <= 599
        ):
            raise ContractError("probe status is invalid")
        if type(item["elapsed_ms"]) is not int or not 0 <= item["elapsed_ms"] <= 60000:
            raise ContractError("probe elapsed time is invalid")
        transport_error = item["transport_error"]
        if transport_error is not None and not isinstance(transport_error, str):
            raise ContractError("unexpected transport error")
        if transport_error not in ALLOWED_TRANSPORT_ERRORS:
            raise ContractError("unexpected transport error")
        headers = item["headers"]
        if not isinstance(headers, dict) or not set(headers).issubset(ALLOWED_HEADERS):
            raise ContractError("unsafe response header entered report")
        for key, value in headers.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ContractError("unsafe response header entered report")
            if len(value) > 512 or "\r" in value or "\n" in value:
                raise ContractError("unsafe response header value entered report")
        problem = item["problem"]
        if not isinstance(problem, dict) or not set(problem).issubset(ALLOWED_PROBLEM_FIELDS):
            raise ContractError("unsafe problem field entered report")
        for value in problem.values():
            _validate_problem_value(value)
    if seen != set(expected_urls):
        raise ContractError("probe target/endpoint coverage mismatch")
    canonical = (
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    return report, canonical


def _probe_argv(as_of: str) -> tuple[str, ...]:
    return (
        str(RUNUSER_PATH),
        "-u",
        AUDIT_USER,
        "--",
        str(ENV_PATH),
        "-i",
        "HOME=/home/andris",
        "USER=andris",
        "LOGNAME=andris",
        "SHELL=/bin/bash",
        "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG=C.UTF-8",
        str(PYTHON_PATH),
        str(PROBE_PATH),
        "--public-base-url",
        PUBLIC_BASE_URL,
        "--origin-base-url",
        ORIGIN_BASE_URL,
        "--origin-host",
        ORIGIN_HOST,
        "--as-of",
        as_of,
        "--timeout",
        str(TIMEOUT_SECONDS),
    )


def _run_probe(as_of: str) -> tuple[int, bytes]:
    try:
        completed = subprocess.run(
            _probe_argv(as_of),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=ROOT_SUBPROCESS_ENV,
            timeout=PROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise ContractError("fixed probe process timed out") from error
    except OSError as error:
        raise ContractError("fixed probe process could not start") from error
    if completed.returncode not in {0, 1, 2}:
        raise ContractError("fixed probe returned an unexpected exit code")
    if len(completed.stdout) > MAX_REPORT_BYTES:
        raise ContractError("probe report exceeds 1 MiB")
    return completed.returncode, completed.stdout


def _destination_for(source_sha: str, as_of: str, *, machine_root: Path = MACHINE_ROOT) -> Path:
    source_sha = _canonical_source_sha(source_sha)
    as_of = _canonical_as_of(as_of)
    destination = machine_root / f"{source_sha}-{as_of}"
    if destination.parent != machine_root:
        raise ContractError("derived evidence destination escaped machine root")
    return destination


def _validate_evidence_parent(
    *,
    evidence_root: Path = EVIDENCE_ROOT,
    machine_root: Path = MACHINE_ROOT,
    expected_uid: int = 0,
    expected_gid: int = 0,
) -> None:
    if machine_root.parent != evidence_root or machine_root.name != MACHINE_ID:
        raise ContractError("machine evidence root is not source-fixed")
    _validate_secure_directory(
        evidence_root,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    _validate_secure_directory(
        machine_root,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )


def _require_destination_absent(destination: Path) -> None:
    if os.path.lexists(destination):
        raise ContractError("evidence destination already exists")


def _write_exclusive(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


def _manifest(
    *,
    source_sha: str,
    as_of: str,
    probe_rc: int,
    report: Mapping[str, Any],
    canonical_report: bytes,
    registration: Mapping[str, str],
) -> bytes:
    payload = {
        "schema": EVIDENCE_SCHEMA,
        "capability": CAPABILITY,
        "machine_id": MACHINE_ID,
        "registered_source_sha": source_sha,
        "as_of": as_of,
        "probe_exit_code": probe_rc,
        "classification": report["classification"],
        "severity": report["severity"],
        "probe_report_sha256": hashlib.sha256(canonical_report).hexdigest(),
        "helper_sha256": registration["helper_sha256"],
        "probe_sha256": registration["probe_sha256"],
        "sanitization_passed": True,
        "protected_values_included": False,
        "production_apply_authorized": False,
        "production_database_write": False,
        "production_deployment": False,
        "restart_or_configuration_mutation": False,
    }
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _persist_evidence(
    destination: Path,
    *,
    report: bytes,
    manifest: bytes,
    probe_rc: int,
) -> None:
    _require_destination_absent(destination)
    os.mkdir(destination, mode=0o700)
    _write_exclusive(destination / "probe-report.json", report)
    _write_exclusive(destination / "dispatcher-manifest.json", manifest)
    _write_exclusive(destination / "audit-exit-code.txt", f"{probe_rc}\n".encode("ascii"))


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the fixed runner-independent Hermes Deals origin-path audit capability."
    )
    parser.add_argument("registered_sha")
    parser.add_argument("as_of")
    args = parser.parse_args(argv)
    args.registered_sha = _canonical_source_sha(args.registered_sha)
    args.as_of = _canonical_as_of(args.as_of)
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if os.geteuid() != 0:
        raise ContractError("helper must run as root through the future capability broker")
    registration = _load_registration(args.registered_sha)
    _validate_installed_provenance(registration)
    _validate_evidence_parent()
    destination = _destination_for(args.registered_sha, args.as_of)
    _require_destination_absent(destination)

    probe_rc, raw_report = _run_probe(args.as_of)
    report, canonical_report = _validate_and_canonicalize_report(
        raw_report,
        args.as_of,
        probe_rc,
    )
    manifest = _manifest(
        source_sha=args.registered_sha,
        as_of=args.as_of,
        probe_rc=probe_rc,
        report=report,
        canonical_report=canonical_report,
        registration=registration,
    )
    _persist_evidence(
        destination,
        report=canonical_report,
        manifest=manifest,
        probe_rc=probe_rc,
    )
    print(
        f"CAPABILITY={CAPABILITY} SOURCE_SHA={args.registered_sha} "
        f"AS_OF={args.as_of} PROBE_EXIT_CODE={probe_rc}"
    )
    print("PRODUCTION_DATABASE_WRITE=false")
    print("PRODUCTION_DEPLOYMENT=false")
    print("RESTART_OR_CONFIGURATION_MUTATION=false")
    return probe_rc


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ContractError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(78)
