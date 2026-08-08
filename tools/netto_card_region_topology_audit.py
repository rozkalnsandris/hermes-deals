from __future__ import annotations

import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path
from statistics import median
import sys
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
BASE_REPLAY_TOOL = ROOT / "tools/netto_visual_geometry_corpus_replay.py"
OWNERSHIP_AUDIT_TOOL = ROOT / "tools/netto_ownership_separator_audit.py"
DEFAULT_OWNERSHIP_TRUTH = (
    ROOT / "backend/tests/fixtures/netto/n2_independent_ownership_summary_v1.json"
)
STRATEGY = "netto_card_region_topology_audit_v1"
CUT_THRESHOLDS = (0.35, 0.50, 0.70, 0.85)
INTERIOR_MARGIN = 0.08


class NettoCardRegionTopologyAuditError(ValueError):
    pass


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise NettoCardRegionTopologyAuditError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BASE = _load_module(BASE_REPLAY_TOOL, "netto_card_region_topology_base_replay")
OWNERSHIP = _load_module(OWNERSHIP_AUDIT_TOOL, "netto_card_region_topology_ownership")


def _text(value: object) -> str | None:
    if value is None:
        return None
    result = " ".join(str(value).split()).strip()
    return result or None


def _cell_box(cell: Mapping[str, Any], width: float, height: float, geometry_module: Any) -> Any:
    return geometry_module.Box(*(float(value) for value in BASE.cell_rect(cell, width, height)))


def _raw_box(raw: Mapping[str, Any], geometry_module: Any) -> Any:
    try:
        box = geometry_module.Box(
            float(raw["x0"]),
            float(raw["y0"]),
            float(raw["x1"]),
            float(raw["y1"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise NettoCardRegionTopologyAuditError("invalid topology bbox") from exc
    if box.area <= 0:
        raise NettoCardRegionTopologyAuditError("empty topology bbox")
    return box


def _intersection_area(a: Any, b: Any) -> float:
    width = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))
    height = max(0.0, min(a.y1, b.y1) - max(a.y0, b.y0))
    return width * height


def _segment_evidence(
    rows: Sequence[Mapping[str, Any]],
    *,
    orientation: str,
    cell_box: Any,
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for raw in rows:
        try:
            x1 = float(raw["x1"])
            y1 = float(raw["y1"])
            x2 = float(raw["x2"])
            y2 = float(raw["y2"])
        except (KeyError, TypeError, ValueError) as exc:
            raise NettoCardRegionTopologyAuditError("invalid topology vector") from exc

        if orientation == "horizontal":
            axis = (y1 + y2) / 2.0
            if not (cell_box.y0 <= axis <= cell_box.y1):
                continue
            low, high = sorted((x1, x2))
            overlap = max(0.0, min(high, cell_box.x1) - max(low, cell_box.x0))
            if overlap <= 0:
                continue
            coverage = overlap / max(cell_box.width, 0.001)
            position = (axis - cell_box.y0) / max(cell_box.height, 0.001)
        elif orientation == "vertical":
            axis = (x1 + x2) / 2.0
            if not (cell_box.x0 <= axis <= cell_box.x1):
                continue
            low, high = sorted((y1, y2))
            overlap = max(0.0, min(high, cell_box.y1) - max(low, cell_box.y0))
            if overlap <= 0:
                continue
            coverage = overlap / max(cell_box.height, 0.001)
            position = (axis - cell_box.x0) / max(cell_box.width, 0.001)
        else:
            raise NettoCardRegionTopologyAuditError(f"unsupported orientation: {orientation}")

        evidence.append(
            {
                "orientation": orientation,
                "coverage": round(min(1.0, coverage), 6),
                "position": round(position, 6),
                "interior": INTERIOR_MARGIN <= position <= 1.0 - INTERIOR_MARGIN,
            }
        )
    return sorted(
        evidence,
        key=lambda row: (-float(row["coverage"]), abs(float(row["position"]) - 0.5)),
    )


def _coverage_summary(evidence: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    interior = [row for row in evidence if row.get("interior") is True]
    strongest = max((float(row["coverage"]) for row in interior), default=0.0)
    strongest_position = None
    if interior:
        best = min(
            interior,
            key=lambda row: (-float(row["coverage"]), abs(float(row["position"]) - 0.5)),
        )
        strongest_position = float(best["position"])
    return {
        "interior_vector_count": len(interior),
        "strongest_interior_coverage": round(strongest, 6),
        "strongest_interior_position": (
            round(strongest_position, 6) if strongest_position is not None else None
        ),
        "coverage_threshold_counts": {
            f"ge_{int(threshold * 100):02d}": sum(
                float(row["coverage"]) >= threshold for row in interior
            )
            for threshold in CUT_THRESHOLDS
        },
    }


def _content_points(
    layout: Mapping[str, Any],
    analysis: Mapping[str, Any],
    cell_box: Any,
    geometry_module: Any,
) -> tuple[list[tuple[float, float]], int, int, list[str]]:
    spans = layout.get("spans") or []
    if not isinstance(spans, list):
        raise NettoCardRegionTopologyAuditError("layout spans must be a list")
    points: list[tuple[float, float]] = []
    text_span_count = 0
    nonprice_text_span_count = 0
    for raw in spans:
        if not isinstance(raw, Mapping):
            raise NettoCardRegionTopologyAuditError("layout span must be an object")
        box = _raw_box(raw, geometry_module)
        if not cell_box.contains_point(box.cx, box.cy):
            continue
        text_span_count += 1
        text = _text(raw.get("text")) or ""
        price_like = bool(
            geometry_module.PRICE_RE.search(text)
            or geometry_module.MAJOR_PRICE_RE.fullmatch(text)
            or geometry_module.CENTS_PRICE_RE.fullmatch(text)
        )
        if not price_like:
            nonprice_text_span_count += 1
        points.append((box.cx, box.cy))

    groups = analysis.get("groups") or []
    if not isinstance(groups, list):
        raise NettoCardRegionTopologyAuditError("analysis groups must be a list")
    center_group_ids: list[str] = []
    for raw in groups:
        if not isinstance(raw, Mapping):
            raise NettoCardRegionTopologyAuditError("analysis group must be an object")
        group_id = _text(raw.get("group_id"))
        bbox = raw.get("bbox")
        if group_id is None or not isinstance(bbox, Mapping):
            raise NettoCardRegionTopologyAuditError("analysis group identity/bbox missing")
        box = _raw_box(bbox, geometry_module)
        if cell_box.contains_point(box.cx, box.cy):
            center_group_ids.append(group_id)
            points.append((box.cx, box.cy))
    return points, text_span_count, nonprice_text_span_count, sorted(center_group_ids)


def _side_occupancy(
    evidence: Sequence[Mapping[str, Any]],
    points: Sequence[tuple[float, float]],
    *,
    orientation: str,
    cell_box: Any,
) -> dict[str, int] | None:
    interior = [row for row in evidence if row.get("interior") is True]
    if not interior:
        return None
    best = min(
        interior,
        key=lambda row: (-float(row["coverage"]), abs(float(row["position"]) - 0.5)),
    )
    position = float(best["position"])
    axis = (
        cell_box.y0 + position * cell_box.height
        if orientation == "horizontal"
        else cell_box.x0 + position * cell_box.width
    )
    scale = cell_box.height if orientation == "horizontal" else cell_box.width
    tolerance = max(scale * 0.02, 0.5)
    before = after = near = 0
    for x, y in points:
        value = y if orientation == "horizontal" else x
        if value < axis - tolerance:
            before += 1
        elif value > axis + tolerance:
            after += 1
        else:
            near += 1
    return {"before": before, "after": after, "near": near}


def _quadrant_counts(points: Sequence[tuple[float, float]], cell_box: Any) -> dict[str, int]:
    result = {"top_left": 0, "top_right": 0, "bottom_left": 0, "bottom_right": 0}
    for x, y in points:
        horizontal = "left" if x < cell_box.cx else "right"
        vertical = "top" if y < cell_box.cy else "bottom"
        result[f"{vertical}_{horizontal}"] += 1
    return result


def _rectangle_evidence(
    rows: Sequence[Mapping[str, Any]],
    cell_box: Any,
    geometry_module: Any,
    *,
    include_fill: bool,
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise NettoCardRegionTopologyAuditError("rectangle row must be an object")
        box = _raw_box(raw, geometry_module)
        area = _intersection_area(box, cell_box)
        if area <= 0:
            continue
        item: dict[str, Any] = {
            "intersection_cell_area_fraction": round(
                area / max(cell_box.area, 0.001), 6
            ),
            "contains_cell_center": box.contains_point(cell_box.cx, cell_box.cy),
        }
        if include_fill:
            rgb = raw.get("fill_rgb")
            item["fill_rgb"] = list(rgb) if isinstance(rgb, (list, tuple)) else None
            item["fill_opacity"] = raw.get("fill_opacity")
        evidence.append(item)
    return sorted(
        evidence,
        key=lambda row: (
            -float(row["intersection_cell_area_fraction"]),
            not bool(row["contains_cell_center"]),
        ),
    )


def extract_fixture_topology(
    fixture: Mapping[str, Any],
    layout: Mapping[str, Any],
    analysis: Mapping[str, Any],
    geometry_module: Any,
) -> list[dict[str, Any]]:
    """Freeze card-region topology without consulting independent review truth."""

    page = analysis.get("page")
    cells = fixture.get("cells")
    if not isinstance(page, Mapping) or not isinstance(cells, list):
        raise NettoCardRegionTopologyAuditError("fixture/analysis page shape invalid")
    width = float(page.get("width_points") or 0.0)
    height = float(page.get("height_points") or 0.0)
    if width <= 0 or height <= 0:
        raise NettoCardRegionTopologyAuditError("analysis page dimensions invalid")

    vectors = layout.get("vectors") or {}
    if not isinstance(vectors, Mapping):
        raise NettoCardRegionTopologyAuditError("layout vectors must be an object")

    rows: list[dict[str, Any]] = []
    for raw_cell in cells:
        if not isinstance(raw_cell, Mapping):
            raise NettoCardRegionTopologyAuditError("fixture cell must be an object")
        cell_id = _text(raw_cell.get("cell_id"))
        if cell_id is None:
            raise NettoCardRegionTopologyAuditError("cell ID missing")
        cell_box = _cell_box(raw_cell, width, height, geometry_module)
        points, span_count, nonprice_count, center_group_ids = _content_points(
            layout, analysis, cell_box, geometry_module
        )
        horizontal = _segment_evidence(
            vectors.get("horizontal_lines") or [],
            orientation="horizontal",
            cell_box=cell_box,
        )
        vertical = _segment_evidence(
            vectors.get("vertical_lines") or [],
            orientation="vertical",
            cell_box=cell_box,
        )
        rectangles = _rectangle_evidence(
            vectors.get("rectangles") or [],
            cell_box,
            geometry_module,
            include_fill=False,
        )
        filled = _rectangle_evidence(
            vectors.get("filled_rectangles") or [],
            cell_box,
            geometry_module,
            include_fill=True,
        )
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
                "center_group_ids": center_group_ids,
                "center_group_count": len(center_group_ids),
                "text_span_count": span_count,
                "nonprice_text_span_count": nonprice_count,
                "content_point_count": len(points),
                "content_quadrant_counts": _quadrant_counts(points, cell_box),
                "horizontal_vector_evidence": horizontal,
                "vertical_vector_evidence": vertical,
                "horizontal_cut_summary": _coverage_summary(horizontal),
                "vertical_cut_summary": _coverage_summary(vertical),
                "strongest_horizontal_cut_side_occupancy": _side_occupancy(
                    horizontal, points, orientation="horizontal", cell_box=cell_box
                ),
                "strongest_vertical_cut_side_occupancy": _side_occupancy(
                    vertical, points, orientation="vertical", cell_box=cell_box
                ),
                "rectangle_evidence": rectangles,
                "filled_rectangle_evidence": filled,
                "review_only": True,
                "promotion_ready": False,
            }
        )
    return rows


def _histogram(values: Sequence[int]) -> dict[str, int]:
    return {str(key): value for key, value in sorted(Counter(values).items())}


def summarize_topology(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        state = str(row["independent_ownership"])
        grouped.setdefault(state, []).append(row)

    result: dict[str, Any] = {}
    for state, state_rows in sorted(grouped.items()):
        horizontal = [
            float(row["horizontal_cut_summary"]["strongest_interior_coverage"])
            for row in state_rows
        ]
        vertical = [
            float(row["vertical_cut_summary"]["strongest_interior_coverage"])
            for row in state_rows
        ]
        result[state] = {
            "cell_count": len(state_rows),
            "center_group_count_histogram": _histogram(
                [int(row["center_group_count"]) for row in state_rows]
            ),
            "text_span_count_median": median(
                int(row["text_span_count"]) for row in state_rows
            ),
            "nonprice_text_span_count_median": median(
                int(row["nonprice_text_span_count"]) for row in state_rows
            ),
            "strongest_horizontal_interior_cut_coverage_median": round(
                float(median(horizontal)), 6
            ),
            "strongest_vertical_interior_cut_coverage_median": round(
                float(median(vertical)), 6
            ),
            "either_orientation_cut_cell_counts": {
                f"ge_{int(threshold * 100):02d}": sum(
                    max(h, v) >= threshold for h, v in zip(horizontal, vertical)
                )
                for threshold in CUT_THRESHOLDS
            },
        }
    return result


def replay_card_region_topology_audit(
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
            raise NettoCardRegionTopologyAuditError("fixture page metadata missing")
        campaign = _text(page.get("publication_slug"))
        page_number = page.get("page_number")
        if campaign not in BASE.CAMPAIGN_PDFS or not isinstance(page_number, int):
            raise NettoCardRegionTopologyAuditError("fixture page identity invalid")
        layout = module.extract_layout_from_pdf(pdfs[campaign], page_number)
        analysis = module.analyze_layout(layout)
        analysis_page = analysis.get("page") if isinstance(analysis, Mapping) else None
        if not isinstance(analysis_page, Mapping) or analysis_page.get("page_number") != page_number:
            raise NettoCardRegionTopologyAuditError("analysis page identity mismatch")
        source_rows.extend(extract_fixture_topology(fixture, layout, analysis, module))

    cell_ids = {str(row["cell_id"]) for row in source_rows}
    if len(source_rows) != 100 or len(cell_ids) != 100:
        raise NettoCardRegionTopologyAuditError(
            "card-region topology audit requires exactly 100 unique cells"
        )

    # Independent ownership is deliberately loaded only after every source-derived
    # topology row is frozen.
    truth = OWNERSHIP.load_ownership_truth(ownership_truth_path, cell_ids)
    rows: list[dict[str, Any]] = []
    for row in source_rows:
        item = dict(row)
        item["independent_ownership"] = truth[str(row["cell_id"])]
        rows.append(item)

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
        "independent_ownership_counts": dict(
            sorted(Counter(truth.values()).items())
        ),
        "topology_by_independent_ownership": summarize_topology(rows),
        "cut_thresholds": list(CUT_THRESHOLDS),
        "interior_margin": INTERIOR_MARGIN,
        "truth_use_contract": "adjudication_only_after_source_topology_freeze",
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
        raise NettoCardRegionTopologyAuditError("output already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze read-only Netto N9 card-region topology evidence before "
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
    payload = replay_card_region_topology_audit(
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
                "topology_by_independent_ownership": payload[
                    "topology_by_independent_ownership"
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
