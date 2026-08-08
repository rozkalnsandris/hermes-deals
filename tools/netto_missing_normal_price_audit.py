from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal, InvalidOperation
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
BASE_REPLAY_TOOL = ROOT / "tools/netto_visual_geometry_corpus_replay.py"
STRATEGY = "netto_missing_normal_price_audit_v1"


class NettoMissingNormalPriceAuditError(ValueError):
    pass


def _load_base_replay() -> Any:
    spec = importlib.util.spec_from_file_location(
        "netto_missing_normal_price_base_replay",
        BASE_REPLAY_TOOL,
    )
    if spec is None or spec.loader is None:
        raise NettoMissingNormalPriceAuditError("cannot load base geometry replay")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BASE = _load_base_replay()


def _price(value: object) -> str | None:
    if value is None:
        return None
    try:
        parsed = Decimal(str(value).replace(",", ".")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None
    if parsed <= 0:
        return None
    return f"{parsed:.2f}"


def _bbox(value: object) -> tuple[float, float, float, float]:
    if not isinstance(value, Mapping):
        raise NettoMissingNormalPriceAuditError("bbox must be an object")
    try:
        x0, y0, x1, y1 = (float(value[key]) for key in ("x0", "y0", "x1", "y1"))
    except (KeyError, TypeError, ValueError) as exc:
        raise NettoMissingNormalPriceAuditError("bbox is invalid") from exc
    if not (x0 < x1 and y0 < y1):
        raise NettoMissingNormalPriceAuditError("bbox is empty")
    return x0, y0, x1, y1


def _center(box: tuple[float, float, float, float]) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def _contains(rect: tuple[float, float, float, float], point: tuple[float, float]) -> bool:
    return rect[0] <= point[0] < rect[2] and rect[1] <= point[1] < rect[3]


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({str(item) for item in value if str(item).strip()})


def diagnose_cell(
    cell: Mapping[str, Any],
    truth: Mapping[str, Any],
    base_row: Mapping[str, Any],
    analysis: Mapping[str, Any],
) -> dict[str, Any]:
    page = analysis.get("page")
    groups_raw = analysis.get("groups")
    anchors_raw = analysis.get("price_anchors")
    if not isinstance(page, Mapping) or not isinstance(groups_raw, list) or not isinstance(anchors_raw, list):
        raise NettoMissingNormalPriceAuditError("analysis page/groups/price_anchors shape invalid")
    width = float(page.get("width_points") or 0.0)
    height = float(page.get("height_points") or 0.0)
    if width <= 0 or height <= 0:
        raise NettoMissingNormalPriceAuditError("analysis page dimensions invalid")

    expected = _price(truth.get("expected_primary_price_eur"))
    if expected is None:
        raise NettoMissingNormalPriceAuditError("expected primary price missing")
    cell_rect = BASE.cell_rect(cell, width, height)

    groups: dict[str, Mapping[str, Any]] = {}
    for raw in groups_raw:
        if not isinstance(raw, Mapping):
            raise NettoMissingNormalPriceAuditError("analysis group must be an object")
        group_id = str(raw.get("group_id") or "").strip()
        if not group_id or group_id in groups:
            raise NettoMissingNormalPriceAuditError("analysis group ID missing or duplicate")
        groups[group_id] = raw

    expected_anchor_ids: list[str] = []
    anchor_source_kinds: dict[str, str] = {}
    for raw in anchors_raw:
        if not isinstance(raw, Mapping):
            raise NettoMissingNormalPriceAuditError("price anchor must be an object")
        anchor_id = str(raw.get("anchor_id") or "").strip()
        if not anchor_id:
            raise NettoMissingNormalPriceAuditError("price anchor ID missing")
        if _price(raw.get("value")) != expected:
            continue
        if not _contains(cell_rect, _center(_bbox(raw.get("bbox")))):
            continue
        expected_anchor_ids.append(anchor_id)
        anchor_source_kinds[anchor_id] = str(raw.get("source_kind") or "unknown")
    expected_anchor_ids = sorted(set(expected_anchor_ids))

    anchor_group_ids = sorted(
        group_id
        for group_id, group in groups.items()
        if set(expected_anchor_ids) & set(_string_list(group.get("anchor_ids")))
    )
    center_group_ids = _string_list(base_row.get("center_group_ids"))
    intersecting_group_ids = _string_list(base_row.get("intersecting_group_ids"))
    chosen_group_id = base_row.get("geometry_group_id")
    chosen = groups.get(str(chosen_group_id)) if chosen_group_id is not None else None

    center_normal_candidates = sorted(
        {
            price
            for group_id in center_group_ids
            for price in (_price(value) for value in _string_list(groups.get(group_id, {}).get("normal_price_candidates")))
            if price is not None
        }
    )
    center_member_candidates = sorted(
        {
            price
            for group_id in center_group_ids
            for price in (_price(value) for value in _string_list(groups.get(group_id, {}).get("member_price_candidates")))
            if price is not None
        }
    )

    selected = _price(chosen.get("selected_normal_price")) if chosen is not None else None
    chosen_normal_values = _string_list(chosen.get("normal_price_candidates")) if chosen is not None else []
    chosen_member_values = _string_list(chosen.get("member_price_candidates")) if chosen is not None else []
    chosen_normals = {
        price for price in (_price(value) for value in chosen_normal_values) if price is not None
    }
    chosen_members = {
        price for price in (_price(value) for value in chosen_member_values) if price is not None
    }

    if selected == expected:
        cause = "selected_normal_price_match"
    elif not expected_anchor_ids:
        cause = "expected_anchor_absent_in_cell"
    elif not anchor_group_ids:
        cause = "expected_anchor_unassigned_to_group"
    elif chosen is None:
        cause = "expected_anchor_present_binding_unresolved"
    elif str(chosen_group_id) not in anchor_group_ids:
        cause = "expected_anchor_owned_by_other_group"
    elif expected in chosen_members:
        cause = "expected_anchor_typed_member"
    elif expected in chosen_normals:
        cause = "expected_normal_candidate_not_selected"
    else:
        cause = "expected_anchor_in_bound_group_not_normal_candidate"

    return {
        "cell_id": str(cell.get("cell_id") or ""),
        "publication_slug": cell.get("publication_slug"),
        "page_number": cell.get("page_number"),
        "expected_normal_price": expected,
        "selected_normal_price": selected,
        "geometry_binding_state": base_row.get("geometry_binding_state"),
        "geometry_group_id": chosen_group_id,
        "center_group_ids": center_group_ids,
        "intersecting_group_ids": intersecting_group_ids,
        "expected_anchor_ids_in_cell": expected_anchor_ids,
        "expected_anchor_source_kinds": {
            key: anchor_source_kinds[key] for key in expected_anchor_ids
        },
        "expected_anchor_group_ids": anchor_group_ids,
        "center_group_normal_price_candidates": center_normal_candidates,
        "center_group_member_price_candidates": center_member_candidates,
        "diagnostic_cause": cause,
        "review_only": True,
        "promotion_ready": False,
    }


def audit_corpus(
    fixtures: Sequence[Mapping[str, Any]],
    n10: Mapping[str, Mapping[str, Any]],
    pdfs: Mapping[str, Path],
    geometry_module: Any | None = None,
) -> dict[str, Any]:
    module = geometry_module or BASE.load_geometry_module()
    rows: list[dict[str, Any]] = []

    for fixture in fixtures:
        page = fixture.get("page")
        cells = fixture.get("cells")
        if not isinstance(page, Mapping) or not isinstance(cells, list):
            raise NettoMissingNormalPriceAuditError("fixture page/cells shape invalid")
        campaign = str(page.get("publication_slug") or "")
        page_number = int(page.get("page_number") or 0)
        pdf_path = pdfs.get(campaign)
        if pdf_path is None:
            raise NettoMissingNormalPriceAuditError("fixture campaign PDF missing")
        layout = module.extract_layout_from_pdf(pdf_path, page_number)
        analysis = module.analyze_layout(layout)
        base_rows = BASE.map_fixture(fixture, analysis, n10)
        base_by_cell = {str(row["cell_id"]): row for row in base_rows}

        for raw_cell in cells:
            if not isinstance(raw_cell, Mapping):
                raise NettoMissingNormalPriceAuditError("fixture cell must be an object")
            cell_id = str(raw_cell.get("cell_id") or "")
            truth = n10.get(cell_id)
            base_row = base_by_cell.get(cell_id)
            if truth is None or base_row is None:
                raise NettoMissingNormalPriceAuditError("cell truth/base replay binding missing")
            rows.append(diagnose_cell(raw_cell, truth, base_row, analysis))

    if len(rows) != 100 or len({row["cell_id"] for row in rows}) != 100:
        raise NettoMissingNormalPriceAuditError("audit must contain exactly 100 unique cells")
    causes = Counter(str(row["diagnostic_cause"]) for row in rows)
    missing = [row for row in rows if row["diagnostic_cause"] != "selected_normal_price_match"]
    return {
        "schema_version": 1,
        "strategy": STRATEGY,
        "geometry_parser_identity": BASE.EXPECTED_GEOMETRY_PARSER,
        "source_archive_sha256": BASE.EXPECTED_SOURCE_ARCHIVE_SHA256,
        "source_n9_fixture_manifest_sha256": BASE.EXPECTED_N9_MANIFEST_SHA256,
        "source_n10_ledger_sha256": BASE.EXPECTED_N10_SHA256,
        "cell_count": 100,
        "diagnostic_cause_counts": dict(sorted(causes.items())),
        "missing_selected_normal_count": len(missing),
        "review_only_default": True,
        "promotion_ready": False,
        "automatic_approval_enabled": False,
        "automatic_publish_enabled": False,
        "database_write_performed": False,
        "deployment_performed": False,
        "rows": rows,
    }


def write_create_only(path: Path, payload: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise NettoMissingNormalPriceAuditError("output already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Classify missing Netto normal-price evidence without changing parser behavior."
    )
    parser.add_argument("--n9-manifest", type=Path, required=True)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--n10-ledger", type=Path, default=BASE.DEFAULT_N10)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    fixtures = BASE.load_exact_n9_manifest(args.n9_manifest)
    n10 = BASE.load_exact_n10(args.n10_ledger)
    pdfs = BASE.locate_exact_pdfs(args.corpus_root)
    payload = audit_corpus(fixtures, n10, pdfs)
    write_create_only(args.output, payload)
    print(json.dumps({
        "diagnostic_cause_counts": payload["diagnostic_cause_counts"],
        "missing_selected_normal_count": payload["missing_selected_normal_count"],
        "promotion_ready": payload["promotion_ready"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
