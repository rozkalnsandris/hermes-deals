#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping

MODE = "ALDI_GATE_D2_LEGACY_FAMILY_DIAGNOSTIC_V01"
EXPECTED_PAGE_COUNTS = {"current": 49, "preview": 41}
EXPECTED_TOTAL_PAGES = 90
VALID_FORMATS = {"jpeg", "png", "webp"}
MIN_IMAGE_BYTES = 10_000

FOUND = "EXACT_LEGACY_FAMILY_FOUND"
NONE = "NO_VALID_LEGACY_FAMILY"
MULTIPLE = "MULTIPLE_VALID_LEGACY_FAMILIES"


class DiagnosticError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DiagnosticError(message)


def sha_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def canonical_sha(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def regular_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def regular_dir(path: Path) -> bool:
    return path.is_dir() and not path.is_symlink()


def relative(root: Path, path: Path) -> str:
    resolved_root = root.resolve(strict=True)
    resolved = path.resolve(strict=True)
    try:
        return resolved.relative_to(resolved_root).as_posix()
    except ValueError as exc:
        raise DiagnosticError("path escapes state root") from exc


def glob_many(root: Path, patterns: Iterable[str]) -> list[Path]:
    found: set[Path] = set()
    for pattern in patterns:
        found.update(root.glob(pattern))
    return sorted(found, key=lambda value: value.as_posix())


def load_gate_d(tool: Path) -> Any:
    require(regular_file(tool), "frozen Gate D validator missing or unsafe")
    spec = importlib.util.spec_from_file_location("aldi_gate_d2_frozen_gate_d", tool)
    require(spec is not None and spec.loader is not None, "cannot load frozen Gate D validator")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    require(getattr(module, "EXPECTED_PAGE_COUNTS", None) == EXPECTED_PAGE_COUNTS, "frozen page-count contract drift")
    return module


def inspect_manifest_shape(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {
            "rows_list": False,
            "total_rows": 0,
            "current_rows": 0,
            "preview_rows": 0,
            "other_label_rows": 0,
            "duplicate_page_identities": 0,
            "invalid_page_numbers": 0,
            "invalid_sha_rows": 0,
            "small_image_rows": 0,
            "invalid_format_rows": 0,
        }
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return {
            "rows_list": False,
            "total_rows": 0,
            "current_rows": 0,
            "preview_rows": 0,
            "other_label_rows": 0,
            "duplicate_page_identities": 0,
            "invalid_page_numbers": 0,
            "invalid_sha_rows": 0,
            "small_image_rows": 0,
            "invalid_format_rows": 0,
        }

    labels: Counter[str] = Counter()
    seen: set[tuple[str, int]] = set()
    duplicates = invalid_pages = invalid_sha = small_rows = invalid_formats = 0
    for raw in rows:
        if not isinstance(raw, Mapping):
            labels["__invalid__"] += 1
            invalid_pages += 1
            invalid_sha += 1
            small_rows += 1
            invalid_formats += 1
            continue
        label = str(raw.get("label") or "")
        labels[label] += 1
        page = raw.get("page_number")
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            invalid_pages += 1
        else:
            key = (label, page)
            if key in seen:
                duplicates += 1
            seen.add(key)
        digest = raw.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            invalid_sha += 1
        size = raw.get("bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < MIN_IMAGE_BYTES:
            small_rows += 1
        if raw.get("format") not in VALID_FORMATS:
            invalid_formats += 1

    return {
        "rows_list": True,
        "total_rows": len(rows),
        "current_rows": labels.get("current", 0),
        "preview_rows": labels.get("preview", 0),
        "other_label_rows": sum(count for label, count in labels.items() if label not in EXPECTED_PAGE_COUNTS),
        "duplicate_page_identities": duplicates,
        "invalid_page_numbers": invalid_pages,
        "invalid_sha_rows": invalid_sha,
        "small_image_rows": small_rows,
        "invalid_format_rows": invalid_formats,
    }


def inspect_candidate(manifest: Path, *, state_root: Path, gate_d: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "manifest_path": relative(state_root, manifest),
        "manifest_regular": regular_file(manifest),
        "manifest_json_valid": False,
        "manifest_contract_valid": False,
        "image_root_present": False,
        "missing_images": 0,
        "byte_mismatches": 0,
        "sha_mismatches": 0,
        "format_mismatches": 0,
        "valid": False,
        "page_set_sha256": None,
        "failure_stage": "manifest_file",
    }
    if not row["manifest_regular"]:
        row.update(inspect_manifest_shape(None))
        return row

    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        row.update(inspect_manifest_shape(None))
        row["failure_stage"] = "manifest_json"
        return row

    row["manifest_json_valid"] = True
    row.update(inspect_manifest_shape(payload))

    try:
        validated = gate_d.validate_legacy_page_manifest(manifest)
    except Exception:
        row["failure_stage"] = "manifest_contract"
        return row

    rows = validated.get("rows")
    if not isinstance(rows, list) or len(rows) != EXPECTED_TOTAL_PAGES:
        row["failure_stage"] = "manifest_contract"
        return row
    row["manifest_contract_valid"] = True

    run_root = manifest.parent.parent
    page_root = run_root / "raw" / "page-images"
    row["image_root_present"] = regular_dir(page_root)
    if not row["image_root_present"]:
        row["failure_stage"] = "image_root"
        return row

    for item in rows:
        label = str(item["label"])
        page = int(item["page_number"])
        source = page_root / label / f"page-{page:03d}.img"
        if not regular_file(source):
            row["missing_images"] += 1
            continue
        if source.stat().st_size != int(item["bytes"]):
            row["byte_mismatches"] += 1
            continue
        try:
            digest = sha_file(source)
        except OSError:
            row["missing_images"] += 1
            continue
        if digest != str(item["sha256"]):
            row["sha_mismatches"] += 1
            continue
        try:
            image_format, _ = gate_d.detect_image_format(source.read_bytes())
        except Exception:
            row["format_mismatches"] += 1
            continue
        if image_format != str(item["format"]):
            row["format_mismatches"] += 1

    if any(row[key] for key in ("missing_images", "byte_mismatches", "sha_mismatches", "format_mismatches")):
        row["failure_stage"] = "image_validation"
        return row

    row["valid"] = True
    row["failure_stage"] = None
    row["page_set_sha256"] = str(validated["page_set_sha256"])
    return row


def safety_contract() -> dict[str, bool]:
    return {
        "diagnostic_only": True,
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
        "strict_49_plus_41_frozen_contract_unchanged": True,
    }


def diagnose(*, state_root: Path, gate_d_tool: Path) -> dict[str, Any]:
    require(regular_dir(state_root), "state root missing or unsafe")
    gate_d = load_gate_d(gate_d_tool)
    manifests = glob_many(
        state_root,
        (
            "a30-v02-runs/*/reports/page-image-manifest.json",
            "**/a30-v02-runs/*/reports/page-image-manifest.json",
        ),
    )
    candidates = [inspect_candidate(path, state_root=state_root, gate_d=gate_d) for path in manifests]
    valid = [row for row in candidates if row["valid"]]
    by_page_set: dict[str, list[str]] = defaultdict(list)
    for row in valid:
        by_page_set[str(row["page_set_sha256"])].append(str(row["manifest_path"]))
    page_sets = sorted(by_page_set)
    if len(page_sets) == 1:
        decision = FOUND
    elif len(page_sets) > 1:
        decision = MULTIPLE
    else:
        decision = NONE
    summary = Counter(str(row.get("failure_stage") or "valid") for row in candidates)
    result = {
        "schema_version": 1,
        "mode": MODE,
        "issue_number": 261,
        "decision": decision,
        "state_root": ".",
        "expected_page_counts": EXPECTED_PAGE_COUNTS,
        "candidate_count": len(candidates),
        "valid_candidate_count": len(valid),
        "distinct_valid_page_set_count": len(page_sets),
        "failure_stage_counts": dict(sorted(summary.items())),
        "candidates": candidates,
        "valid_page_sets": [
            {"page_set_sha256": digest, "manifest_paths": sorted(by_page_set[digest])}
            for digest in page_sets
        ],
        "safety": safety_contract(),
        "raw_evidence_exported": False,
        "raw_exception_exported": False,
        "production_eligible": False,
        "review_pack_execution_authorized": False,
        "next_step": (
            "bind_exact_legacy_family_into_gate_d1"
            if decision == FOUND
            else "prepare_immutable_legacy_family_recovery"
            if decision == NONE
            else "resolve_multiple_valid_legacy_page_sets"
        ),
    }
    result["diagnostic_fingerprint"] = canonical_sha(result)
    return result


def write_create_only(path: Path, value: Mapping[str, Any]) -> str:
    data = canonical_bytes(value)
    require(not path.is_symlink(), "symlinked output forbidden")
    if path.exists():
        require(path.is_file(), "existing output is not regular")
        require(path.read_bytes() == data, "existing output differs")
        return "unchanged"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return "created"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--gate-d-tool", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = diagnose(state_root=args.state_root, gate_d_tool=args.gate_d_tool)
    write_state = write_create_only(args.output, result)
    print(json.dumps({"write_state": write_state, **result}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
