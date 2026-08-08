#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
STRATEGY = "netto_object_component_signature_audit_v1"
SOURCE_STRATEGY = "netto_object_card_graph_audit_v1"
TRUTH_USE_CONTRACT = "component_signatures_frozen_before_truth_evaluation"
HARD_MIXED_CANARIES = (
    "2073a7926a2caacc0f257767",
    "b96e8863f348bd632f74db8f",
    "beea6693263e14fc6adca1c6",
    "aa0f536b410f09e7a217fbb1",
)
NODE_TYPES = ("price_group", "price_anchor", "text_block", "image")
SIGNATURE_METRICS = (
    "separator_component_count",
    "complete_commercial_component_count",
    "full_commercial_component_count",
    "nonprice_fragment_component_count",
    "image_text_nonprice_component_count",
    "orphan_price_component_count",
    "multi_price_group_component_count",
    "max_price_groups_per_component",
    "max_component_node_count",
    "second_largest_component_node_count",
)


class NettoObjectComponentSignatureAuditError(ValueError):
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
        raise NettoObjectComponentSignatureAuditError(
            f"unsafe source graph flag: {key}={payload.get(key)!r}"
        )


def _positive_rect(raw: Any, *, label: str) -> tuple[float, float, float, float]:
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        raise NettoObjectComponentSignatureAuditError(f"invalid {label}")
    try:
        x0, y0, x1, y1 = (float(value) for value in raw)
    except (TypeError, ValueError) as exc:
        raise NettoObjectComponentSignatureAuditError(f"invalid {label}") from exc
    if not x1 > x0 or not y1 > y0:
        raise NettoObjectComponentSignatureAuditError(f"empty {label}")
    return x0, y0, x1, y1


def _node_bbox(node: dict[str, Any]) -> tuple[float, float, float, float]:
    bbox = node.get("bbox")
    if not isinstance(bbox, dict):
        raise NettoObjectComponentSignatureAuditError("node bbox missing")
    return _positive_rect(
        [bbox.get("x0"), bbox.get("y0"), bbox.get("x1"), bbox.get("y1")],
        label="node bbox",
    )


def _source_fraction(node: dict[str, Any]) -> float:
    try:
        value = float(node.get("source_area_fraction_inside_cell"))
    except (TypeError, ValueError) as exc:
        raise NettoObjectComponentSignatureAuditError(
            "invalid source-area fraction"
        ) from exc
    if not 0.0 <= value <= 1.0:
        raise NettoObjectComponentSignatureAuditError("source-area fraction out of range")
    return value


def _source_only_row(row: dict[str, Any]) -> dict[str, Any]:
    # The independent truth is deliberately removed before signature construction.
    return {
        key: value
        for key, value in row.items()
        if key not in {"independent_ownership"}
    }


def freeze_cell_signature(source_row: dict[str, Any]) -> dict[str, Any]:
    if "independent_ownership" in source_row:
        raise NettoObjectComponentSignatureAuditError(
            "ownership truth reached signature construction"
        )

    cell_id = str(source_row.get("cell_id") or "")
    if not cell_id:
        raise NettoObjectComponentSignatureAuditError("cell id missing")
    page_number = int(source_row.get("page_number") or 0)
    if page_number <= 0:
        raise NettoObjectComponentSignatureAuditError("page number invalid")

    cell_x0, cell_y0, cell_x1, cell_y1 = _positive_rect(
        source_row.get("cell_rect_points"), label="cell rectangle"
    )
    cell_width = cell_x1 - cell_x0
    cell_height = cell_y1 - cell_y0
    cell_area = cell_width * cell_height

    nodes_raw = source_row.get("nodes")
    components_raw = source_row.get("separator_respecting_components")
    if not isinstance(nodes_raw, list) or not isinstance(components_raw, list):
        raise NettoObjectComponentSignatureAuditError("graph nodes/components missing")

    nodes: dict[str, dict[str, Any]] = {}
    for node in nodes_raw:
        if not isinstance(node, dict):
            raise NettoObjectComponentSignatureAuditError("invalid graph node")
        node_id = str(node.get("node_id") or "")
        if not node_id or node_id in nodes:
            raise NettoObjectComponentSignatureAuditError("duplicate or missing node id")
        node_type = str(node.get("node_type") or "")
        if node_type not in NODE_TYPES:
            raise NettoObjectComponentSignatureAuditError(
                f"unexpected node type: {node_type}"
            )
        _node_bbox(node)
        _source_fraction(node)
        nodes[node_id] = node

    frozen_components: list[dict[str, Any]] = []
    seen_node_ids: set[str] = set()
    for component in sorted(
        components_raw, key=lambda item: str((item or {}).get("component_id") or "")
    ):
        if not isinstance(component, dict):
            raise NettoObjectComponentSignatureAuditError("invalid component")
        component_id = str(component.get("component_id") or "")
        node_ids_raw = component.get("node_ids")
        if not component_id or not isinstance(node_ids_raw, list) or not node_ids_raw:
            raise NettoObjectComponentSignatureAuditError("invalid component identity")
        node_ids = sorted(str(node_id) for node_id in node_ids_raw)
        if len(node_ids) != len(set(node_ids)):
            raise NettoObjectComponentSignatureAuditError("duplicate node in component")
        if any(node_id not in nodes for node_id in node_ids):
            raise NettoObjectComponentSignatureAuditError("component references missing node")
        overlap = seen_node_ids.intersection(node_ids)
        if overlap:
            raise NettoObjectComponentSignatureAuditError(
                "node appears in multiple separator-respecting components"
            )
        seen_node_ids.update(node_ids)

        selected = [nodes[node_id] for node_id in node_ids]
        counts = Counter(str(node["node_type"]) for node in selected)
        x0 = min(_node_bbox(node)[0] for node in selected)
        y0 = min(_node_bbox(node)[1] for node in selected)
        x1 = max(_node_bbox(node)[2] for node in selected)
        y1 = max(_node_bbox(node)[3] for node in selected)
        fractions = sorted(_source_fraction(node) for node in selected)

        has_price_group = counts["price_group"] > 0
        has_price_anchor = counts["price_anchor"] > 0
        has_text = counts["text_block"] > 0
        has_image = counts["image"] > 0
        complete_commercial = has_price_group and has_price_anchor and has_text
        full_commercial = complete_commercial and has_image

        frozen_components.append(
            {
                "component_id": component_id,
                "node_count": len(selected),
                "node_type_counts": {name: int(counts[name]) for name in NODE_TYPES},
                "has_price_group": has_price_group,
                "has_price_anchor": has_price_anchor,
                "has_text_block": has_text,
                "has_image": has_image,
                "complete_commercial_component": complete_commercial,
                "full_commercial_component": full_commercial,
                "nonprice_fragment_component": not has_price_group,
                "image_text_nonprice_component": (
                    not has_price_group and has_image and has_text
                ),
                "orphan_price_component": (
                    has_price_group and (not has_price_anchor or not has_text)
                ),
                "multi_price_group_component": counts["price_group"] >= 2,
                "normalized_bbox": {
                    "x0": round((x0 - cell_x0) / cell_width, 6),
                    "y0": round((y0 - cell_y0) / cell_height, 6),
                    "x1": round((x1 - cell_x0) / cell_width, 6),
                    "y1": round((y1 - cell_y0) / cell_height, 6),
                    "area_fraction": round(((x1 - x0) * (y1 - y0)) / cell_area, 6),
                },
                "source_area_fraction_inside_cell_min": round(min(fractions), 6),
                "source_area_fraction_inside_cell_median": round(
                    float(statistics.median(fractions)), 6
                ),
            }
        )

    if seen_node_ids != set(nodes):
        raise NettoObjectComponentSignatureAuditError(
            "separator-respecting components do not cover every graph node"
        )

    node_sizes = sorted(
        (component["node_count"] for component in frozen_components), reverse=True
    )
    cell_signature = {
        "separator_component_count": len(frozen_components),
        "complete_commercial_component_count": sum(
            component["complete_commercial_component"]
            for component in frozen_components
        ),
        "full_commercial_component_count": sum(
            component["full_commercial_component"] for component in frozen_components
        ),
        "nonprice_fragment_component_count": sum(
            component["nonprice_fragment_component"] for component in frozen_components
        ),
        "image_text_nonprice_component_count": sum(
            component["image_text_nonprice_component"]
            for component in frozen_components
        ),
        "orphan_price_component_count": sum(
            component["orphan_price_component"] for component in frozen_components
        ),
        "multi_price_group_component_count": sum(
            component["multi_price_group_component"] for component in frozen_components
        ),
        "max_price_groups_per_component": max(
            (
                component["node_type_counts"]["price_group"]
                for component in frozen_components
            ),
            default=0,
        ),
        "max_component_node_count": node_sizes[0] if node_sizes else 0,
        "second_largest_component_node_count": node_sizes[1] if len(node_sizes) > 1 else 0,
    }

    return {
        "cell_id": cell_id,
        "page_number": page_number,
        "component_signature": cell_signature,
        "components": frozen_components,
    }


def freeze_source_signatures(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise NettoObjectComponentSignatureAuditError("source rows missing")
    frozen = [freeze_cell_signature(_source_only_row(row)) for row in rows]
    frozen.sort(key=lambda row: row["cell_id"])
    if len(frozen) != len({row["cell_id"] for row in frozen}):
        raise NettoObjectComponentSignatureAuditError("duplicate cell id")
    return frozen


def _validate_source_graph(payload: dict[str, Any]) -> None:
    if payload.get("strategy") != SOURCE_STRATEGY:
        raise NettoObjectComponentSignatureAuditError("unexpected source graph strategy")
    if int(payload.get("schema_version") or 0) != 1:
        raise NettoObjectComponentSignatureAuditError("unexpected source graph schema")
    if int(payload.get("cell_count") or 0) != 100:
        raise NettoObjectComponentSignatureAuditError("source graph must contain 100 cells")
    if int(payload.get("fixture_page_count") or 0) != 17:
        raise NettoObjectComponentSignatureAuditError("source graph fixture-page count mismatch")
    rows = payload.get("rows")
    if not isinstance(rows, list) or len(rows) != 100:
        raise NettoObjectComponentSignatureAuditError("source graph row count mismatch")

    _require_bool(payload, "image_binary_retained", False)
    _require_bool(payload, "ocr_used", False)
    _require_bool(payload, "classification_performed", False)
    _require_bool(payload, "parser_behavior_changed", False)
    _require_bool(payload, "review_only", True)
    _require_bool(payload, "promotion_ready", False)
    _require_bool(payload, "database_write_performed", False)
    _require_bool(payload, "deployment_performed", False)
    _require_bool(payload, "automatic_approval_enabled", False)
    _require_bool(payload, "automatic_publish_enabled", False)


def _truth_map_after_freeze(payload: dict[str, Any]) -> dict[str, str]:
    truth: dict[str, str] = {}
    for row in payload["rows"]:
        cell_id = str(row.get("cell_id") or "")
        ownership = str(row.get("independent_ownership") or "")
        if ownership not in {"single_source", "mixed_source", "excluded_control"}:
            raise NettoObjectComponentSignatureAuditError("invalid independent ownership")
        if not cell_id or cell_id in truth:
            raise NettoObjectComponentSignatureAuditError("invalid truth cell id")
        truth[cell_id] = ownership
    if Counter(truth.values()) != Counter(
        {"single_source": 88, "mixed_source": 10, "excluded_control": 2}
    ):
        raise NettoObjectComponentSignatureAuditError("independent ownership counts drift")
    return truth


def _metric_distribution(values: list[int]) -> dict[str, Any]:
    counter = Counter(values)
    return {
        "median": float(statistics.median(values)),
        "histogram": {str(key): counter[key] for key in sorted(counter)},
    }


def _rule_snapshots(
    frozen_by_id: dict[str, dict[str, Any]], truth: dict[str, str]
) -> dict[str, Any]:
    rules = {
        "separator_components_ge_5": lambda sig: sig["separator_component_count"] >= 5,
        "complete_commercial_components_ge_3": lambda sig: sig[
            "complete_commercial_component_count"
        ] >= 3,
        "full_commercial_components_ge_2": lambda sig: sig[
            "full_commercial_component_count"
        ] >= 2,
        "unmerged_3plus_commercial_components": lambda sig: (
            sig["complete_commercial_component_count"] >= 3
            and sig["multi_price_group_component_count"] == 0
        ),
    }
    output: dict[str, Any] = {}
    for name, predicate in rules.items():
        counts = Counter()
        matches: list[str] = []
        for cell_id in sorted(frozen_by_id):
            ownership = truth[cell_id]
            if predicate(frozen_by_id[cell_id]["component_signature"]):
                counts[ownership] += 1
                matches.append(cell_id)
        output[name] = {
            "classification_performed": False,
            "promotion_ready": False,
            "match_count_by_independent_ownership": {
                key: counts[key]
                for key in ("single_source", "mixed_source", "excluded_control")
            },
            "matching_cell_ids": matches,
        }
    return output


def replay_component_signature_audit(payload: dict[str, Any]) -> dict[str, Any]:
    _validate_source_graph(payload)

    # Truth is intentionally not consulted until these signatures and their digest exist.
    frozen = freeze_source_signatures(payload)
    frozen_signature_sha256 = _sha256(frozen)
    frozen_by_id = {row["cell_id"]: row for row in frozen}

    truth = _truth_map_after_freeze(payload)
    if set(truth) != set(frozen_by_id):
        raise NettoObjectComponentSignatureAuditError("truth/source cell universe mismatch")

    by_ownership: dict[str, Any] = {}
    for ownership in ("single_source", "mixed_source", "excluded_control"):
        cell_ids = sorted(cell_id for cell_id, value in truth.items() if value == ownership)
        metric_distributions = {}
        for metric in SIGNATURE_METRICS:
            metric_distributions[metric] = _metric_distribution(
                [
                    int(frozen_by_id[cell_id]["component_signature"][metric])
                    for cell_id in cell_ids
                ]
            )
        by_ownership[ownership] = {
            "cell_count": len(cell_ids),
            "metric_distributions": metric_distributions,
        }

    canaries = {}
    for cell_id in HARD_MIXED_CANARIES:
        if truth.get(cell_id) != "mixed_source":
            raise NettoObjectComponentSignatureAuditError(
                f"hard mixed canary truth mismatch: {cell_id}"
            )
        canaries[cell_id] = {
            "independent_ownership": truth[cell_id],
            "page_number": frozen_by_id[cell_id]["page_number"],
            "component_signature": frozen_by_id[cell_id]["component_signature"],
            "components": frozen_by_id[cell_id]["components"],
        }

    single_examples = sorted(
        (
            frozen_by_id[cell_id]
            for cell_id, ownership in truth.items()
            if ownership == "single_source"
        ),
        key=lambda row: (
            -row["component_signature"]["separator_component_count"],
            -row["component_signature"]["nonprice_fragment_component_count"],
            row["cell_id"],
        ),
    )[:8]

    evaluated_rows = [
        {
            **frozen_by_id[cell_id],
            "independent_ownership": truth[cell_id],
        }
        for cell_id in sorted(frozen_by_id)
    ]

    return {
        "schema_version": SCHEMA_VERSION,
        "strategy": STRATEGY,
        "source_graph_strategy": SOURCE_STRATEGY,
        "source_graph_sha256": _sha256(payload),
        "source_cell_count": len(frozen),
        "truth_use_contract": TRUTH_USE_CONTRACT,
        "frozen_signature_sha256": frozen_signature_sha256,
        "independent_ownership_counts": {
            key: Counter(truth.values())[key]
            for key in ("single_source", "mixed_source", "excluded_control")
        },
        "by_independent_ownership": by_ownership,
        "hard_mixed_canaries": canaries,
        "high_fragmentation_single_source_examples": single_examples,
        "predeclared_review_signal_snapshots": _rule_snapshots(frozen_by_id, truth),
        "rows": evaluated_rows,
        "classification_performed": False,
        "parser_behavior_changed": False,
        "review_only": True,
        "promotion_ready": False,
        "image_binary_retained": False,
        "ocr_used": False,
        "database_write_performed": False,
        "review_write_performed": False,
        "automatic_approval_enabled": False,
        "automatic_publish_enabled": False,
        "deployment_performed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--object-graph", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    payload = json.loads(args.object_graph.read_text(encoding="utf-8"))
    result = replay_component_signature_audit(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"COMPONENT_SIGNATURE_AUDIT_RESULT=PASS cell_count={result['source_cell_count']}")
    print(f"FROZEN_SIGNATURE_SHA256={result['frozen_signature_sha256']}")
    print("CLASSIFICATION_PERFORMED=false")
    print("PARSER_BEHAVIOR_CHANGED=false")
    print("PROMOTION_READY=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
