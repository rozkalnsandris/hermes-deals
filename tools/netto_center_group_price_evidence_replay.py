from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Callable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
BASE_REPLAY_TOOL = ROOT / "tools/netto_visual_geometry_corpus_replay.py"
STRATEGY = "netto_center_group_price_evidence_replay_v1"


class CenterGroupPriceEvidenceError(ValueError):
    pass


def _load_base_replay() -> Any:
    spec = importlib.util.spec_from_file_location(
        "netto_center_group_price_evidence_base_replay",
        BASE_REPLAY_TOOL,
    )
    if spec is None or spec.loader is None:
        raise CenterGroupPriceEvidenceError("cannot load base geometry replay")
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


def _bbox(group: Mapping[str, Any]) -> tuple[float, float, float, float]:
    raw = group.get("bbox")
    if not isinstance(raw, Mapping):
        raise CenterGroupPriceEvidenceError("geometry group bbox missing")
    try:
        x0, y0, x1, y1 = (
            float(raw[key]) for key in ("x0", "y0", "x1", "y1")
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CenterGroupPriceEvidenceError("invalid geometry group bbox") from exc
    if not (x0 < x1 and y0 < y1):
        raise CenterGroupPriceEvidenceError("empty geometry group bbox")
    return x0, y0, x1, y1


def _center(box: Sequence[float]) -> tuple[float, float]:
    return (float(box[0]) + float(box[2])) / 2.0, (
        float(box[1]) + float(box[3])
    ) / 2.0


def _contains_point(
    rect: Sequence[float],
    point: Sequence[float],
) -> bool:
    x0, y0, x1, y1 = (float(value) for value in rect)
    x, y = (float(value) for value in point)
    return x0 <= x < x1 and y0 <= y < y1


def _string_list(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    result = [_text(item) for item in value]
    return sorted(item for item in result if item is not None)


def group_price_evidence(group: Mapping[str, Any]) -> dict[str, Any]:
    group_id = _text(group.get("group_id"))
    if group_id is None:
        raise CenterGroupPriceEvidenceError("geometry group ID missing")
    return {
        "group_id": group_id,
        "selected_normal_price": _text(group.get("selected_normal_price")),
        "selected_member_price": _text(group.get("selected_member_price")),
        "normal_price_candidates": _string_list(group.get("normal_price_candidates")),
        "member_price_candidates": _string_list(group.get("member_price_candidates")),
        "route": _text(group.get("route")),
        "reasons": _string_list(group.get("reasons")),
    }


def build_fixture_evidence(
    fixture: Mapping[str, Any],
    analysis: Mapping[str, Any],
) -> list[dict[str, Any]]:
    page_meta = analysis.get("page")
    groups = analysis.get("groups")
    if not isinstance(page_meta, Mapping) or not isinstance(groups, list):
        raise CenterGroupPriceEvidenceError("geometry analysis page/groups shape invalid")

    width = float(page_meta.get("width_points") or 0.0)
    height = float(page_meta.get("height_points") or 0.0)
    if width <= 0 or height <= 0:
        raise CenterGroupPriceEvidenceError("geometry analysis page dimensions invalid")

    prepared: dict[str, tuple[tuple[float, float, float, float], Mapping[str, Any]]] = {}
    for raw_group in groups:
        if not isinstance(raw_group, Mapping):
            raise CenterGroupPriceEvidenceError("geometry group must be an object")
        group_id = _text(raw_group.get("group_id"))
        if group_id is None or group_id in prepared:
            raise CenterGroupPriceEvidenceError("geometry group IDs must be unique")
        prepared[group_id] = (_bbox(raw_group), raw_group)

    cells = fixture.get("cells")
    if not isinstance(cells, list):
        raise CenterGroupPriceEvidenceError("fixture cells missing")

    rows: list[dict[str, Any]] = []
    provisional: dict[str, str] = {}

    for raw_cell in cells:
        if not isinstance(raw_cell, Mapping):
            raise CenterGroupPriceEvidenceError("fixture cell must be an object")
        cell = dict(raw_cell)
        cell_id = _text(cell.get("cell_id"))
        if cell_id is None:
            raise CenterGroupPriceEvidenceError("cell ID missing")

        rect = BASE.cell_rect(cell, width, height)
        center_ids = sorted(
            group_id
            for group_id, (box, _group) in prepared.items()
            if _contains_point(rect, _center(box))
        )
        scope_excluded = cell.get("scope_state") == "excluded_non_target_card"

        chosen_id: str | None = None
        if scope_excluded:
            binding_state = "excluded_scope_control"
        elif len(center_ids) == 1:
            binding_state = "single_center_group"
            chosen_id = center_ids[0]
            provisional[cell_id] = chosen_id
        elif not center_ids:
            binding_state = "no_center_group_review_required"
        else:
            binding_state = "multiple_center_groups_review_required"

        rows.append(
            {
                "cell_id": cell_id,
                "publication_slug": cell.get("publication_slug"),
                "page_number": cell.get("page_number"),
                "geometry_binding_state": binding_state,
                "geometry_group_id": chosen_id,
                "center_group_ids": center_ids,
                "center_group_price_evidence": []
                if scope_excluded
                else [
                    group_price_evidence(prepared[group_id][1])
                    for group_id in center_ids
                ],
                "review_only": True,
                "promotion_ready": False,
            }
        )

    users: defaultdict[str, list[str]] = defaultdict(list)
    for cell_id, group_id in provisional.items():
        users[group_id].append(cell_id)
    reused = {group_id for group_id, cell_ids in users.items() if len(cell_ids) > 1}

    for row in rows:
        chosen_id = row["geometry_group_id"]
        if chosen_id in reused:
            row["geometry_binding_state"] = "cross_cell_group_reuse_review_required"
            row["geometry_group_id"] = None

    return rows


def replay_center_group_price_evidence(
    fixtures: Sequence[Mapping[str, Any]],
    pdfs: Mapping[str, Path],
    *,
    geometry_module: Any | None = None,
    analyze_page: Callable[[Path, int], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    module = geometry_module or BASE.load_geometry_module()
    if analyze_page is None:
        def analyze_page(pdf_path: Path, page_number: int) -> Mapping[str, Any]:
            layout = module.extract_layout_from_pdf(pdf_path, page_number)
            return module.analyze_layout(layout)

    rows: list[dict[str, Any]] = []
    rotations: Counter[int] = Counter()
    for fixture in fixtures:
        page = fixture.get("page")
        if not isinstance(page, Mapping):
            raise CenterGroupPriceEvidenceError("fixture page metadata missing")
        campaign = _text(page.get("publication_slug"))
        page_number = page.get("page_number")
        if campaign not in BASE.CAMPAIGN_PDFS or not isinstance(page_number, int):
            raise CenterGroupPriceEvidenceError("fixture page identity invalid")
        analysis = analyze_page(pdfs[campaign], page_number)
        analysis_page = analysis.get("page") if isinstance(analysis, Mapping) else None
        if not isinstance(analysis_page, Mapping):
            raise CenterGroupPriceEvidenceError("analysis page metadata missing")
        if analysis_page.get("page_number") != page_number:
            raise CenterGroupPriceEvidenceError("analysis page-number mismatch")
        rotations[int(analysis_page.get("rotation") or 0)] += 1
        rows.extend(build_fixture_evidence(fixture, analysis))

    if len(rows) != 100 or len({row["cell_id"] for row in rows}) != 100:
        raise CenterGroupPriceEvidenceError(
            "price-evidence replay must contain exactly 100 unique cells"
        )

    states = Counter(row["geometry_binding_state"] for row in rows)
    return {
        "schema_version": 1,
        "strategy": STRATEGY,
        "geometry_parser_identity": BASE.EXPECTED_GEOMETRY_PARSER,
        "source_archive_sha256": BASE.EXPECTED_SOURCE_ARCHIVE_SHA256,
        "source_n9_fixture_manifest_sha256": BASE.EXPECTED_N9_MANIFEST_SHA256,
        "campaign_pdf_sha256": {
            campaign: values["pdf_sha256"]
            for campaign, values in sorted(BASE.CAMPAIGN_PDFS.items())
        },
        "fixture_page_count": 17,
        "cell_count": 100,
        "page_rotation_counts": {
            str(key): value for key, value in sorted(rotations.items())
        },
        "geometry_binding_counts": dict(sorted(states.items())),
        "review_only": True,
        "promotion_ready": False,
        "automatic_approval_enabled": False,
        "automatic_publish_enabled": False,
        "database_write_performed": False,
        "rows": rows,
    }


def write_create_only(path: Path, payload: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise CenterGroupPriceEvidenceError("output already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Replay exact Netto geometry and expose bounded per-center-group "
            "normal/member price evidence without changing binding decisions."
        )
    )
    parser.add_argument("--n9-manifest", type=Path, required=True)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    fixtures = BASE.load_exact_n9_manifest(args.n9_manifest)
    pdfs = BASE.locate_exact_pdfs(args.corpus_root)
    payload = replay_center_group_price_evidence(fixtures, pdfs)
    write_create_only(args.output, payload)
    print(
        json.dumps(
            {
                "strategy": payload["strategy"],
                "fixture_page_count": payload["fixture_page_count"],
                "cell_count": payload["cell_count"],
                "geometry_binding_counts": payload["geometry_binding_counts"],
                "promotion_ready": payload["promotion_ready"],
                "database_write_performed": payload["database_write_performed"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
