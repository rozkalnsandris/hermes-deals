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
SCHEMA_VERSION = 1
MODE = "ALDI_GATE_D4_BOUNDED_BACKUP_DISCOVERY"
GATE_D3_TOOL = Path(__file__).with_name("aldi_gate_d3_recovery_inventory.py")
EXPECTED_GATE_D3_SHA256 = "606976346177b3a6a2965c6aab536f249f2097c41e08e76f3704990fe0473cb8"
GATE_D3_STATE_ROOT = Path("/home/andris/.local/state/hermes-deals/aldi-perfect-shadow")
FORBIDDEN_BROAD_ROOTS = {
    Path("/"),
    Path("/home"),
    Path("/home/andris"),
}
ROOT_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
MAX_ROOTS = 8
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


def validate_request(payload: Mapping[str, Any]) -> tuple[bool, list[tuple[str, Path]]]:
    require(
        set(payload) == {
            "schema_version",
            "issue_number",
            "authoritative_source_set_complete",
            "roots",
        },
        "request fields mismatch",
    )
    require(payload.get("schema_version") == SCHEMA_VERSION, "unsupported request schema_version")
    require(payload.get("issue_number") == ISSUE_NUMBER, "request issue_number mismatch")
    complete = payload.get("authoritative_source_set_complete")
    require(isinstance(complete, bool), "authoritative_source_set_complete must be boolean")
    rows = payload.get("roots")
    require(isinstance(rows, list) and rows, "at least one explicit backup root is required")
    require(len(rows) <= MAX_ROOTS, "too many backup roots")

    roots: list[tuple[str, Path]] = []
    ids: set[str] = set()
    resolved_paths: set[Path] = set()
    for raw in rows:
        require(isinstance(raw, dict), "backup root entry must be an object")
        require(set(raw) == {"id", "path"}, "backup root entry fields mismatch")
        root_id = raw.get("id")
        require(isinstance(root_id, str) and ROOT_ID_RE.fullmatch(root_id) is not None, "invalid backup root id")
        require(root_id not in ids, "duplicate backup root id")
        root = _normalize_root(raw.get("path"))
        require(root not in resolved_paths, "duplicate backup root path")
        for _, existing in roots:
            require(
                root not in existing.parents and existing not in root.parents,
                "backup roots must not overlap",
            )
        ids.add(root_id)
        resolved_paths.add(root)
        roots.append((root_id, root))
    roots.sort(key=lambda item: item[0])
    return complete, roots


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


def build_discovery(request: Mapping[str, Any]) -> dict[str, Any]:
    authoritative_complete, roots = validate_request(request)
    d3 = _load_d3_module()

    reports: list[dict[str, Any]] = []
    source_rows: list[dict[str, str]] = []
    identities: set[str] = set()
    for root_id, root in roots:
        inventory = d3.build_inventory(root)
        report = _sanitize_inventory(root_id, inventory)
        reports.append(report)
        for item in report["complete_recovery_sources"]:
            require(isinstance(item, dict), "Gate D3 recovery source invalid")
            identity = item.get("identity_sha256")
            source = item.get("source")
            kind = item.get("kind")
            require(isinstance(identity, str) and len(identity) == 64, "Gate D3 candidate identity invalid")
            require(isinstance(source, str) and not source.startswith("/"), "Gate D3 candidate source invalid")
            require(kind in {"directory", "archive"}, "Gate D3 candidate kind invalid")
            identities.add(identity)
            source_rows.append(
                {
                    "root_id": root_id,
                    "kind": kind,
                    "source": source,
                    "identity_sha256": identity,
                    "provenance_status": "unbound_requires_gate_d4_binding",
                }
            )

    source_rows.sort(key=lambda row: (row["identity_sha256"], row["root_id"], row["kind"], row["source"]))
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
        next_step = "authorize_additional_explicit_backup_roots_or_mark_source_set_complete"

    require(decision in DECISIONS, "invalid Gate D4 decision")
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "mode": MODE,
        "issue_number": ISSUE_NUMBER,
        "decision": decision,
        "authoritative_source_set_complete": authoritative_complete,
        "designated_root_count": len(reports),
        "complete_recovery_source_count": len(source_rows),
        "distinct_complete_identity_count": len(distinct_identities),
        "root_reports": reports,
        "plausible_recovery_sources": source_rows,
        "complete_identities": distinct_identities,
        "provenance_binding_complete": False,
        "historical_recovery_authorized": False,
        "irrecoverable_decision_recorded": False,
        "next_step": next_step,
        "safety": {
            "explicit_roots_only": True,
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
