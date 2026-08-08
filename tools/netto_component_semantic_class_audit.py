#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
STRATEGY = "netto_component_semantic_class_audit_v1"
SOURCE_STRATEGY = "netto_object_component_signature_audit_v1"
TRUTH_USE_CONTRACT = "semantic_classes_frozen_before_truth_evaluation"
OWNERSHIP_VALUES = ("single_source", "mixed_source", "excluded_control")


class NettoComponentSemanticClassAuditError(ValueError):
    pass


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_bool(payload: dict[str, Any], key: str, expected: bool) -> None:
    if payload.get(key) is not expected:
        raise NettoComponentSemanticClassAuditError(
            f"unsafe component-signature flag: {key}={payload.get(key)!r}"
        )


def _component_semantic_tuple(component: dict[str, Any]) -> tuple[Any, ...]:
    counts = component.get("node_type_counts")
    if not isinstance(counts, dict):
        raise NettoComponentSemanticClassAuditError("component node_type_counts missing")
    required_counts = ("price_group", "price_anchor", "text_block", "image")
    try:
        count_values = tuple(int(counts[name]) for name in required_counts)
        node_count = int(component["node_count"])
    except (KeyError, TypeError, ValueError) as exc:
        raise NettoComponentSemanticClassAuditError(
            "invalid component semantic counts"
        ) from exc
    if node_count <= 0 or any(value < 0 for value in count_values):
        raise NettoComponentSemanticClassAuditError("negative/empty component counts")
    if sum(count_values) != node_count:
        raise NettoComponentSemanticClassAuditError("component count sum mismatch")
    return (
        *count_values,
        bool(component.get("complete_commercial_component")),
        bool(component.get("full_commercial_component")),
        bool(component.get("nonprice_fragment_component")),
        bool(component.get("image_text_nonprice_component")),
        bool(component.get("orphan_price_component")),
        bool(component.get("multi_price_group_component")),
    )


def freeze_semantic_class(row: dict[str, Any]) -> dict[str, Any]:
    if "independent_ownership" in row:
        raise NettoComponentSemanticClassAuditError(
            "ownership truth reached semantic class construction"
        )
    cell_id = str(row.get("cell_id") or "")
    components = row.get("components")
    if not cell_id or not isinstance(components, list) or not components:
        raise NettoComponentSemanticClassAuditError("cell components missing")
    component_tuples = sorted(_component_semantic_tuple(component) for component in components)
    semantic_key = [list(value) for value in component_tuples]
    return {
        "cell_id": cell_id,
        "semantic_class_key": semantic_key,
        "semantic_class_sha256": _sha256(semantic_key),
        "component_count": len(component_tuples),
    }


def freeze_semantic_classes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise NettoComponentSemanticClassAuditError("source rows missing")
    frozen = [
        freeze_semantic_class(
            {key: value for key, value in row.items() if key != "independent_ownership"}
        )
        for row in rows
    ]
    frozen.sort(key=lambda row: row["cell_id"])
    if len(frozen) != len({row["cell_id"] for row in frozen}):
        raise NettoComponentSemanticClassAuditError("duplicate cell id")
    return frozen


def _validate_source(payload: dict[str, Any]) -> None:
    if payload.get("strategy") != SOURCE_STRATEGY:
        raise NettoComponentSemanticClassAuditError("unexpected source strategy")
    if int(payload.get("schema_version") or 0) != 1:
        raise NettoComponentSemanticClassAuditError("unexpected source schema")
    if int(payload.get("source_cell_count") or 0) != 100:
        raise NettoComponentSemanticClassAuditError("source must contain 100 cells")
    rows = payload.get("rows")
    if not isinstance(rows, list) or len(rows) != 100:
        raise NettoComponentSemanticClassAuditError("source row count mismatch")
    for key, expected in (
        ("classification_performed", False),
        ("parser_behavior_changed", False),
        ("review_only", True),
        ("promotion_ready", False),
        ("image_binary_retained", False),
        ("ocr_used", False),
        ("database_write_performed", False),
        ("review_write_performed", False),
        ("automatic_approval_enabled", False),
        ("automatic_publish_enabled", False),
        ("deployment_performed", False),
    ):
        _require_bool(payload, key, expected)


def _truth_map_after_freeze(payload: dict[str, Any]) -> dict[str, str]:
    truth: dict[str, str] = {}
    for row in payload["rows"]:
        cell_id = str(row.get("cell_id") or "")
        ownership = str(row.get("independent_ownership") or "")
        if not cell_id or ownership not in OWNERSHIP_VALUES or cell_id in truth:
            raise NettoComponentSemanticClassAuditError("invalid ownership truth")
        truth[cell_id] = ownership
    counts = Counter(truth.values())
    if counts != Counter({"single_source": 88, "mixed_source": 10, "excluded_control": 2}):
        raise NettoComponentSemanticClassAuditError("ownership truth counts drift")
    return truth


def replay_semantic_class_audit(payload: dict[str, Any]) -> dict[str, Any]:
    _validate_source(payload)
    frozen = freeze_semantic_classes(payload)
    frozen_sha = _sha256(frozen)
    truth = _truth_map_after_freeze(payload)
    if set(truth) != {row["cell_id"] for row in frozen}:
        raise NettoComponentSemanticClassAuditError("truth/source cell universe mismatch")

    by_class: dict[str, list[str]] = defaultdict(list)
    key_by_class: dict[str, list[list[Any]]] = {}
    for row in frozen:
        class_sha = row["semantic_class_sha256"]
        by_class[class_sha].append(row["cell_id"])
        key_by_class[class_sha] = row["semantic_class_key"]

    class_rows: list[dict[str, Any]] = []
    for class_sha in sorted(by_class):
        cell_ids = sorted(by_class[class_sha])
        counts = Counter(truth[cell_id] for cell_id in cell_ids)
        non_excluded = counts["single_source"] + counts["mixed_source"]
        mixed_fraction = (
            round(counts["mixed_source"] / non_excluded, 6) if non_excluded else None
        )
        class_rows.append(
            {
                "semantic_class_sha256": class_sha,
                "semantic_class_key": key_by_class[class_sha],
                "cell_count": len(cell_ids),
                "ownership_counts": {value: counts[value] for value in OWNERSHIP_VALUES},
                "mixed_fraction_non_excluded": mixed_fraction,
                "truth_pure": sum(1 for value in OWNERSHIP_VALUES if counts[value]) == 1,
                "mixed_only_non_excluded": counts["mixed_source"] > 0 and counts["single_source"] == 0,
                "single_only_non_excluded": counts["single_source"] > 0 and counts["mixed_source"] == 0,
                "cell_ids": cell_ids,
            }
        )

    mixed_classes = [row for row in class_rows if row["ownership_counts"]["mixed_source"]]
    mixed_only_classes = [row for row in class_rows if row["mixed_only_non_excluded"]]
    mixed_cells_in_mixed_only = sum(row["ownership_counts"]["mixed_source"] for row in mixed_only_classes)
    single_cells_in_mixed_classes = sum(row["ownership_counts"]["single_source"] for row in mixed_classes)

    return {
        "schema_version": SCHEMA_VERSION,
        "strategy": STRATEGY,
        "source_strategy": SOURCE_STRATEGY,
        "source_frozen_signature_sha256": payload.get("frozen_signature_sha256"),
        "truth_use_contract": TRUTH_USE_CONTRACT,
        "frozen_semantic_class_sha256": frozen_sha,
        "semantic_class_count": len(class_rows),
        "mixed_source_class_count": len(mixed_classes),
        "mixed_only_non_excluded_class_count": len(mixed_only_classes),
        "mixed_source_cells_in_mixed_only_classes": mixed_cells_in_mixed_only,
        "single_source_cells_sharing_mixed_classes": single_cells_in_mixed_classes,
        "classes": class_rows,
        "classification_performed": False,
        "parser_behavior_changed": False,
        "review_only": True,
        "promotion_ready": False,
        "database_write_performed": False,
        "review_write_performed": False,
        "automatic_approval_enabled": False,
        "automatic_publish_enabled": False,
        "deployment_performed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--component-signatures", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    payload = json.loads(args.component_signatures.read_text(encoding="utf-8"))
    result = replay_semantic_class_audit(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"SEMANTIC_CLASS_AUDIT_RESULT=PASS class_count={result['semantic_class_count']}")
    print(f"FROZEN_SEMANTIC_CLASS_SHA256={result['frozen_semantic_class_sha256']}")
    print("CLASSIFICATION_PERFORMED=false")
    print("PARSER_BEHAVIOR_CHANGED=false")
    print("PROMOTION_READY=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
