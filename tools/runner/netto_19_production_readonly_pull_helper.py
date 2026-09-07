#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys
from types import ModuleType
from typing import Any, Mapping, Sequence

CAPABILITY = "netto-19-production-readonly-verify"
REGISTRATION_SCHEMA = "rozkalns.hermes-deals.netto-19-production-readonly-pull-registration.v1"
EVIDENCE_SCHEMA = "rozkalns.hermes-deals.netto-19-production-readonly-pull-evidence.v1"
MACHINE_ID = "rpi5"
REGISTRATION_PATH = Path(
    "/etc/hermes-deals-audits.d/netto-19-production-readonly-pull.json"
)
INSTALLED_HELPER_PATH = Path(
    "/usr/local/sbin/hermes-deals-netto-19-production-readonly-pull-dispatch"
)
VERIFIER_PATH = Path(
    "/usr/local/libexec/hermes-deals-audits/netto-19-production-readonly-v1/"
    "netto_19_production_readonly_verify.py"
)
EVIDENCE_ROOT = Path(
    "/var/lib/hermes-deals-audits/netto-19-production-readonly-v1/evidence"
)
MACHINE_ROOT = EVIDENCE_ROOT / MACHINE_ID
MAX_JSON_BYTES = 2 * 1024 * 1024
SOURCE_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
RUN_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{12}Z$")
REGISTRATION_FIELDS = {
    "schema",
    "capability",
    "registered_source_sha",
    "helper_sha256",
    "verifier_sha256",
}
RECEIPT_FIELDS = {
    "schema_version",
    "result",
    "registered_sha",
    "production_revision",
    "production_image_ref",
    "production_image_id",
    "runtime_version",
    "runtime_phase",
    "alembic_revision",
    "required_fix_commits_present",
    "daily_contract",
    "weekly_contract",
    "daily_ui_count_contract",
    "daily_ui_asset_mode",
    "weekly_ui_count_contract",
    "review_only_policy",
    "covered_probe_count",
    "latest_covered_probe_date",
    "latest_covered_snapshot_id",
    "latest_covered_snapshot_sha256",
    "latest_covered_netto_count",
    "latest_daily_ui_netto_count",
    "historical_covered_probe_present",
    "covered_probes",
    "outside_window_probe_date",
    "outside_window_netto_count",
    "database_payload_unchanged",
    "production_git_unchanged",
    "rollback_target",
    "production_mutated",
    "database_write_performed",
    "review_write_performed",
    "publication_performed",
    "deployment_performed",
    "scheduler_change_performed",
    "host_root_change_performed",
}
PROBE_FIELDS = {
    "date",
    "snapshot_id",
    "snapshot_sha256",
    "daily_netto_count",
    "daily_ui_high_confidence_netto_count",
    "weekly_high_confidence_netto_count",
    "weekly_ui_netto_count",
}
ROLLBACK_FIELDS = {
    "kind",
    "image_ref",
    "image_id",
    "revision",
    "command_required",
    "reason",
}
FALSE_POSTCONDITIONS = (
    "production_mutated",
    "database_write_performed",
    "review_write_performed",
    "publication_performed",
    "deployment_performed",
    "scheduler_change_performed",
    "host_root_change_performed",
)


class ContractError(RuntimeError):
    pass


def _canonical_source_sha(value: str) -> str:
    if not SOURCE_SHA_RE.fullmatch(value):
        raise ContractError("invalid registered source SHA")
    return value


def _canonical_run_id(value: str) -> str:
    if not RUN_ID_RE.fullmatch(value):
        raise ContractError("invalid internally derived run id")
    try:
        parsed = datetime.strptime(value, "%Y%m%dT%H%M%S%fZ").replace(tzinfo=timezone.utc)
    except ValueError as error:
        raise ContractError("invalid internally derived run id") from error
    if parsed.strftime("%Y%m%dT%H%M%S%fZ") != value:
        raise ContractError("run id is not canonical")
    return value


def _new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


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
    if len(raw) > MAX_JSON_BYTES:
        raise ContractError("JSON input exceeds 2 MiB")
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
    for field in ("helper_sha256", "verifier_sha256"):
        value = payload[field]
        if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
            raise ContractError(f"invalid registration identity: {field}")
    return payload


def _load_registration(expected_source_sha: str) -> Mapping[str, str]:
    _validate_secure_file(REGISTRATION_PATH, expected_mode=0o600)
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
        expected_mode=0o755,
        expected_sha256=registration["helper_sha256"],
    )
    _validate_secure_file(
        VERIFIER_PATH,
        expected_mode=0o555,
        expected_sha256=registration["verifier_sha256"],
    )


def _load_verifier_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "_hermes_netto_19_production_readonly_verify",
        VERIFIER_PATH,
    )
    if spec is None or spec.loader is None:
        raise ContractError("fixed verifier module is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as error:
        sys.modules.pop(spec.name, None)
        raise ContractError("fixed verifier module failed to load") from error
    return module


def _safe_string(value: Any, *, field: str, max_length: int = 256) -> str:
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise ContractError(f"unsafe receipt value: {field}")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise ContractError(f"unsafe receipt value: {field}")
    return value


def _safe_optional_string(
    value: Any,
    *,
    field: str,
    max_length: int = 256,
) -> str | None:
    if value is None:
        return None
    return _safe_string(value, field=field, max_length=max_length)


def _nonnegative_int(value: Any, *, field: str, maximum: int = 10_000_000) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise ContractError(f"unsafe receipt count: {field}")
    return value


def _canonical_date(value: Any, *, field: str) -> str:
    text = _safe_string(value, field=field, max_length=10)
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d")
    except ValueError as error:
        raise ContractError(f"invalid receipt date: {field}") from error
    if parsed.strftime("%Y-%m-%d") != text:
        raise ContractError(f"invalid receipt date: {field}")
    return text


def _validate_probe_row(item: Any) -> None:
    if not isinstance(item, dict) or set(item) != PROBE_FIELDS:
        raise ContractError("unexpected covered probe fields")
    _canonical_date(item["date"], field="covered_probes.date")
    _safe_string(item["snapshot_id"], field="covered_probes.snapshot_id", max_length=128)
    snapshot_sha = item["snapshot_sha256"]
    if not isinstance(snapshot_sha, str) or not SHA256_RE.fullmatch(snapshot_sha):
        raise ContractError("invalid covered probe snapshot SHA")
    for field in (
        "daily_netto_count",
        "daily_ui_high_confidence_netto_count",
        "weekly_high_confidence_netto_count",
        "weekly_ui_netto_count",
    ):
        _nonnegative_int(item[field], field=f"covered_probes.{field}")


def _validate_receipt_payload(
    payload: Any,
    expected_source_sha: str,
) -> Mapping[str, Any]:
    if not isinstance(payload, dict) or set(payload) != RECEIPT_FIELDS:
        raise ContractError("unexpected verifier receipt fields")
    if payload["schema_version"] != 1 or payload["result"] != "PASS":
        raise ContractError("verifier receipt did not pass")
    if payload["registered_sha"] != expected_source_sha:
        raise ContractError("verifier receipt source identity mismatch")

    production_revision = payload["production_revision"]
    if not isinstance(production_revision, str) or not SOURCE_SHA_RE.fullmatch(
        production_revision
    ):
        raise ContractError("invalid production revision")
    image_ref = _safe_string(
        payload["production_image_ref"],
        field="production_image_ref",
    )
    if not image_ref.startswith("hermes-deals-api:"):
        raise ContractError("unexpected production image reference")
    image_id = payload["production_image_id"]
    if not isinstance(image_id, str) or not IMAGE_ID_RE.fullmatch(image_id):
        raise ContractError("invalid production image identity")

    _safe_optional_string(payload["runtime_version"], field="runtime_version", max_length=128)
    _safe_optional_string(payload["runtime_phase"], field="runtime_phase", max_length=128)
    _safe_string(payload["alembic_revision"], field="alembic_revision", max_length=128)

    for field in (
        "required_fix_commits_present",
        "historical_covered_probe_present",
        "database_payload_unchanged",
        "production_git_unchanged",
    ):
        if payload[field] is not True:
            raise ContractError(f"required read-only verifier postcondition failed: {field}")
    for field in (
        "daily_contract",
        "weekly_contract",
        "daily_ui_count_contract",
        "weekly_ui_count_contract",
        "review_only_policy",
    ):
        if payload[field] != "PASS":
            raise ContractError(f"required verifier contract failed: {field}")
    _safe_string(
        payload["daily_ui_asset_mode"],
        field="daily_ui_asset_mode",
        max_length=256,
    )

    covered_probe_count = _nonnegative_int(
        payload["covered_probe_count"],
        field="covered_probe_count",
        maximum=64,
    )
    if covered_probe_count < 2:
        raise ContractError("current and historical covered probes are both required")
    probes = payload["covered_probes"]
    if not isinstance(probes, list) or len(probes) != covered_probe_count:
        raise ContractError("covered probe count mismatch")
    for item in probes:
        _validate_probe_row(item)

    _canonical_date(payload["latest_covered_probe_date"], field="latest_covered_probe_date")
    _safe_string(
        payload["latest_covered_snapshot_id"],
        field="latest_covered_snapshot_id",
        max_length=128,
    )
    snapshot_sha = payload["latest_covered_snapshot_sha256"]
    if not isinstance(snapshot_sha, str) or not SHA256_RE.fullmatch(snapshot_sha):
        raise ContractError("invalid latest covered snapshot SHA")
    _nonnegative_int(payload["latest_covered_netto_count"], field="latest_covered_netto_count")
    _nonnegative_int(
        payload["latest_daily_ui_netto_count"],
        field="latest_daily_ui_netto_count",
    )
    first_probe = probes[0]
    if (
        first_probe["date"] != payload["latest_covered_probe_date"]
        or first_probe["snapshot_id"] != payload["latest_covered_snapshot_id"]
        or first_probe["snapshot_sha256"] != payload["latest_covered_snapshot_sha256"]
        or first_probe["daily_netto_count"] != payload["latest_covered_netto_count"]
        or first_probe["daily_ui_high_confidence_netto_count"]
        != payload["latest_daily_ui_netto_count"]
    ):
        raise ContractError("latest covered probe summary mismatch")
    _canonical_date(payload["outside_window_probe_date"], field="outside_window_probe_date")
    if payload["outside_window_netto_count"] != 0:
        raise ContractError("outside-window verifier contract failed")

    rollback = payload["rollback_target"]
    if not isinstance(rollback, dict) or set(rollback) != ROLLBACK_FIELDS:
        raise ContractError("unexpected rollback target fields")
    if rollback["kind"] != "current_running_image":
        raise ContractError("unexpected rollback target kind")
    if rollback["image_ref"] != image_ref or rollback["image_id"] != image_id:
        raise ContractError("rollback image identity mismatch")
    if rollback["revision"] != production_revision:
        raise ContractError("rollback revision mismatch")
    if rollback["command_required"] is not False:
        raise ContractError("read-only verifier unexpectedly requires rollback command")
    if rollback["reason"] != "read-only verifier performs no deployment":
        raise ContractError("unexpected rollback reason")

    for field in FALSE_POSTCONDITIONS:
        if payload[field] is not False:
            raise ContractError(f"mutation postcondition violated: {field}")
    return payload


def _canonicalize_receipt(
    payload: Mapping[str, Any],
    expected_source_sha: str,
) -> bytes:
    validated = _validate_receipt_payload(payload, expected_source_sha)
    return (
        json.dumps(validated, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def _collect_receipt(verifier: ModuleType, source_sha: str) -> dict[str, Any]:
    try:
        if os.geteuid() != 0:
            raise ContractError("helper must run as root through the future capability broker")
        if not verifier.PRIMARY.is_dir() or verifier.PRIMARY.is_symlink():
            raise ContractError("production root missing")
        if not (verifier.PRIMARY / ".env").is_file():
            raise ContractError("production env missing")

        production_git_head = verifier.owner_git("rev-parse", "HEAD")
        production_git_status = verifier.owner_git(
            "status", "--porcelain=v1", "--untracked-files=all"
        )

        api = verifier.compose("ps", "-q", "api")
        db = verifier.compose("ps", "-q", "db")
        web = verifier.compose("ps", "-q", "web")
        verifier.require(bool(api and db and web), "production containers are not all running")

        api_row = verifier.docker_inspect(api)
        image_ref = str(api_row.get("Config", {}).get("Image") or "")
        image_id = str(api_row.get("Image") or "")
        labels = api_row.get("Config", {}).get("Labels") or {}
        production_revision = str(labels.get("org.opencontainers.image.revision") or "")
        verifier.require(
            image_ref.startswith("hermes-deals-api:"),
            "unexpected production image reference",
        )
        verifier.require(
            image_id.startswith("sha256:"),
            "unexpected production image id",
        )
        verifier.require(
            verifier.SHA40_RE.fullmatch(production_revision) is not None,
            "production revision missing",
        )
        verifier.owner_git("cat-file", "-e", f"{production_revision}^{{commit}}")
        for required in verifier.REQUIRED_FIX_COMMITS:
            verifier.owner_git("merge-base", "--is-ancestor", required, production_revision)

        verifier.validate_review_only_policy(production_revision)
        verifier.require(
            verifier.psql(db, "SHOW default_transaction_read_only;") == "on",
            "database read-only session enforcement missing",
        )

        alembic_before = verifier.psql(db, "SELECT version_num FROM alembic_version;")
        verifier.require(bool(alembic_before), "Alembic revision unavailable")
        db_before = {
            "source_snapshots": verifier.table_digest(
                db, "source_snapshots", "source_chain='netto'"
            ),
            "offer_candidates": verifier.table_digest(
                db, "offer_candidates", "source_chain='netto'"
            ),
            "offer_review_items": verifier.table_digest(db, "offer_review_items"),
            "offer_review_revisions": verifier.table_digest(db, "offer_review_revisions"),
        }

        health = verifier.http_json("/api/health")
        verifier.require(health.get("status") == "ok", "health status not ok")
        verifier.require(
            health.get("service") == "hermes-deals-api",
            "health service mismatch",
        )
        verifier.require(verifier.http_status("/ui") == 200, "UI status not 200")
        verifier.require(
            verifier.http_status("/ui/review") in {200, 302},
            "Review UI status unexpected",
        )
        daily_ui_asset_mode = verifier.validate_daily_ui_contract(production_revision)

        snapshots = verifier.parse_snapshot_rows(db)
        probes = verifier.find_covered_probes(snapshots)
        weekly_counts: list[int] = []
        weekly_ui_counts: list[int] = []
        for day, _, netto in probes:
            weekly_count, weekly_ui_count = verifier.validate_weekly_probe(day, netto)
            weekly_counts.append(weekly_count)
            weekly_ui_counts.append(weekly_ui_count)
        latest_day, latest_snapshot, latest_netto = probes[0]

        outside_day = max(snapshot.valid_until for snapshot in snapshots) + timedelta(days=7)
        outside_payload = verifier.http_json(
            f"/api/v1/deals/daily-specials?as_of={outside_day.isoformat()}"
        )
        verifier.validate_daily_payload(
            outside_payload,
            day=outside_day,
            selected=None,
        )

        alembic_after = verifier.psql(db, "SELECT version_num FROM alembic_version;")
        db_after = {
            "source_snapshots": verifier.table_digest(
                db, "source_snapshots", "source_chain='netto'"
            ),
            "offer_candidates": verifier.table_digest(
                db, "offer_candidates", "source_chain='netto'"
            ),
            "offer_review_items": verifier.table_digest(db, "offer_review_items"),
            "offer_review_revisions": verifier.table_digest(db, "offer_review_revisions"),
        }
        verifier.require(
            alembic_after == alembic_before,
            "Alembic revision changed during verifier",
        )
        verifier.require(db_after == db_before, "database payload changed during verifier")
        verifier.require(
            verifier.owner_git("rev-parse", "HEAD") == production_git_head,
            "production Git HEAD changed",
        )
        verifier.require(
            verifier.owner_git(
                "status", "--porcelain=v1", "--untracked-files=all"
            )
            == production_git_status,
            "production Git status changed",
        )

        return {
            "schema_version": 1,
            "result": "PASS",
            "registered_sha": source_sha,
            "production_revision": production_revision,
            "production_image_ref": image_ref,
            "production_image_id": image_id,
            "runtime_version": health.get("version"),
            "runtime_phase": health.get("phase"),
            "alembic_revision": alembic_after,
            "required_fix_commits_present": True,
            "daily_contract": "PASS",
            "weekly_contract": "PASS",
            "daily_ui_count_contract": "PASS",
            "daily_ui_asset_mode": daily_ui_asset_mode,
            "weekly_ui_count_contract": "PASS",
            "review_only_policy": "PASS",
            "covered_probe_count": len(probes),
            "latest_covered_probe_date": latest_day.isoformat(),
            "latest_covered_snapshot_id": latest_snapshot.id,
            "latest_covered_snapshot_sha256": latest_snapshot.sha256,
            "latest_covered_netto_count": len(latest_netto),
            "latest_daily_ui_netto_count": len(
                verifier.daily_ui_high_confidence_ids(latest_day, latest_netto)
            ),
            "historical_covered_probe_present": True,
            "covered_probes": [
                {
                    "date": day.isoformat(),
                    "snapshot_id": snapshot.id,
                    "snapshot_sha256": snapshot.sha256,
                    "daily_netto_count": len(netto),
                    "daily_ui_high_confidence_netto_count": len(
                        verifier.daily_ui_high_confidence_ids(day, netto)
                    ),
                    "weekly_high_confidence_netto_count": weekly_count,
                    "weekly_ui_netto_count": weekly_ui_count,
                }
                for (day, snapshot, netto), weekly_count, weekly_ui_count in zip(
                    probes,
                    weekly_counts,
                    weekly_ui_counts,
                    strict=True,
                )
            ],
            "outside_window_probe_date": outside_day.isoformat(),
            "outside_window_netto_count": 0,
            "database_payload_unchanged": True,
            "production_git_unchanged": True,
            "rollback_target": {
                "kind": "current_running_image",
                "image_ref": image_ref,
                "image_id": image_id,
                "revision": production_revision,
                "command_required": False,
                "reason": "read-only verifier performs no deployment",
            },
            "production_mutated": False,
            "database_write_performed": False,
            "review_write_performed": False,
            "publication_performed": False,
            "deployment_performed": False,
            "scheduler_change_performed": False,
            "host_root_change_performed": False,
        }
    except ContractError:
        raise
    except Exception as error:
        raise ContractError("fixed Netto #19 read-only verifier failed") from error


def _destination_for(
    source_sha: str,
    run_id: str,
    *,
    machine_root: Path = MACHINE_ROOT,
) -> Path:
    source_sha = _canonical_source_sha(source_sha)
    run_id = _canonical_run_id(run_id)
    destination = machine_root / f"{source_sha}-{run_id}"
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
    run_id: str,
    canonical_receipt: bytes,
    registration: Mapping[str, str],
) -> bytes:
    payload = {
        "schema": EVIDENCE_SCHEMA,
        "capability": CAPABILITY,
        "machine_id": MACHINE_ID,
        "registered_source_sha": source_sha,
        "run_id": run_id,
        "receipt_sha256": hashlib.sha256(canonical_receipt).hexdigest(),
        "helper_sha256": registration["helper_sha256"],
        "verifier_sha256": registration["verifier_sha256"],
        "sanitization_passed": True,
        "protected_values_included": False,
        "production_mutated": False,
        "database_write_performed": False,
        "review_write_performed": False,
        "publication_performed": False,
        "deployment_performed": False,
        "scheduler_change_performed": False,
        "host_root_change_performed": False,
    }
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _persist_evidence(
    destination: Path,
    *,
    receipt: bytes,
    manifest: bytes,
) -> None:
    _require_destination_absent(destination)
    os.mkdir(destination, mode=0o700)
    _write_exclusive(destination / "receipt.json", receipt)
    _write_exclusive(destination / "dispatcher-manifest.json", manifest)
    _write_exclusive(destination / "verify-exit-code.txt", b"0\n")


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the fixed runner-independent Netto #19 production read-only "
            "verification capability."
        )
    )
    parser.add_argument("registered_sha")
    args = parser.parse_args(argv)
    args.registered_sha = _canonical_source_sha(args.registered_sha)
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if os.geteuid() != 0:
        raise ContractError("helper must run as root through the future capability broker")

    registration = _load_registration(args.registered_sha)
    _validate_installed_provenance(registration)
    _validate_evidence_parent()
    run_id = _new_run_id()
    destination = _destination_for(args.registered_sha, run_id)
    _require_destination_absent(destination)

    verifier = _load_verifier_module()
    receipt = _collect_receipt(verifier, args.registered_sha)
    canonical_receipt = _canonicalize_receipt(receipt, args.registered_sha)
    manifest = _manifest(
        source_sha=args.registered_sha,
        run_id=run_id,
        canonical_receipt=canonical_receipt,
        registration=registration,
    )
    _persist_evidence(
        destination,
        receipt=canonical_receipt,
        manifest=manifest,
    )

    print(
        f"CAPABILITY={CAPABILITY} SOURCE_SHA={args.registered_sha} "
        f"RUN_ID={run_id} RESULT=PASS"
    )
    for field in FALSE_POSTCONDITIONS:
        print(f"{field.upper()}=false")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ContractError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(78)
