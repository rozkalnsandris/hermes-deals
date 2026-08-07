#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import defaultdict
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping

MODE = "ALDI_GATE_D_RPI5_EVIDENCE_DISCOVERY_V01"
READY = "READY_FOR_GATE_D_EXECUTION"
WAIT = "WAIT_FOR_EXACT_EVIDENCE"
BLOCKED = "BLOCKED_AMBIGUOUS_LEGACY_EVIDENCE"
EXPECTED_A21_ARCHIVE_SHA256 = "fa16df4db701e90f38bea0387a278750415ba03628f1fe1cc34ffb2833f2985d"
EXPECTED_A21_PROJECTION_SHA256 = "64699b7ede52dcaa5b85f3306426f3b90399dd037209621a38bacd166161d5ea"
EXPECTED_GATE_B_PLAN_SHA256 = "3188821faa36a6d9fb598fde521a59993e6cb11678a8160e4afead4ba4fcfdd4"
EXPECTED_PAGE3_SHA256 = "ad297cdd2f3dc728f0114fcb8a06c6d2c6131f4b342173b134d9e99bd092ae7c"
EXPECTED_PAGE_COUNTS = {"current": 49, "preview": 41}


class DiscoveryError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DiscoveryError(message)


def sha_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def canonical_sha(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def _relative(root: Path, path: Path) -> str:
    resolved_root = root.resolve(strict=True)
    resolved = path.resolve(strict=True)
    try:
        return resolved.relative_to(resolved_root).as_posix()
    except ValueError as exc:
        raise DiscoveryError(f"path escapes state root: {path}") from exc


def _regular_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def _regular_dir(path: Path) -> bool:
    return path.is_dir() and not path.is_symlink()


def _exact_matches(
    paths: Iterable[Path],
    *,
    root: Path,
    expected_sha256: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in sorted(set(paths), key=lambda value: value.as_posix()):
        if not _regular_file(path):
            continue
        try:
            digest = sha_file(path)
        except OSError:
            continue
        if digest != expected_sha256:
            continue
        relative = _relative(root, path)
        if relative in seen:
            continue
        seen.add(relative)
        rows.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": digest,
            }
        )
    return rows


def load_gate_d_module() -> Any:
    tool = Path(__file__).with_name("aldi_weekly_gate_d_visual_review_pack.py")
    require(tool.is_file(), f"Gate D builder is missing: {tool}")
    spec = importlib.util.spec_from_file_location("aldi_gate_d_for_discovery", tool)
    require(spec is not None and spec.loader is not None, "cannot load Gate D builder")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _glob_many(root: Path, patterns: Iterable[str]) -> list[Path]:
    paths: set[Path] = set()
    for pattern in patterns:
        paths.update(root.glob(pattern))
    return sorted(paths, key=lambda value: value.as_posix())


def _legacy_identity(
    manifest_path: Path,
    *,
    state_root: Path,
    gate_d: Any,
) -> dict[str, Any] | None:
    if not _regular_file(manifest_path):
        return None
    run_root = manifest_path.parent.parent
    page_root = run_root / "raw" / "page-images"
    if not _regular_dir(run_root) or not _regular_dir(page_root):
        return None
    try:
        validated = gate_d.validate_legacy_page_manifest(manifest_path)
    except Exception:
        return None
    rows = validated.get("rows")
    if not isinstance(rows, list) or len(rows) != 90:
        return None

    compact_pages: list[dict[str, Any]] = []
    try:
        for raw in rows:
            label = str(raw["label"])
            page = int(raw["page_number"])
            source = page_root / label / f"page-{page:03d}.img"
            gate_d.validate_image(
                source,
                expected_sha256=str(raw["sha256"]),
                expected_bytes=int(raw["bytes"]),
                expected_format=str(raw["format"]),
            )
            compact_pages.append(
                {
                    "label": label,
                    "page_number": page,
                    "sha256": str(raw["sha256"]),
                    "bytes": int(raw["bytes"]),
                    "format": str(raw["format"]),
                }
            )
    except Exception:
        return None

    counts = {
        "current": sum(row["label"] == "current" for row in compact_pages),
        "preview": sum(row["label"] == "preview" for row in compact_pages),
    }
    if counts != EXPECTED_PAGE_COUNTS:
        return None
    compact_pages.sort(key=lambda row: (row["label"], row["page_number"]))
    return {
        "manifest_path": _relative(state_root, manifest_path),
        "page_root": _relative(state_root, page_root),
        "manifest_sha256": sha_file(manifest_path),
        "page_set_sha256": str(validated["page_set_sha256"]),
        "page_counts": counts,
        "page_bytes_sha256": canonical_sha(compact_pages),
    }


def safety_contract() -> dict[str, bool]:
    return {
        "discovery_only": True,
        "network_acquisition_authorized": False,
        "parser_execution_authorized": False,
        "source_or_corpus_mutation_authorized": False,
        "candidate_creation_authorized": False,
        "production_database_write_authorized": False,
        "review_write_authorized": False,
        "automatic_approval_authorized": False,
        "automatic_publication_authorized": False,
        "production_deployment_authorized": False,
        "scheduler_or_retry_authorized": False,
        "production_canary_authorized": False,
        "b15m2_v08_action_authorized": False,
        "strict_41_of_41_gate_unchanged": True,
    }


def discover_evidence(
    *,
    state_root: Path,
    gate_b_plan: Path,
    gate_d_module: Any | None = None,
) -> dict[str, Any]:
    require(_regular_dir(state_root), f"state root is missing or unsafe: {state_root}")
    require(_regular_file(gate_b_plan), f"Gate B plan is missing or unsafe: {gate_b_plan}")
    require(
        sha_file(gate_b_plan) == EXPECTED_GATE_B_PLAN_SHA256,
        "Gate B plan SHA256 mismatch",
    )
    gate_d = gate_d_module or load_gate_d_module()
    gate_b_plan_value, gate_b_validated = gate_d.load_gate_b_authoritative(gate_b_plan)
    require(
        gate_b_plan_value.get("decision") == "READY_FOR_SHADOW_REPLAY",
        "Gate B plan is not replay-ready",
    )

    archive_matches = _exact_matches(
        _glob_many(
            state_root,
            (
                "hermes-deals-aldi-a21-*.tar.gz",
                "**/hermes-deals-aldi-a21-*.tar.gz",
            ),
        ),
        root=state_root,
        expected_sha256=EXPECTED_A21_ARCHIVE_SHA256,
    )
    projection_matches = _exact_matches(
        _glob_many(
            state_root,
            (
                "**/reports/a21-adjudicated-projection.jsonl",
                "**/a21-adjudicated-projection.jsonl",
            ),
        ),
        root=state_root,
        expected_sha256=EXPECTED_A21_PROJECTION_SHA256,
    )
    page3_matches = _exact_matches(
        _glob_many(
            state_root,
            (
                "a30-authoritative-cycle-github/*/evidence/pages/current/page-003.img",
                "**/a30-authoritative-cycle-github/*/evidence/pages/current/page-003.img",
            ),
        ),
        root=state_root,
        expected_sha256=EXPECTED_PAGE3_SHA256,
    )

    legacy_rows = []
    for manifest in _glob_many(
        state_root,
        (
            "a30-v02-runs/*/reports/page-image-manifest.json",
            "**/a30-v02-runs/*/reports/page-image-manifest.json",
        ),
    ):
        row = _legacy_identity(manifest, state_root=state_root, gate_d=gate_d)
        if row is not None:
            legacy_rows.append(row)
    legacy_rows.sort(key=lambda row: (row["page_set_sha256"], row["manifest_path"]))

    by_page_set: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in legacy_rows:
        by_page_set[row["page_set_sha256"]].append(row)
    distinct_page_sets = sorted(by_page_set)

    missing = []
    if not archive_matches:
        missing.append("a21_archive")
    if not projection_matches:
        missing.append("a21_projection")
    if not legacy_rows:
        missing.append("legacy_a30_page_family")
    if not page3_matches:
        missing.append("authoritative_current_page3")

    if len(distinct_page_sets) > 1:
        decision, reason = BLOCKED, "multiple_distinct_valid_legacy_page_sets"
    elif missing:
        decision, reason = WAIT, "required_exact_evidence_missing"
    else:
        decision, reason = READY, "all_exact_inputs_discovered"

    selected_legacy = (
        sorted(
            by_page_set[distinct_page_sets[0]],
            key=lambda row: row["manifest_path"],
        )[0]
        if len(distinct_page_sets) == 1
        else None
    )
    gate_b_identity = gate_b_validated.get("identity")
    require(isinstance(gate_b_identity, Mapping), "validated Gate B identity missing")

    result = {
        "schema_version": 1,
        "mode": MODE,
        "issue_number": 223,
        "parent_issue_number": 165,
        "upstream_issue_numbers": [64, 191, 196, 200, 203, 208, 210, 215, 216],
        "decision": decision,
        "reason": reason,
        "missing_inputs": missing,
        "state_root": ".",
        "selected": {
            "a21_archive": archive_matches[0]["path"] if archive_matches else None,
            "a21_projection": projection_matches[0]["path"] if projection_matches else None,
            "legacy_manifest": selected_legacy["manifest_path"] if selected_legacy else None,
            "legacy_page_root": selected_legacy["page_root"] if selected_legacy else None,
            "current_page3": page3_matches[0]["path"] if page3_matches else None,
        },
        "matches": {
            "a21_archives": archive_matches,
            "a21_projections": projection_matches,
            "legacy_a30_runs": legacy_rows,
            "authoritative_current_page3": page3_matches,
        },
        "identity": {
            "a21_archive_sha256": EXPECTED_A21_ARCHIVE_SHA256,
            "a21_projection_sha256": EXPECTED_A21_PROJECTION_SHA256,
            "gate_b_plan_sha256": EXPECTED_GATE_B_PLAN_SHA256,
            "gate_b_replay_fingerprint": gate_b_plan_value.get("replay_fingerprint"),
            "current_manifest_sha256": gate_b_identity.get("current_manifest_sha256"),
            "current_page3_sha256": EXPECTED_PAGE3_SHA256,
            "legacy_page_set_sha256": (
                distinct_page_sets[0] if len(distinct_page_sets) == 1 else None
            ),
        },
        "safety": safety_contract(),
        "review_pack_execution_authorized": False,
        "production_eligible": False,
        "next_step": (
            "owner_authorized_gate_d_review_pack_execution"
            if decision == READY
            else "resolve_exact_evidence_discovery"
        ),
    }
    result["discovery_fingerprint"] = canonical_sha(result)
    return result


def write_create_only(path: Path, value: Mapping[str, Any]) -> str:
    data = canonical_bytes(value)
    require(not path.is_symlink(), f"symlinked output forbidden: {path}")
    if path.exists():
        require(path.is_file(), f"existing output is not a regular file: {path}")
        require(path.read_bytes() == data, "existing output differs")
        return "unchanged"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return "created"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--gate-b-plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = discover_evidence(
        state_root=args.state_root,
        gate_b_plan=args.gate_b_plan,
    )
    write_state = write_create_only(args.output, result)
    print(
        json.dumps(
            {"write_state": write_state, **result},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
