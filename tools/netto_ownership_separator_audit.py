from __future__ import annotations

import argparse
from collections import Counter
from itertools import combinations
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
BASE_REPLAY_TOOL = ROOT / "tools/netto_visual_geometry_corpus_replay.py"
DEFAULT_OWNERSHIP_TRUTH = (
    ROOT / "backend/tests/fixtures/netto/n2_independent_ownership_summary_v1.json"
)
STRATEGY = "netto_ownership_separator_audit_v1"


class NettoOwnershipSeparatorAuditError(ValueError):
    pass


def _load_base_replay() -> Any:
    spec = importlib.util.spec_from_file_location(
        "netto_ownership_separator_base_replay",
        BASE_REPLAY_TOOL,
    )
    if spec is None or spec.loader is None:
        raise NettoOwnershipSeparatorAuditError("cannot load base geometry replay")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BASE = _load_base_replay()


def _text(value: object) -> str | None:
    if value is None:
        return None
    result = " ".join(str(value).split()).strip()
    return result or None


def _bbox(group: Mapping[str, Any], geometry_module: Any) -> Any:
    raw = group.get("bbox")
    if not isinstance(raw, Mapping):
        raise NettoOwnershipSeparatorAuditError("geometry group bbox missing")
    try:
        box = geometry_module.Box(
            float(raw["x0"]),
            float(raw["y0"]),
            float(raw["x1"]),
            float(raw["y1"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise NettoOwnershipSeparatorAuditError("invalid geometry group bbox") from exc
    if box.area <= 0:
        raise NettoOwnershipSeparatorAuditError("empty geometry group bbox")
    return box


def _cell_box(cell: Mapping[str, Any], width: float, height: float, geometry_module: Any) -> Any:
    rect = BASE.cell_rect(cell, width, height)
    return geometry_module.Box(*(float(value) for value in rect))


def _center_in_cell(cell_box: Any, group_box: Any) -> bool:
    return cell_box.contains_point(group_box.cx, group_box.cy)


def _normalized_pair_metrics(left: Any, right: Any, cell_box: Any) -> dict[str, float]:
    dx = abs(left.cx - right.cx)
    dy = abs(left.cy - right.cy)
    diagonal = math.hypot(cell_box.width, cell_box.height)
    distance = math.hypot(dx, dy)
    return {
        "dx_cell_width": round(dx / max(cell_box.width, 0.001), 6),
        "dy_cell_height": round(dy / max(cell_box.height, 0.001), 6),
        "distance_cell_diagonal": round(distance / max(diagonal, 0.001), 6),
    }


def classify_center_groups(
    center_group_ids: Sequence[str],
    separated_pairs: Sequence[tuple[str, str]],
    *,
    scope_excluded: bool,
) -> tuple[str, list[str]]:
    """Classify N9-cell ownership without consulting independent review truth.

    N9 is the authoritative candidate-cell boundary. Multiple parser price groups
    inside one N9 cell are treated as one ownership cluster only when no detected
    source separator lies between any pair of their centers. A detected separator
    keeps the cell fail-closed as multiple ownership clusters.
    """

    group_ids = sorted(set(str(value) for value in center_group_ids))
    if scope_excluded:
        return "excluded_scope_control", []
    if not group_ids:
        return "no_center_group_review_required", []
    if len(group_ids) == 1:
        return "single_ownership_cluster", group_ids
    if separated_pairs:
        return "multiple_ownership_clusters_review_required", []
    return "single_ownership_cluster_coalesced", group_ids


def _price_list(group: Mapping[str, Any], key: str) -> list[str]:
    raw = group.get(key)
    if not isinstance(raw, list):
        return []
    return sorted({value for item in raw if (value := _text(item)) is not None})


def audit_fixture(
    fixture: Mapping[str, Any],
    layout: Mapping[str, Any],
    analysis: Mapping[str, Any],
    geometry_module: Any,
) -> list[dict[str, Any]]:
    """Build source-derived ownership evidence for one page.

    This function deliberately has no independent-review/truth parameter. It may
    use only N9 cell geometry, parser group geometry and source separators.
    """

    page = analysis.get("page")
    groups = analysis.get("groups")
    cells = fixture.get("cells")
    if not isinstance(page, Mapping) or not isinstance(groups, list):
        raise NettoOwnershipSeparatorAuditError("geometry analysis page/groups shape invalid")
    if not isinstance(cells, list):
        raise NettoOwnershipSeparatorAuditError("fixture cells missing")

    width = float(page.get("width_points") or 0.0)
    height = float(page.get("height_points") or 0.0)
    if width <= 0 or height <= 0:
        raise NettoOwnershipSeparatorAuditError("geometry page dimensions invalid")

    separators = geometry_module.separators_from_layout(layout)
    prepared: dict[str, tuple[Any, Mapping[str, Any]]] = {}
    for raw_group in groups:
        if not isinstance(raw_group, Mapping):
            raise NettoOwnershipSeparatorAuditError("geometry group must be an object")
        group_id = _text(raw_group.get("group_id"))
        if group_id is None or group_id in prepared:
            raise NettoOwnershipSeparatorAuditError("geometry group IDs must be unique")
        prepared[group_id] = (_bbox(raw_group, geometry_module), raw_group)

    rows: list[dict[str, Any]] = []
    for raw_cell in cells:
        if not isinstance(raw_cell, Mapping):
            raise NettoOwnershipSeparatorAuditError("fixture cell must be an object")
        cell = dict(raw_cell)
        cell_id = _text(cell.get("cell_id"))
        if cell_id is None:
            raise NettoOwnershipSeparatorAuditError("cell ID missing")
        cell_box = _cell_box(cell, width, height, geometry_module)

        center_group_ids = sorted(
            group_id
            for group_id, (group_box, _group) in prepared.items()
            if _center_in_cell(cell_box, group_box)
        )

        pair_evidence: list[dict[str, Any]] = []
        separated_pairs: list[tuple[str, str]] = []
        for left_id, right_id in combinations(center_group_ids, 2):
            left = prepared[left_id][0]
            right = prepared[right_id][0]
            is_separated = bool(geometry_module.separated(left, right, separators))
            if is_separated:
                separated_pairs.append((left_id, right_id))
            pair_evidence.append(
                {
                    "left_group_id": left_id,
                    "right_group_id": right_id,
                    "separator_between": is_separated,
                    **_normalized_pair_metrics(left, right, cell_box),
                }
            )

        scope_excluded = cell.get("scope_state") == "excluded_non_target_card"
        candidate_binding, ownership_group_ids = classify_center_groups(
            center_group_ids,
            separated_pairs,
            scope_excluded=scope_excluded,
        )

        if scope_excluded:
            current_binding = "excluded_scope_control"
        elif len(center_group_ids) == 1:
            current_binding = "single_center_group"
        elif not center_group_ids:
            current_binding = "no_center_group_review_required"
        else:
            current_binding = "multiple_center_groups_review_required"

        group_evidence = []
        for group_id in center_group_ids:
            group_box, group = prepared[group_id]
            group_evidence.append(
                {
                    "group_id": group_id,
                    "bbox": {
                        "x0": round(group_box.x0, 3),
                        "y0": round(group_box.y0, 3),
                        "x1": round(group_box.x1, 3),
                        "y1": round(group_box.y1, 3),
                    },
                    "route": _text(group.get("route")),
                    "reasons": sorted(
                        value
                        for item in (group.get("reasons") or [])
                        if (value := _text(item)) is not None
                    ),
                    "normal_price_candidates": _price_list(group, "normal_price_candidates"),
                    "member_price_candidates": _price_list(group, "member_price_candidates"),
                    "selected_normal_price": _text(group.get("selected_normal_price")),
                    "selected_member_price": _text(group.get("selected_member_price")),
                }
            )

        rows.append(
            {
                "cell_id": cell_id,
                "publication_slug": cell.get("publication_slug"),
                "page_number": cell.get("page_number"),
                "scope_state": cell.get("scope_state"),
                "current_binding": current_binding,
                "candidate_ownership_binding": candidate_binding,
                "center_group_ids": center_group_ids,
                "ownership_group_ids": ownership_group_ids,
                "center_group_count": len(center_group_ids),
                "separator_pair_count": len(separated_pairs),
                "pair_evidence": pair_evidence,
                "group_evidence": group_evidence,
                "review_only": True,
                "promotion_ready": False,
            }
        )
    return rows


def load_ownership_truth(
    path: Path,
    fixture_cell_ids: set[str],
) -> dict[str, str]:
    if path.is_symlink() or not path.is_file():
        raise NettoOwnershipSeparatorAuditError("ownership truth must be a regular file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise NettoOwnershipSeparatorAuditError("invalid ownership truth JSON") from exc
    if not isinstance(payload, Mapping):
        raise NettoOwnershipSeparatorAuditError("ownership truth root must be an object")
    required = {
        "strategy": "netto_n2_independent_ownership_summary_v1",
        "source_completed_independent_ledger_sha256": "2fb5c5675d2b05b53da1f37cf4d1f66d32d152f3c7d77c0786d0400b5d30330a",
        "source_adjudication_sha256": "59319ade8a5164b036a4f68474c36d46568c09dd9034e380c6928c15d2331088",
        "source_n9_fixture_manifest_sha256": BASE.EXPECTED_N9_MANIFEST_SHA256,
        "cell_count": 100,
        "single_source_count": 88,
        "mixed_source_count": 10,
        "excluded_control_count": 2,
        "truth_use_contract": "adjudication_only_not_parser_or_geometry_selection",
    }
    for key, expected in required.items():
        if payload.get(key) != expected:
            raise NettoOwnershipSeparatorAuditError(f"ownership truth drift: {key}")

    mixed = payload.get("mixed_cell_ids")
    excluded = payload.get("excluded_control_cell_ids")
    if not isinstance(mixed, list) or not isinstance(excluded, list):
        raise NettoOwnershipSeparatorAuditError("ownership truth ID lists missing")
    mixed_ids = {str(value) for value in mixed}
    excluded_ids = {str(value) for value in excluded}
    if len(mixed_ids) != 10 or len(excluded_ids) != 2 or mixed_ids & excluded_ids:
        raise NettoOwnershipSeparatorAuditError("ownership truth ID counts invalid")
    if not (mixed_ids | excluded_ids) <= fixture_cell_ids:
        raise NettoOwnershipSeparatorAuditError("ownership truth references unknown N9 cells")

    result = {
        cell_id: (
            "mixed_source"
            if cell_id in mixed_ids
            else "excluded_control"
            if cell_id in excluded_ids
            else "single_source"
        )
        for cell_id in fixture_cell_ids
    }
    counts = Counter(result.values())
    if counts != Counter({"single_source": 88, "mixed_source": 10, "excluded_control": 2}):
        raise NettoOwnershipSeparatorAuditError("ownership truth derived counts invalid")
    return result


def _score(rows: Sequence[Mapping[str, Any]], truth: Mapping[str, str]) -> dict[str, Any]:
    tp = fp = tn = fn = 0
    mixed_review_only_count = 0
    for row in rows:
        cell_id = str(row["cell_id"])
        state = truth[cell_id]
        if state == "excluded_control":
            continue
        predicted_mixed = row["candidate_ownership_binding"] == "multiple_ownership_clusters_review_required"
        actual_mixed = state == "mixed_source"
        if actual_mixed and predicted_mixed:
            tp += 1
        elif actual_mixed:
            fn += 1
        elif predicted_mixed:
            fp += 1
        else:
            tn += 1
        if actual_mixed and row.get("review_only") is True and row.get("promotion_ready") is False:
            mixed_review_only_count += 1

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "mixed_review_only_count": mixed_review_only_count,
    }


def replay_ownership_separator_audit(
    fixtures: Sequence[Mapping[str, Any]],
    pdfs: Mapping[str, Path],
    *,
    ownership_truth_path: Path = DEFAULT_OWNERSHIP_TRUTH,
    geometry_module: Any | None = None,
) -> dict[str, Any]:
    module = geometry_module or BASE.load_geometry_module()
    rows: list[dict[str, Any]] = []
    for fixture in fixtures:
        page = fixture.get("page")
        if not isinstance(page, Mapping):
            raise NettoOwnershipSeparatorAuditError("fixture page metadata missing")
        campaign = _text(page.get("publication_slug"))
        page_number = page.get("page_number")
        if campaign not in BASE.CAMPAIGN_PDFS or not isinstance(page_number, int):
            raise NettoOwnershipSeparatorAuditError("fixture page identity invalid")
        layout = module.extract_layout_from_pdf(pdfs[campaign], page_number)
        analysis = module.analyze_layout(layout)
        analysis_page = analysis.get("page") if isinstance(analysis, Mapping) else None
        if not isinstance(analysis_page, Mapping) or analysis_page.get("page_number") != page_number:
            raise NettoOwnershipSeparatorAuditError("analysis page identity mismatch")
        rows.extend(audit_fixture(fixture, layout, analysis, module))

    fixture_cell_ids = {str(row["cell_id"]) for row in rows}
    if len(rows) != 100 or len(fixture_cell_ids) != 100:
        raise NettoOwnershipSeparatorAuditError("ownership audit must contain exactly 100 unique cells")
    truth = load_ownership_truth(ownership_truth_path, fixture_cell_ids)

    current_counts = Counter(row["current_binding"] for row in rows)
    candidate_counts = Counter(row["candidate_ownership_binding"] for row in rows)
    truth_counts = Counter(truth.values())
    coalesced = sum(
        row["candidate_ownership_binding"] == "single_ownership_cluster_coalesced"
        for row in rows
    )

    adjudicated_rows = []
    for row in rows:
        item = dict(row)
        item["independent_ownership"] = truth[str(row["cell_id"])]
        adjudicated_rows.append(item)

    return {
        "schema_version": 1,
        "strategy": STRATEGY,
        "geometry_parser_identity": BASE.EXPECTED_GEOMETRY_PARSER,
        "source_archive_sha256": BASE.EXPECTED_SOURCE_ARCHIVE_SHA256,
        "source_n9_fixture_manifest_sha256": BASE.EXPECTED_N9_MANIFEST_SHA256,
        "source_completed_independent_ledger_sha256": "2fb5c5675d2b05b53da1f37cf4d1f66d32d152f3c7d77c0786d0400b5d30330a",
        "source_adjudication_sha256": "59319ade8a5164b036a4f68474c36d46568c09dd9034e380c6928c15d2331088",
        "fixture_page_count": 17,
        "cell_count": 100,
        "independent_ownership_counts": dict(sorted(truth_counts.items())),
        "current_binding_counts": dict(sorted(current_counts.items())),
        "candidate_ownership_binding_counts": dict(sorted(candidate_counts.items())),
        "coalesced_multiple_group_cell_count": coalesced,
        "candidate_vs_independent": _score(adjudicated_rows, truth),
        "truth_use_contract": "adjudication_only_not_parser_or_geometry_selection",
        "review_only": True,
        "promotion_ready": False,
        "automatic_approval_enabled": False,
        "automatic_publish_enabled": False,
        "database_write_performed": False,
        "rows": adjudicated_rows,
    }


def write_create_only(path: Path, payload: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise NettoOwnershipSeparatorAuditError("output already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Audit candidate Netto N9-cell ownership using only parser group geometry "
            "and source separators, then adjudicate against frozen independent ownership."
        )
    )
    parser.add_argument("--n9-manifest", type=Path, required=True)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--ownership-truth", type=Path, default=DEFAULT_OWNERSHIP_TRUTH)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    fixtures = BASE.load_exact_n9_manifest(args.n9_manifest)
    pdfs = BASE.locate_exact_pdfs(args.corpus_root)
    payload = replay_ownership_separator_audit(
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
                "current_binding_counts": payload["current_binding_counts"],
                "candidate_ownership_binding_counts": payload["candidate_ownership_binding_counts"],
                "coalesced_multiple_group_cell_count": payload["coalesced_multiple_group_cell_count"],
                "candidate_vs_independent": payload["candidate_vs_independent"],
                "promotion_ready": payload["promotion_ready"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
