#!/usr/bin/env python3
from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import re
from typing import Any, Mapping

ISSUE_NUMBER = 631
RESULT_SCHEMA_VERSION = 1
REQUEST_SCHEMA_VERSION_V1 = 1
REQUEST_SCHEMA_VERSION_V2 = 2
MODE = "ALDI_GATE_D4_BOUNDED_BACKUP_DISCOVERY"
GATE_D3_TOOL = Path(__file__).with_name("aldi_gate_d3_recovery_inventory.py")
EXPECTED_GATE_D3_SHA256 = "606976346177b3a6a2965c6aab536f249f2097c41e08e76f3704990fe0473cb8"
GATE_D3_STATE_ROOT = Path("/home/andris/.local/state/hermes-deals/aldi-perfect-shadow")
FORBIDDEN_BROAD_ROOTS = {
    Path("/"),
    Path("/home"),
    Path("/home/andris"),
}
INPUT_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
MAX_INPUTS = 8
DECISIONS = {
    "NO_CANDIDATE_IN_DESIGNATED_ROOTS",
    "READY_FOR_IRRECOVERABLE_DECISION",
    "PLAUSIBLE_RECOVERY_CANDIDATE_FOUND",
    "AMBIGUOUS_PLAUSIBLE_RECOVERY_CANDIDATES",
}


class GateD4Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise GateD4Error(message)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _load_d3_module():
    require(GATE_D3_TOOL.is_file() and not GATE_D3_TOOL.is_symlink(), "Gate D3 recovery inventory tool missing")
    actual_sha = sha256(GATE_D3_TOOL.read_bytes()).hexdigest()
    require(actual_sha == EXPECTED_GATE_D3_SHA256, "Gate D3 recovery inventory tool identity drift")
    spec = importlib.util.spec_from_file_location("aldi_gate_d3_recovery_inventory", GATE_D3_TOOL)
    require(spec is not None and spec.loader is not None, "cannot load Gate D3 recovery inventory tool")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    require(callable(getattr(module, "build_inventory", None)), "Gate D3 build_inventory unavailable")
    require(callable(getattr(module, "archive_inventory", None)), "Gate D3 archive_inventory unavailable")
    return module


def load_request(path: Path) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), "request missing or unsafe")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateD4Error("invalid request JSON") from exc
    require(isinstance(payload, dict), "request root must be an object")
    return payload


def _normalize_root(path_value: Any) -> Path:
    require(isinstance(path_value, str) and path_value.startswith("/"), "backup root must be absolute")
    path = Path(path_value)
    require(".." not in path.parts, "backup root must not contain parent traversal")
    require(not path.is_symlink(), "backup root missing or unsafe")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise GateD4Error("backup root missing") from exc
    require(resolved.is_dir() and not resolved.is_symlink(), "backup root missing or unsafe")
    require(resolved not in FORBIDDEN_BROAD_ROOTS, "backup root is too broad")
    require(resolved != GATE_D3_STATE_ROOT, "Gate D3 state root was already exhaustively covered")
    return resolved


def _normalize_exact_file(path_value: Any) -> Path:
    require(isinstance(path_value, str) and path_value.startswith("/"), "backup file must be absolute")
    path = Path(path_value)
    require(".." not in path.parts, "backup file must not contain parent traversal")
    require(not path.is_symlink(), "backup file missing or unsafe")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise GateD4Error("backup file missing") from exc
    require(resolved == path, "backup file path must not contain symlinks")
    require(resolved.is_file() and not resolved.is_symlink(), "backup file missing or unsafe")
    require(
        resolved.name.endswith(".tar.gz") or resolved.name.endswith(".tgz"),
        "backup file must be a supported archive",
    )
    require(
        resolved != GATE_D3_STATE_ROOT and GATE_D3_STATE_ROOT not in resolved.parents,
        "Gate D3 state root was already exhaustively covered",
    )
    return resolved


def _validate_input_id(raw_id: Any, seen_ids: set[str]) -> str:
    require(isinstance(raw_id, str) and INPUT_ID_RE.fullmatch(raw_id) is not None, "invalid backup input id")
    require(raw_id not in seen_ids, "duplicate backup input id")
    seen_ids.add(raw_id)
    return raw_id


def validate_request(
    payload: Mapping[str, Any],
) -> tuple[bool, list[tuple[str, Path]], list[tuple[str, Path]]]:
    schema_version = payload.get("schema_version")
    require(
        schema_version in {REQUEST_SCHEMA_VERSION_V1, REQUEST_SCHEMA_VERSION_V2},
        "unsupported request schema_version",
    )
    if schema_version == REQUEST_SCHEMA_VERSION_V1:
        require(
            set(payload) == {
                "schema_version",
                "issue_number",
                "authoritative_source_set_complete",
                "roots",
            },
            "request fields mismatch",
        )
        raw_files: list[Any] = []
    else:
        require(
            set(payload) == {
                "schema_version",
                "issue_number",
                "authoritative_source_set_complete",
                "roots",
                "files",
            },
            "request fields mismatch",
        )
        raw_files = payload.get("files")
        require(isinstance(raw_files, list), "files must be a list")

    require(payload.get("issue_number") == ISSUE_NUMBER, "request issue_number mismatch")
    complete = payload.get("authoritative_source_set_complete")
    require(isinstance(complete, bool), "authoritative_source_set_complete must be boolean")
    rows = payload.get("roots")
    require(isinstance(rows, list), "roots must be a list")
    if schema_version == REQUEST_SCHEMA_VERSION_V1:
        require(rows, "at least one explicit backup root is required")
    else:
        require(rows or raw_files, "at least one explicit backup input is required")
    require(len(rows) + len(raw_files) <= MAX_INPUTS, "too many backup inputs")

    roots: list[tuple[str, Path]] = []
    files: list[tuple[str, Path]] = []
    ids: set[str] = set()
    resolved_roots: set[Path] = set()
    resolved_files: set[Path] = set()

    for raw in rows:
        require(isinstance(raw, dict), "backup root entry must be an object")
        require(set(raw) == {"id", "path"}, "backup root entry fields mismatch")
        root_id = _validate_input_id(raw.get("id"), ids)
        root = _normalize_root(raw.get("path"))
        require(root not in resolved_roots, "duplicate backup root path")
        for _, existing in roots:
            require(
                root not in existing.parents and existing not in root.parents,
                "backup roots must not overlap",
            )
        resolved_roots.add(root)
        roots.append((root_id, root))

    for raw in raw_files:
        require(isinstance(raw, dict), "backup file entry must be an object")
        require(set(raw) == {"id", "path"}, "backup file entry fields mismatch")
        file_id = _validate_input_id(raw.get("id"), ids)
        exact_file = _normalize_exact_file(raw.get("path"))
        require(exact_file not in resolved_files, "duplicate backup file path")
        for _, root in roots:
            require(root not in exact_file.parents, "backup file must not be inside a designated root")
        resolved_files.add(exact_file)
        files.append((file_id, exact_file))

    roots.sort(key=lambda item: item[0])
    files.sort(key=lambda item: item[0])
    return complete, roots, files


def _contains_absolute_path(value: Any) -> bool:
    if isinstance(value, str):
        return value.startswith("/")
    if isinstance(value, Mapping):
        return any(_contains_absolute_path(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_absolute_path(item) for item in value)
    return False


def _sanitize_inventory(root_id: str, inventory: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "decision",
        "manifest_count",
        "directory_candidate_count",
        "archive_count",
        "complete_recovery_source_count",
        "distinct_complete_identity_count",
        "manifests",
        "directory_candidates",
        "archives",
        "complete_recovery_sources",
        "complete_identities",
    }
    require(required.issubset(inventory), "Gate D3 inventory schema drift")
    require(inventory.get("state_root") == ".", "Gate D3 inventory leaked unexpected state root")
    require(isinstance(inventory.get("complete_identities"), list), "Gate D3 complete identities invalid")
    sanitized = {
        "root_id": root_id,
        "gate_d3_decision": inventory["decision"],
        "manifest_count": inventory["manifest_count"],
        "directory_candidate_count": inventory["directory_candidate_count"],
        "archive_count": inventory["archive_count"],
        "complete_recovery_source_count": inventory["complete_recovery_source_count"],
        "distinct_complete_identity_count": inventory["distinct_complete_identity_count"],
        "manifests": inventory["manifests"],
        "directory_candidates": inventory["directory_candidates"],
        "archives": inventory["archives"],
        "complete_recovery_sources": inventory["complete_recovery_sources"],
        "complete_identities": sorted(set(inventory["complete_identities"])),
    }
    require(not _contains_absolute_path(sanitized), "Gate D3 inventory contains absolute path")
    return sanitized


def _sanitize_exact_archive(file_id: str, archive: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "path",
        "sha256",
        "is_a21_archive",
        "safe",
        "unsafe_reason",
        "manifest_member_count",
        "complete_49_plus_41_count",
        "complete_identities",
    }
    require(required.issubset(archive), "Gate D3 archive inventory schema drift")
    relative_path = archive.get("path")
    require(
        isinstance(relative_path, str)
        and relative_path not in {"", ".", ".."}
        and not relative_path.startswith("/")
        and "/" not in relative_path,
        "Gate D3 exact archive path invalid",
    )
    digest = archive.get("sha256")
    require(
        digest is None or (isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest) is not None),
        "Gate D3 exact archive SHA invalid",
    )
    require(isinstance(archive.get("is_a21_archive"), bool), "Gate D3 exact archive A2.1 flag invalid")
    require(isinstance(archive.get("safe"), bool), "Gate D3 exact archive safety flag invalid")
    unsafe_reason = archive.get("unsafe_reason")
    require(unsafe_reason is None or isinstance(unsafe_reason, str), "Gate D3 exact archive unsafe reason invalid")
    for field in ("manifest_member_count", "complete_49_plus_41_count"):
        value = archive.get(field)
        require(isinstance(value, int) and not isinstance(value, bool) and value >= 0, f"Gate D3 exact archive {field} invalid")
    identities = archive.get("complete_identities")
    require(isinstance(identities, list), "Gate D3 exact archive identities invalid")
    require(
        all(isinstance(item, str) and re.fullmatch(r"[0-9a-f]{64}", item) is not None for item in identities),
        "Gate D3 exact archive identities invalid",
    )
    sanitized = {
        "file_id": file_id,
        "archive": {
            "path": relative_path,
            "sha256": archive.get("sha256"),
            "is_a21_archive": archive.get("is_a21_archive"),
            "safe": archive.get("safe"),
            "unsafe_reason": archive.get("unsafe_reason"),
            "manifest_member_count": archive.get("manifest_member_count"),
            "complete_49_plus_41_count": archive.get("complete_49_plus_41_count"),
            "complete_identities": sorted(set(identities)),
        },
    }
    require(not _contains_absolute_path(sanitized), "Gate D3 exact archive contains absolute path")
    return sanitized


def _append_source_row(
    source_rows: list[dict[str, str]],
    identities: set[str],
    *,
    input_id: str,
    input_kind: str,
    kind: str,
    source: str,
    identity: Any,
) -> None:
    require(isinstance(identity, str) and re.fullmatch(r"[0-9a-f]{64}", identity) is not None, "Gate D3 candidate identity invalid")
    require(isinstance(source, str) and not source.startswith("/"), "Gate D3 candidate source invalid")
    require(kind in {"directory", "archive"}, "Gate D3 candidate kind invalid")
    identities.add(identity)
    row = {
        "input_id": input_id,
        "input_kind": input_kind,
        "kind": kind,
        "source": source,
        "identity_sha256": identity,
        "provenance_status": "unbound_requires_gate_d4_binding",
    }
    if input_kind == "root":
        row["root_id"] = input_id
    else:
        row["file_id"] = input_id
    source_rows.append(row)


def build_discovery(request: Mapping[str, Any]) -> dict[str, Any]:
    authoritative_complete, roots, files = validate_request(request)
    d3 = _load_d3_module()

    root_reports: list[dict[str, Any]] = []
    file_reports: list[dict[str, Any]] = []
    source_rows: list[dict[str, str]] = []
    identities: set[str] = set()

    for root_id, root in roots:
        inventory = d3.build_inventory(root)
        report = _sanitize_inventory(root_id, inventory)
        root_reports.append(report)
        for item in report["complete_recovery_sources"]:
            require(isinstance(item, dict), "Gate D3 recovery source invalid")
            _append_source_row(
                source_rows,
                identities,
                input_id=root_id,
                input_kind="root",
                kind=item.get("kind"),
                source=item.get("source"),
                identity=item.get("identity_sha256"),
            )

    for file_id, exact_file in files:
        archive = d3.archive_inventory(exact_file, exact_file.parent)
        report = _sanitize_exact_archive(file_id, archive)
        file_reports.append(report)
        archive_row = report["archive"]
        if archive_row["is_a21_archive"] or not archive_row["safe"]:
            continue
        for identity in archive_row["complete_identities"]:
            _append_source_row(
                source_rows,
                identities,
                input_id=file_id,
                input_kind="file",
                kind="archive",
                source=archive_row["path"],
                identity=identity,
            )

    source_rows.sort(
        key=lambda row: (
            row["identity_sha256"],
            row["input_kind"],
            row["input_id"],
            row["kind"],
            row["source"],
        )
    )
    distinct_identities = sorted(identities)
    if len(distinct_identities) > 1:
        decision = "AMBIGUOUS_PLAUSIBLE_RECOVERY_CANDIDATES"
        next_step = "bind_and_resolve_distinct_historical_identities"
    elif len(distinct_identities) == 1:
        decision = "PLAUSIBLE_RECOVERY_CANDIDATE_FOUND"
        next_step = "bind_candidate_to_independent_historical_provenance"
    elif authoritative_complete:
        decision = "READY_FOR_IRRECOVERABLE_DECISION"
        next_step = "record_separate_owner_reviewed_irrecoverable_decision"
    else:
        decision = "NO_CANDIDATE_IN_DESIGNATED_ROOTS"
        next_step = "authorize_additional_explicit_backup_inputs_or_mark_source_set_complete"

    require(decision in DECISIONS, "invalid Gate D4 decision")
    payload: dict[str, Any] = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "mode": MODE,
        "issue_number": ISSUE_NUMBER,
        "request_schema_version": request["schema_version"],
        "decision": decision,
        "authoritative_source_set_complete": authoritative_complete,
        "designated_root_count": len(root_reports),
        "designated_file_count": len(file_reports),
        "designated_input_count": len(root_reports) + len(file_reports),
        "complete_recovery_source_count": len(source_rows),
        "distinct_complete_identity_count": len(distinct_identities),
        "root_reports": root_reports,
        "file_reports": file_reports,
        "plausible_recovery_sources": source_rows,
        "complete_identities": distinct_identities,
        "provenance_binding_complete": False,
        "historical_recovery_authorized": False,
        "irrecoverable_decision_recorded": False,
        "next_step": next_step,
        "safety": {
            "explicit_inputs_only": True,
            "explicit_roots_only": not files,
            "exact_file_allowlist_enabled": bool(files),
            "raw_page_bytes_exported": False,
            "network_acquisition_authorized": False,
            "archive_extraction_authorized": False,
            "source_or_corpus_mutation_authorized": False,
            "manifest_regeneration_authorized": False,
            "parser_execution_authorized": False,
            "candidate_creation_authorized": False,
            "review_or_publication_write_authorized": False,
            "production_database_write_authorized": False,
            "production_deployment_authorized": False,
            "scheduler_systemd_canary_authorized": False,
            "destructive_cleanup_authorized": False,
            "newer_41_plus_41_substitution_authorized": False,
            "strict_49_plus_41_frozen_contract_unchanged": True,
        },
    }
    payload["diagnostic_fingerprint"] = sha256(canonical_bytes(payload)).hexdigest()
    return payload


def write_report(output: Path, payload: Mapping[str, Any]) -> None:
    require(not output.exists(), "output already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_bytes(payload) + b"\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    request = load_request(Path(args.request))
    payload = build_discovery(request)
    write_report(Path(args.output), payload)
    print(payload["decision"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
