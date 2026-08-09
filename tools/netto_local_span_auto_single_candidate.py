from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import math
from statistics import median
from typing import Any, Mapping, Sequence

from netto_visual_geometry_shadow import Box, separated, separators_from_layout

SCHEMA_VERSION = 1
STRATEGY = "local_span_component_auto_single_v1"
GRAPH_GAP_MULTIPLIER = 0.5
MIN_OWNED_NODE_FRACTION = 2.0 / 3.0
MAX_COMPONENT_AREA_FRACTION = 0.005


class LocalSpanCandidateError(ValueError):
    pass


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def payload_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _box(raw: Any, *, label: str) -> Box:
    if isinstance(raw, Mapping):
        values = [raw.get(key) for key in ("x0", "y0", "x1", "y1")]
    elif isinstance(raw, (list, tuple)) and len(raw) == 4:
        values = list(raw)
    else:
        raise LocalSpanCandidateError(f"invalid {label}")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
        raise LocalSpanCandidateError(f"non-numeric {label}")
    box = Box(*(float(value) for value in values))
    if not all(math.isfinite(value) for value in (box.x0, box.y0, box.x1, box.y1)):
        raise LocalSpanCandidateError(f"non-finite {label}")
    if box.area <= 0:
        raise LocalSpanCandidateError(f"empty {label}")
    return box


def _bbox_payload(box: Box) -> list[float]:
    return [round(float(box.x0), 3), round(float(box.y0), 3), round(float(box.x1), 3), round(float(box.y1), 3)]


def _bbox_gap(a: Box, b: Box) -> float:
    dx = max(0.0, max(a.x0, b.x0) - min(a.x1, b.x1))
    dy = max(0.0, max(a.y0, b.y0) - min(a.y1, b.y1))
    return math.hypot(dx, dy)


def _positive_overlap(a: Box, b: Box) -> bool:
    return min(a.x1, b.x1) > max(a.x0, b.x0) and min(a.y1, b.y1) > max(a.y0, b.y0)


def _union(boxes: Sequence[Box]) -> Box:
    if not boxes:
        raise LocalSpanCandidateError("component cannot be empty")
    return Box(
        min(box.x0 for box in boxes),
        min(box.y0 for box in boxes),
        max(box.x1 for box in boxes),
        max(box.y1 for box in boxes),
    )


def _validate_matching_inputs(source: Mapping[str, Any], predictions: Mapping[str, Any]) -> dict[str, Any]:
    if source.get("strategy") != "netto_heldout_all_pages_source_evidence_v1":
        raise LocalSpanCandidateError("source evidence strategy mismatch")
    if predictions.get("strategy") != "netto_heldout_all_pages_predictions_v1":
        raise LocalSpanCandidateError("prediction strategy mismatch")
    for key in (
        "store_external_id",
        "scope",
        "campaign_key",
        "campaign_window",
        "source_identity_sha256",
        "source_pdf_sha256",
        "prediction_parser_identity",
        "page_count",
    ):
        if source.get(key) != predictions.get(key):
            raise LocalSpanCandidateError(f"source/prediction identity mismatch: {key}")
    for payload, label in ((source, "source"), (predictions, "predictions")):
        if payload.get("truth_included") is not False:
            raise LocalSpanCandidateError(f"{label} unexpectedly contains truth")
        if payload.get("expected_metadata_included") is not False:
            raise LocalSpanCandidateError(f"{label} unexpectedly contains expected metadata")
        if payload.get("review_labels_included") is not False:
            raise LocalSpanCandidateError(f"{label} unexpectedly contains review labels")
        if payload.get("review_only") is not True or payload.get("promotion_ready") is not False:
            raise LocalSpanCandidateError(f"{label} safety contract mismatch")
    page_count = int(source.get("page_count") or 0)
    source_pages = source.get("pages")
    prediction_pages = predictions.get("pages")
    if page_count <= 0 or not isinstance(source_pages, list) or not isinstance(prediction_pages, list):
        raise LocalSpanCandidateError("input page arrays are invalid")
    if len(source_pages) != page_count or len(prediction_pages) != page_count:
        raise LocalSpanCandidateError("input page counts are incomplete")
    return {
        "store_external_id": source["store_external_id"],
        "scope": source["scope"],
        "campaign_key": source["campaign_key"],
        "campaign_window": source["campaign_window"],
        "source_identity_sha256": source["source_identity_sha256"],
        "source_pdf_sha256": source["source_pdf_sha256"],
        "prediction_parser_identity": source["prediction_parser_identity"],
        "page_count": page_count,
    }


def _connected_components(nodes: Mapping[str, Box], layout: Mapping[str, Any], local_scale: float) -> list[list[str]]:
    if local_scale <= 0 or not math.isfinite(local_scale):
        raise LocalSpanCandidateError("local graph scale must be positive and finite")
    separators = separators_from_layout(layout)
    node_ids = sorted(nodes)
    adjacency = {node_id: set() for node_id in node_ids}
    maximum_gap = GRAPH_GAP_MULTIPLIER * local_scale
    for index, left_id in enumerate(node_ids):
        left = nodes[left_id]
        for right_id in node_ids[index + 1 :]:
            right = nodes[right_id]
            if separated(left, right, separators):
                continue
            if _positive_overlap(left, right) or _bbox_gap(left, right) <= maximum_gap:
                adjacency[left_id].add(right_id)
                adjacency[right_id].add(left_id)
    unseen = set(node_ids)
    result: list[list[str]] = []
    while unseen:
        root = min(unseen)
        unseen.remove(root)
        stack = [root]
        component: list[str] = []
        while stack:
            current = stack.pop()
            component.append(current)
            for neighbor in sorted(adjacency[current] & unseen, reverse=True):
                unseen.remove(neighbor)
                stack.append(neighbor)
        result.append(sorted(component))
    return result


def _group_atom_ids(group: Mapping[str, Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for key in ("title_span_indexes", "ambiguous_span_indexes"):
        indexes = group.get(key) or []
        if not isinstance(indexes, list):
            raise LocalSpanCandidateError(f"{key} must be a list")
        for raw_index in indexes:
            if isinstance(raw_index, bool) or not isinstance(raw_index, int):
                raise LocalSpanCandidateError("span index must be an integer")
            node_id = f"span:{raw_index}"
            if node_id not in seen:
                seen.add(node_id)
                result.append(node_id)
    anchor_ids = group.get("anchor_ids") or []
    if not isinstance(anchor_ids, list):
        raise LocalSpanCandidateError("anchor_ids must be a list")
    for raw_anchor_id in anchor_ids:
        node_id = f"anchor:{str(raw_anchor_id)}"
        if node_id not in seen:
            seen.add(node_id)
            result.append(node_id)
    return result


def freeze_candidate(
    source: Mapping[str, Any],
    predictions: Mapping[str, Any],
    *,
    source_evidence_sha256: str,
    predictions_sha256: str,
) -> dict[str, Any]:
    identity = _validate_matching_inputs(source, predictions)
    if len(source_evidence_sha256) != 64 or len(predictions_sha256) != 64:
        raise LocalSpanCandidateError("input SHA256 identities are required")
    source_pages = {int(page["page_number"]): page for page in source["pages"]}
    prediction_pages = {int(page["page_number"]): page for page in predictions["pages"]}
    expected_pages = set(range(1, identity["page_count"] + 1))
    if set(source_pages) != expected_pages or set(prediction_pages) != expected_pages:
        raise LocalSpanCandidateError("input page numbering is not exact sequential coverage")

    pages: list[dict[str, Any]] = []
    total_groups = 0
    total_components = 0
    candidate_count = 0
    cross_parent_group_reuse_count = 0

    for page_number in sorted(expected_pages):
        source_page = source_pages[page_number]
        prediction_page = prediction_pages[page_number]
        layout = source_page.get("layout")
        analysis = prediction_page.get("analysis")
        if not isinstance(layout, Mapping) or not isinstance(analysis, Mapping):
            raise LocalSpanCandidateError("source/prediction page body is missing")
        if analysis.get("parser_identity") != identity["prediction_parser_identity"]:
            raise LocalSpanCandidateError("prediction page parser identity mismatch")
        source_dims = layout.get("page") or {}
        prediction_dims = analysis.get("page") or {}
        width = float(source_dims.get("width_points") or 0.0)
        height = float(source_dims.get("height_points") or 0.0)
        if width <= 0 or height <= 0:
            raise LocalSpanCandidateError("page dimensions are invalid")
        if abs(width - float(prediction_dims.get("width_points") or 0.0)) > 0.001 or abs(
            height - float(prediction_dims.get("height_points") or 0.0)
        ) > 0.001:
            raise LocalSpanCandidateError("source/prediction page dimensions mismatch")

        spans = analysis.get("spans")
        anchors = analysis.get("price_anchors")
        groups = analysis.get("groups")
        if not isinstance(spans, list) or not isinstance(anchors, list) or not isinstance(groups, list):
            raise LocalSpanCandidateError("prediction page arrays are invalid")
        nodes: dict[str, Box] = {}
        span_heights: list[float] = []
        for raw in spans:
            if not isinstance(raw, Mapping):
                raise LocalSpanCandidateError("prediction span must be an object")
            index = int(raw["index"])
            node_id = f"span:{index}"
            if node_id in nodes:
                raise LocalSpanCandidateError("duplicate prediction span index")
            box = _box(raw.get("bbox"), label="prediction span bbox")
            nodes[node_id] = box
            span_heights.append(box.y1 - box.y0)
        for raw in anchors:
            if not isinstance(raw, Mapping):
                raise LocalSpanCandidateError("price anchor must be an object")
            node_id = f"anchor:{str(raw['anchor_id'])}"
            if node_id in nodes:
                raise LocalSpanCandidateError("duplicate price anchor id")
            nodes[node_id] = _box(raw.get("bbox"), label="price anchor bbox")
        if not span_heights:
            raise LocalSpanCandidateError("page has no text-span scale evidence")
        local_scale = float(median(span_heights))
        components = _connected_components(nodes, layout, local_scale)
        component_for_node: dict[str, str] = {}
        component_rows: list[dict[str, Any]] = []
        for component_index, member_ids in enumerate(components, start=1):
            component_id = f"p{page_number:03d}-c{component_index:03d}"
            boxes = [nodes[node_id] for node_id in member_ids]
            box = _union(boxes)
            for node_id in member_ids:
                component_for_node[node_id] = component_id
            component_rows.append(
                {
                    "parent_unit_id": component_id,
                    "bbox": _bbox_payload(box),
                    "area_fraction": round(box.area / (width * height), 8),
                    "node_ids": member_ids,
                    "node_count": len(member_ids),
                    "prediction_unit_ids": [],
                }
            )
        component_lookup = {row["parent_unit_id"]: row for row in component_rows}

        group_rows: list[dict[str, Any]] = []
        group_component_membership: defaultdict[str, list[str]] = defaultdict(list)
        seen_group_ids: set[str] = set()
        for group in groups:
            if not isinstance(group, Mapping):
                raise LocalSpanCandidateError("prediction group must be an object")
            group_id = str(group.get("group_id") or "")
            if not group_id or group_id in seen_group_ids:
                raise LocalSpanCandidateError("duplicate or missing group id")
            seen_group_ids.add(group_id)
            prediction_unit_id = f"p{page_number:03d}-{group_id}"
            atom_ids = _group_atom_ids(group)
            if any(atom_id not in component_for_node for atom_id in atom_ids):
                raise LocalSpanCandidateError("group references atom missing from frozen graph")
            component_ids = sorted({component_for_node[atom_id] for atom_id in atom_ids})
            if len(component_ids) > 1:
                cross_parent_group_reuse_count += 1
            for component_id in component_ids:
                group_component_membership[component_id].append(prediction_unit_id)
            group_rows.append(
                {
                    "prediction_unit_id": prediction_unit_id,
                    "group_id": group_id,
                    "atom_ids": atom_ids,
                    "atom_count": len(atom_ids),
                    "parent_unit_ids": component_ids,
                    "parent_unit_count": len(component_ids),
                }
            )
            total_groups += 1

        for component_id, prediction_unit_ids in group_component_membership.items():
            component_lookup[component_id]["prediction_unit_ids"] = sorted(prediction_unit_ids)

        for row in group_rows:
            reasons: list[str] = []
            component_id = row["parent_unit_ids"][0] if row["parent_unit_count"] == 1 else None
            if component_id is None:
                reasons.append("owned_atoms_span_multiple_parent_units" if row["parent_unit_count"] > 1 else "no_owned_atoms")
                owned_fraction = None
                component_area_fraction = None
                component_group_count = None
            else:
                component = component_lookup[component_id]
                owned_fraction = row["atom_count"] / int(component["node_count"])
                component_area_fraction = float(component["area_fraction"])
                component_group_count = len(component["prediction_unit_ids"])
                if component_group_count != 1:
                    reasons.append("parent_unit_referenced_by_multiple_groups")
                if owned_fraction < MIN_OWNED_NODE_FRACTION:
                    reasons.append("owned_node_fraction_below_minimum")
                if component_area_fraction > MAX_COMPONENT_AREA_FRACTION:
                    reasons.append("parent_unit_area_above_maximum")
            candidate_auto_single = component_id is not None and not reasons
            if candidate_auto_single:
                candidate_count += 1
                reasons.append("conservative_local_span_component_candidate")
            row.update(
                {
                    "primary_parent_unit_id": component_id,
                    "parent_group_count": component_group_count,
                    "owned_node_fraction": None if owned_fraction is None else round(owned_fraction, 8),
                    "parent_area_fraction": component_area_fraction,
                    "candidate_auto_single": candidate_auto_single,
                    "candidate_reasons": reasons,
                }
            )

        pages.append(
            {
                "page_number": page_number,
                "page_width_points": round(width, 3),
                "page_height_points": round(height, 3),
                "median_span_height_points": round(local_scale, 6),
                "parent_units": component_rows,
                "groups": group_rows,
            }
        )
        total_components += len(component_rows)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "strategy": STRATEGY,
        **identity,
        "source_evidence_sha256": source_evidence_sha256,
        "predictions_sha256": predictions_sha256,
        "config": {
            "graph_nodes": ["prediction_text_span", "prediction_price_anchor"],
            "graph_gap_multiplier": GRAPH_GAP_MULTIPLIER,
            "graph_local_scale": "page_median_positive_text_span_height",
            "graph_separator_contract": "netto_visual_geometry_shadow.separators_from_layout+separated",
            "minimum_owned_node_fraction": MIN_OWNED_NODE_FRACTION,
            "maximum_parent_area_fraction": MAX_COMPONENT_AREA_FRACTION,
            "requires_exactly_one_parent_unit": True,
            "requires_exactly_one_group_per_parent_unit": True,
        },
        "prediction_group_count": total_groups,
        "parent_unit_count": total_components,
        "candidate_auto_single_count": candidate_count,
        "cross_parent_group_reuse_count": cross_parent_group_reuse_count,
        "truth_used_for_candidate_construction": False,
        "automatic_candidate_decisions_frozen": True,
        "review_only": True,
        "promotion_ready": False,
        "parser_behavior_changed": False,
        "pages": pages,
    }
    payload["candidate_provenance_sha256"] = payload_sha256(payload)
    return payload


def candidate_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    pages = payload.get("pages")
    if not isinstance(pages, list):
        raise LocalSpanCandidateError("candidate pages are missing")
    for page in pages:
        if not isinstance(page, Mapping):
            raise LocalSpanCandidateError("candidate page must be an object")
        groups = page.get("groups")
        if not isinstance(groups, list):
            raise LocalSpanCandidateError("candidate group list is missing")
        result.extend(row for row in groups if isinstance(row, dict) and row.get("candidate_auto_single") is True)
    return result
