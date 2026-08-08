from __future__ import annotations

import argparse
from collections import Counter
import importlib.util
import json
import math
from pathlib import Path
from statistics import median
import sys
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
TOPOLOGY_TOOL = ROOT / "tools/netto_card_region_topology_audit.py"
DEFAULT_OWNERSHIP_TRUTH = (
    ROOT / "backend/tests/fixtures/netto/n2_independent_ownership_summary_v1.json"
)
STRATEGY = "netto_object_card_graph_audit_v1"
PROXIMITY_GAP_FRACTION = 0.08
MIXED_CANARY_CELL_IDS = (
    "2073a7926a2caacc0f257767",
    "b96e8863f348bd632f74db8f",
    "beea6693263e14fc6adca1c6",
    "aa0f536b410f09e7a217fbb1",
)


class NettoObjectCardGraphAuditError(ValueError):
    pass


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise NettoObjectCardGraphAuditError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


TOPOLOGY = _load_module(TOPOLOGY_TOOL, "netto_object_card_graph_topology")
BASE = TOPOLOGY.BASE
OWNERSHIP = TOPOLOGY.OWNERSHIP


def _text(value: object) -> str | None:
    if value is None:
        return None
    result = " ".join(str(value).split()).strip()
    return result or None


def _raw_box(raw: Mapping[str, Any], geometry_module: Any) -> Any:
    try:
        nested = raw.get("bbox")
        if isinstance(nested, (list, tuple)) and len(nested) == 4:
            coords = nested
        elif isinstance(nested, Mapping):
            coords = tuple(nested[key] for key in ("x0", "y0", "x1", "y1"))
        else:
            coords = tuple(raw[key] for key in ("x0", "y0", "x1", "y1"))
        box = geometry_module.Box(*(float(value) for value in coords))
    except (KeyError, TypeError, ValueError) as exc:
        raise NettoObjectCardGraphAuditError("invalid object bbox") from exc
    if box.area <= 0:
        raise NettoObjectCardGraphAuditError("empty object bbox")
    return box


def _bbox_payload(box: Any) -> dict[str, float]:
    return {
        "x0": round(float(box.x0), 3),
        "y0": round(float(box.y0), 3),
        "x1": round(float(box.x1), 3),
        "y1": round(float(box.y1), 3),
    }


def _intersection_box(a: Any, b: Any, geometry_module: Any) -> Any | None:
    x0 = max(a.x0, b.x0)
    y0 = max(a.y0, b.y0)
    x1 = min(a.x1, b.x1)
    y1 = min(a.y1, b.y1)
    if x1 <= x0 or y1 <= y0:
        return None
    return geometry_module.Box(x0, y0, x1, y1)


def normalize_text_blocks(
    rows: Sequence[Sequence[Any]],
    geometry_module: Any,
) -> list[dict[str, Any]]:
    """Keep PyMuPDF text-block identity and bbox, never image payloads."""

    result: list[dict[str, Any]] = []
    for raw in rows:
        if len(raw) < 7:
            raise NettoObjectCardGraphAuditError("PyMuPDF block row is incomplete")
        block_type = int(raw[6])
        if block_type != 0:
            continue
        box = geometry_module.Box(*(float(raw[index]) for index in range(4)))
        if box.area <= 0:
            continue
        block_number = int(raw[5])
        result.append(
            {
                "object_type": "text_block",
                "object_id": f"text-block:{block_number}",
                "block_number": block_number,
                "bbox": _bbox_payload(box),
                "text": _text(raw[4]),
            }
        )
    return sorted(result, key=lambda row: (int(row["block_number"]), str(row["object_id"])))


def sanitize_image_info(
    rows: Sequence[Mapping[str, Any]],
    geometry_module: Any,
) -> list[dict[str, Any]]:
    """Retain displayed-image metadata and bbox without binary image content."""

    result: list[dict[str, Any]] = []
    for index, raw in enumerate(rows):
        box = _raw_box(raw, geometry_module)
        number = int(raw.get("number") if raw.get("number") is not None else index)
        digest = raw.get("digest")
        if isinstance(digest, (bytes, bytearray)):
            digest_value = bytes(digest).hex()
        elif digest is None:
            digest_value = None
        else:
            digest_value = str(digest)
        transform = raw.get("transform")
        result.append(
            {
                "object_type": "image",
                "object_id": f"image:{number}:{index}",
                "number": number,
                "bbox": _bbox_payload(box),
                "width": int(raw.get("width") or 0),
                "height": int(raw.get("height") or 0),
                "xres": int(raw.get("xres") or 0),
                "yres": int(raw.get("yres") or 0),
                "bpc": int(raw.get("bpc") or 0),
                "colorspace": int(raw.get("colorspace") or 0),
                "colorspace_name": _text(raw.get("cs-name")),
                "xref": int(raw.get("xref") or 0),
                "has_mask": bool(raw.get("has-mask")),
                "digest": digest_value,
                "transform": (
                    [round(float(value), 6) for value in transform]
                    if isinstance(transform, (list, tuple))
                    else None
                ),
            }
        )
    return sorted(result, key=lambda row: (int(row["number"]), str(row["object_id"])))


def extract_page_object_metadata(
    pdf_path: Path,
    page_number: int,
    geometry_module: Any,
) -> dict[str, Any]:
    """Extract block/image geometry without retaining image binary payload."""

    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required for object-card graph extraction") from exc

    document = fitz.open(pdf_path)
    try:
        if page_number < 1 or page_number > document.page_count:
            raise NettoObjectCardGraphAuditError("page number outside PDF")
        page = document.load_page(page_number - 1)
        text_blocks = normalize_text_blocks(
            page.get_text("blocks", sort=False),
            geometry_module,
        )
        images = sanitize_image_info(
            page.get_image_info(hashes=True, xrefs=True),
            geometry_module,
        )
        return {
            "page": {
                "width_points": round(float(page.cropbox.width), 3),
                "height_points": round(float(page.cropbox.height), 3),
                "rotation": int(page.rotation),
                "page_number": page_number,
            },
            "text_blocks": text_blocks,
            "images": images,
            "image_binary_retained": False,
        }
    finally:
        document.close()


def _cell_box(
    cell: Mapping[str, Any],
    width: float,
    height: float,
    geometry_module: Any,
) -> Any:
    return geometry_module.Box(
        *(float(value) for value in BASE.cell_rect(cell, width, height))
    )


def _clip_node(
    raw: Mapping[str, Any],
    *,
    cell_box: Any,
    geometry_module: Any,
    node_type: str,
    node_id: str,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    source_box = _raw_box(raw, geometry_module)
    clipped = _intersection_box(source_box, cell_box, geometry_module)
    if clipped is None:
        return None
    payload: dict[str, Any] = {
        "node_id": node_id,
        "node_type": node_type,
        "bbox": _bbox_payload(clipped),
        "source_bbox": _bbox_payload(source_box),
        "source_area_fraction_inside_cell": round(
            clipped.area / max(source_box.area, 0.001),
            6,
        ),
    }
    if metadata:
        payload["metadata"] = dict(metadata)
    return payload


def _node_box(node: Mapping[str, Any], geometry_module: Any) -> Any:
    bbox = node.get("bbox")
    if not isinstance(bbox, Mapping):
        raise NettoObjectCardGraphAuditError("graph node bbox missing")
    return _raw_box(bbox, geometry_module)


def _bbox_gap(a: Any, b: Any) -> float:
    dx = max(0.0, max(a.x0, b.x0) - min(a.x1, b.x1))
    dy = max(0.0, max(a.y0, b.y0) - min(a.y1, b.y1))
    return math.hypot(dx, dy)


def _intersection_area(a: Any, b: Any) -> float:
    width = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))
    height = max(0.0, min(a.y1, b.y1) - max(a.y0, b.y0))
    return width * height


def build_pairwise_relations(
    nodes: Sequence[Mapping[str, Any]],
    separators: Sequence[Any],
    cell_box: Any,
    geometry_module: Any,
) -> list[dict[str, Any]]:
    diagonal = max(math.hypot(cell_box.width, cell_box.height), 0.001)
    relations: list[dict[str, Any]] = []
    ordered = sorted(nodes, key=lambda row: str(row["node_id"]))
    for index, left in enumerate(ordered):
        left_box = _node_box(left, geometry_module)
        for right in ordered[index + 1 :]:
            right_box = _node_box(right, geometry_module)
            intersection = _intersection_area(left_box, right_box)
            gap_fraction = _bbox_gap(left_box, right_box) / diagonal
            separated = bool(
                geometry_module.separated(left_box, right_box, separators)
            )
            proximity_edge = intersection > 0 or gap_fraction <= PROXIMITY_GAP_FRACTION
            relations.append(
                {
                    "left": str(left["node_id"]),
                    "right": str(right["node_id"]),
                    "bbox_gap_fraction": round(gap_fraction, 6),
                    "center_distance_fraction": round(
                        math.hypot(
                            left_box.cx - right_box.cx,
                            left_box.cy - right_box.cy,
                        )
                        / diagonal,
                        6,
                    ),
                    "intersection_min_area_fraction": round(
                        intersection
                        / max(min(left_box.area, right_box.area), 0.001),
                        6,
                    ),
                    "source_separator_between": separated,
                    "proximity_edge": proximity_edge,
                    "separator_respecting_edge": proximity_edge and not separated,
                }
            )
    return relations


def _components(
    node_ids: Sequence[str],
    relations: Sequence[Mapping[str, Any]],
    edge_key: str,
) -> list[list[str]]:
    adjacency = {node_id: set() for node_id in node_ids}
    for row in relations:
        if row.get(edge_key) is not True:
            continue
        left = str(row["left"])
        right = str(row["right"])
        adjacency[left].add(right)
        adjacency[right].add(left)

    result: list[list[str]] = []
    unseen = set(node_ids)
    while unseen:
        root = min(unseen)
        stack = [root]
        component: list[str] = []
        unseen.remove(root)
        while stack:
            current = stack.pop()
            component.append(current)
            neighbors = sorted(adjacency[current] & unseen, reverse=True)
            for neighbor in neighbors:
                unseen.remove(neighbor)
                stack.append(neighbor)
        result.append(sorted(component))
    return sorted(result, key=lambda values: (values[0], len(values), values))


def _component_profiles(
    components: Sequence[Sequence[str]],
    nodes: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    by_id = {str(row["node_id"]): row for row in nodes}
    result: list[dict[str, Any]] = []
    for index, component in enumerate(components, start=1):
        counts = Counter(str(by_id[node_id]["node_type"]) for node_id in component)
        result.append(
            {
                "component_id": f"c{index:03d}",
                "node_ids": list(component),
                "node_type_counts": dict(sorted(counts.items())),
            }
        )
    return result


def extract_fixture_object_graphs(
    fixture: Mapping[str, Any],
    layout: Mapping[str, Any],
    analysis: Mapping[str, Any],
    page_objects: Mapping[str, Any],
    geometry_module: Any,
) -> list[dict[str, Any]]:
    """Freeze source object graphs before consulting independent ownership truth."""

    page = analysis.get("page")
    cells = fixture.get("cells")
    if not isinstance(page, Mapping) or not isinstance(cells, list):
        raise NettoObjectCardGraphAuditError("fixture/analysis page shape invalid")
    width = float(page.get("width_points") or 0.0)
    height = float(page.get("height_points") or 0.0)
    if width <= 0 or height <= 0:
        raise NettoObjectCardGraphAuditError("analysis page dimensions invalid")

    text_blocks = page_objects.get("text_blocks") or []
    images = page_objects.get("images") or []
    if not isinstance(text_blocks, list) or not isinstance(images, list):
        raise NettoObjectCardGraphAuditError("page object metadata shape invalid")

    vectors = layout.get("vectors") or {}
    if not isinstance(vectors, Mapping):
        raise NettoObjectCardGraphAuditError("layout vectors must be an object")
    separators = geometry_module.separators_from_layout(layout)

    groups = analysis.get("groups") or []
    anchors = analysis.get("price_anchors") or []
    if not isinstance(groups, list) or not isinstance(anchors, list):
        raise NettoObjectCardGraphAuditError("analysis group/anchor shape invalid")

    rows: list[dict[str, Any]] = []
    for raw_cell in cells:
        if not isinstance(raw_cell, Mapping):
            raise NettoObjectCardGraphAuditError("fixture cell must be an object")
        cell_id = _text(raw_cell.get("cell_id"))
        if cell_id is None:
            raise NettoObjectCardGraphAuditError("cell ID missing")
        cell_box = _cell_box(raw_cell, width, height, geometry_module)
        nodes: list[dict[str, Any]] = []

        for raw in text_blocks:
            if not isinstance(raw, Mapping):
                raise NettoObjectCardGraphAuditError("text block must be an object")
            node = _clip_node(
                raw,
                cell_box=cell_box,
                geometry_module=geometry_module,
                node_type="text_block",
                node_id=str(raw["object_id"]),
                metadata={
                    "block_number": raw.get("block_number"),
                    "text": raw.get("text"),
                },
            )
            if node:
                nodes.append(node)

        for raw in images:
            if not isinstance(raw, Mapping):
                raise NettoObjectCardGraphAuditError("image row must be an object")
            node = _clip_node(
                raw,
                cell_box=cell_box,
                geometry_module=geometry_module,
                node_type="image",
                node_id=str(raw["object_id"]),
                metadata={
                    key: raw.get(key)
                    for key in (
                        "number",
                        "width",
                        "height",
                        "xres",
                        "yres",
                        "bpc",
                        "colorspace",
                        "colorspace_name",
                        "xref",
                        "has_mask",
                        "digest",
                        "transform",
                    )
                },
            )
            if node:
                nodes.append(node)

        for raw in groups:
            if not isinstance(raw, Mapping):
                raise NettoObjectCardGraphAuditError("analysis group must be an object")
            group_id = _text(raw.get("group_id"))
            if group_id is None:
                raise NettoObjectCardGraphAuditError("analysis group ID missing")
            node = _clip_node(
                raw,
                cell_box=cell_box,
                geometry_module=geometry_module,
                node_type="price_group",
                node_id=f"price-group:{group_id}",
                metadata={"group_id": group_id},
            )
            if node:
                nodes.append(node)

        for raw in anchors:
            if not isinstance(raw, Mapping):
                raise NettoObjectCardGraphAuditError("analysis anchor must be an object")
            anchor_id = _text(raw.get("anchor_id"))
            if anchor_id is None:
                raise NettoObjectCardGraphAuditError("analysis anchor ID missing")
            node = _clip_node(
                raw,
                cell_box=cell_box,
                geometry_module=geometry_module,
                node_type="price_anchor",
                node_id=f"price-anchor:{anchor_id}",
                metadata={
                    "anchor_id": anchor_id,
                    "source_kind": raw.get("source_kind"),
                    "member_labeled": bool(raw.get("member_labeled")),
                    "member_badge_ambiguous": bool(raw.get("member_badge_ambiguous")),
                    "regular_labeled": bool(raw.get("regular_labeled")),
                    "unit_labeled": bool(raw.get("unit_labeled")),
                },
            )
            if node:
                nodes.append(node)

        if len({str(row["node_id"]) for row in nodes}) != len(nodes):
            raise NettoObjectCardGraphAuditError("duplicate graph node ID inside cell")

        relations = build_pairwise_relations(
            nodes,
            separators,
            cell_box,
            geometry_module,
        )
        node_ids = sorted(str(row["node_id"]) for row in nodes)
        proximity = _components(node_ids, relations, "proximity_edge")
        separator_respecting = _components(
            node_ids,
            relations,
            "separator_respecting_edge",
        )
        node_type_counts = Counter(str(row["node_type"]) for row in nodes)
        rows.append(
            {
                "cell_id": cell_id,
                "publication_slug": raw_cell.get("publication_slug"),
                "page_number": raw_cell.get("page_number"),
                "scope_state": raw_cell.get("scope_state"),
                "cell_rect_points": [
                    round(value, 3)
                    for value in (cell_box.x0, cell_box.y0, cell_box.x1, cell_box.y1)
                ],
                "nodes": sorted(nodes, key=lambda row: str(row["node_id"])),
                "node_type_counts": dict(sorted(node_type_counts.items())),
                "pairwise_relations": relations,
                "proximity_components": _component_profiles(proximity, nodes),
                "separator_respecting_components": _component_profiles(
                    separator_respecting,
                    nodes,
                ),
                "proximity_component_count": len(proximity),
                "separator_respecting_component_count": len(separator_respecting),
                "horizontal_vector_evidence": TOPOLOGY._segment_evidence(
                    vectors.get("horizontal_lines") or [],
                    orientation="horizontal",
                    cell_box=cell_box,
                ),
                "vertical_vector_evidence": TOPOLOGY._segment_evidence(
                    vectors.get("vertical_lines") or [],
                    orientation="vertical",
                    cell_box=cell_box,
                ),
                "image_binary_retained": False,
                "classification_performed": False,
                "parser_behavior_changed": False,
                "review_only": True,
                "promotion_ready": False,
            }
        )
    return rows


def _histogram(values: Sequence[int]) -> dict[str, int]:
    return {str(key): value for key, value in sorted(Counter(values).items())}


def summarize_object_graphs(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["independent_ownership"]), []).append(row)

    result: dict[str, Any] = {}
    for state, state_rows in sorted(grouped.items()):
        result[state] = {
            "cell_count": len(state_rows),
            "object_count_median": median(len(row["nodes"]) for row in state_rows),
            "text_block_count_median": median(
                int(row["node_type_counts"].get("text_block", 0))
                for row in state_rows
            ),
            "image_count_median": median(
                int(row["node_type_counts"].get("image", 0))
                for row in state_rows
            ),
            "price_group_count_median": median(
                int(row["node_type_counts"].get("price_group", 0))
                for row in state_rows
            ),
            "proximity_component_count_histogram": _histogram(
                [int(row["proximity_component_count"]) for row in state_rows]
            ),
            "separator_respecting_component_count_histogram": _histogram(
                [
                    int(row["separator_respecting_component_count"])
                    for row in state_rows
                ]
            ),
        }
    return result


def replay_object_card_graph_audit(
    fixtures: Sequence[Mapping[str, Any]],
    pdfs: Mapping[str, Path],
    *,
    ownership_truth_path: Path = DEFAULT_OWNERSHIP_TRUTH,
    geometry_module: Any | None = None,
) -> dict[str, Any]:
    module = geometry_module or BASE.load_geometry_module()
    source_rows: list[dict[str, Any]] = []
    for fixture in fixtures:
        page = fixture.get("page")
        if not isinstance(page, Mapping):
            raise NettoObjectCardGraphAuditError("fixture page metadata missing")
        campaign = _text(page.get("publication_slug"))
        page_number = page.get("page_number")
        if campaign not in BASE.CAMPAIGN_PDFS or not isinstance(page_number, int):
            raise NettoObjectCardGraphAuditError("fixture page identity invalid")
        pdf_path = pdfs[campaign]
        layout = module.extract_layout_from_pdf(pdf_path, page_number)
        analysis = module.analyze_layout(layout)
        page_objects = extract_page_object_metadata(
            pdf_path,
            page_number,
            module,
        )
        source_rows.extend(
            extract_fixture_object_graphs(
                fixture,
                layout,
                analysis,
                page_objects,
                module,
            )
        )

    cell_ids = {str(row["cell_id"]) for row in source_rows}
    if len(source_rows) != 100 or len(cell_ids) != 100:
        raise NettoObjectCardGraphAuditError(
            "object-card graph audit requires exactly 100 unique cells"
        )

    # Independent ownership is deliberately loaded only after every source-derived
    # graph has been frozen.
    truth = OWNERSHIP.load_ownership_truth(ownership_truth_path, cell_ids)
    rows: list[dict[str, Any]] = []
    for row in source_rows:
        item = dict(row)
        item["independent_ownership"] = truth[str(row["cell_id"])]
        rows.append(item)

    missing_canaries = sorted(set(MIXED_CANARY_CELL_IDS) - cell_ids)
    if missing_canaries:
        raise NettoObjectCardGraphAuditError(
            f"required mixed canary cells missing: {missing_canaries}"
        )

    return {
        "schema_version": 1,
        "strategy": STRATEGY,
        "geometry_parser_identity": BASE.EXPECTED_GEOMETRY_PARSER,
        "source_archive_sha256": BASE.EXPECTED_SOURCE_ARCHIVE_SHA256,
        "source_n9_fixture_manifest_sha256": BASE.EXPECTED_N9_MANIFEST_SHA256,
        "source_completed_independent_ledger_sha256": (
            "2fb5c5675d2b05b53da1f37cf4d1f66d32d152f3c7d77c0786d0400b5d30330a"
        ),
        "source_adjudication_sha256": (
            "59319ade8a5164b036a4f68474c36d46568c09dd9034e380c6928c15d2331088"
        ),
        "fixture_page_count": 17,
        "cell_count": 100,
        "independent_ownership_counts": dict(sorted(Counter(truth.values()).items())),
        "object_graph_by_independent_ownership": summarize_object_graphs(rows),
        "mixed_canary_cell_ids": list(MIXED_CANARY_CELL_IDS),
        "proximity_gap_fraction": PROXIMITY_GAP_FRACTION,
        "truth_use_contract": "adjudication_only_after_source_object_graph_freeze",
        "image_binary_retained": False,
        "ocr_used": False,
        "classification_performed": False,
        "parser_behavior_changed": False,
        "review_only": True,
        "promotion_ready": False,
        "automatic_approval_enabled": False,
        "automatic_publish_enabled": False,
        "database_write_performed": False,
        "deployment_performed": False,
        "rows": rows,
    }


def write_create_only(path: Path, payload: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise NettoObjectCardGraphAuditError("output already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze read-only Netto N9 object-level card graph evidence before "
            "designing another ownership classifier."
        )
    )
    parser.add_argument("--n9-manifest", type=Path, required=True)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--ownership-truth", type=Path, default=DEFAULT_OWNERSHIP_TRUTH)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    fixtures = BASE.load_exact_n9_manifest(args.n9_manifest)
    pdfs = BASE.locate_exact_pdfs(args.corpus_root)
    payload = replay_object_card_graph_audit(
        fixtures,
        pdfs,
        ownership_truth_path=args.ownership_truth,
    )
    write_create_only(args.output, payload)
    print(
        json.dumps(
            {
                "strategy": payload["strategy"],
                "cell_count": payload["cell_count"],
                "independent_ownership_counts": payload["independent_ownership_counts"],
                "object_graph_by_independent_ownership": payload[
                    "object_graph_by_independent_ownership"
                ],
                "classification_performed": payload["classification_performed"],
                "promotion_ready": payload["promotion_ready"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
