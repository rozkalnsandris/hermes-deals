from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Any, Callable, Mapping, Sequence
import unicodedata


ROOT = Path(__file__).resolve().parents[1]
GEOMETRY_TOOL = ROOT / "tools/netto_visual_geometry_shadow.py"
DEFAULT_N10 = ROOT / "backend/tests/fixtures/netto/n10_full_visual_review_v1.json"

EXPECTED_SOURCE_ARCHIVE_SHA256 = (
    "882d61ad18ddca13680b97c0a27adf1a1db7874cabe337b61fc3ebc9b9d329f2"
)
EXPECTED_N9_MANIFEST_SHA256 = (
    "2b180d67af4c5d1e586704088e3d685cff21ae2e12f3052254daf4553dd4e147"
)
EXPECTED_N10_SHA256 = (
    "bf35bff323d76a2b29a7248df067641e5b9f2a7d29329cf53bf9fc0ae832734a"
)
EXPECTED_N10_BYTES = 104385
EXPECTED_GEOMETRY_PARSER = "netto-visual-geometry-shadow-v3-unrotated-page-space"
EXPECTED_CAMPAIGN_COUNTS = {"hz31_hasb_4": 26, "hz32_hasb": 74}
CAMPAIGN_PDFS = {
    "hz31_hasb_4": {
        "pdf_sha256": "9e878399868bd3ff5422954e7547ea68cfd2a518209ed01c96940a0eafb258ca",
        "page_count": 76,
    },
    "hz32_hasb": {
        "pdf_sha256": "f87bb55bc735ecd7fbbf0735ad848615b30a543639a94265464d1c57e621cb36",
        "page_count": 49,
    },
}


class GeometryCorpusReplayError(ValueError):
    pass


def sha_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    if path.is_symlink() or not path.is_file():
        raise GeometryCorpusReplayError(f"input must be a regular file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GeometryCorpusReplayError(f"invalid UTF-8 JSON: {path}") from exc


def _text(value: Any) -> str | None:
    if value is None:
        return None
    result = " ".join(str(value).split()).strip()
    return result or None


def _normalized_title(value: Any) -> str | None:
    text = _text(value)
    if text is None:
        return None
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(part for part in re.split(r"[^\w]+", normalized) if part)


def _price(value: Any) -> Decimal | None:
    text = _text(value)
    if text is None:
        return None
    try:
        parsed = Decimal(text.replace(",", ".")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise GeometryCorpusReplayError(f"invalid price: {value!r}") from exc
    if parsed < 0:
        raise GeometryCorpusReplayError(f"invalid price: {value!r}")
    return parsed


def _require_false(payload: Mapping[str, Any], keys: Sequence[str], label: str) -> None:
    for key in keys:
        if payload.get(key) is not False:
            raise GeometryCorpusReplayError(f"{label}.{key} must be false")


def validate_n9_manifest(fixtures: Any) -> list[dict[str, Any]]:
    if not isinstance(fixtures, list) or len(fixtures) != 17:
        raise GeometryCorpusReplayError("N9 manifest must contain exactly 17 fixtures")

    seen_pages: set[tuple[str, int]] = set()
    seen_cells: set[str] = set()
    campaign_counts: Counter[str] = Counter()
    zero_cell_pages = 0
    normalized: list[dict[str, Any]] = []

    for fixture in fixtures:
        if not isinstance(fixture, Mapping):
            raise GeometryCorpusReplayError("N9 fixture must be an object")
        if fixture.get("strategy") != "netto_n9_n8_v2_visual_cell_fixture_v1":
            raise GeometryCorpusReplayError("unexpected N9 fixture strategy")
        if fixture.get("review_state") != "pending_visual_validation":
            raise GeometryCorpusReplayError("N9 fixture review state drift")
        if fixture.get("automatic_approval_count") != 0 or fixture.get("automatic_publish_count") != 0:
            raise GeometryCorpusReplayError("N9 fixture contains automatic approval/publication")
        if fixture.get("production_write_performed") is not False:
            raise GeometryCorpusReplayError("N9 fixture production-write flag drift")

        page = fixture.get("page")
        cells = fixture.get("cells")
        if not isinstance(page, Mapping) or not isinstance(cells, list):
            raise GeometryCorpusReplayError("N9 fixture page/cells shape is invalid")
        campaign = _text(page.get("publication_slug"))
        page_number = page.get("page_number")
        if campaign not in EXPECTED_CAMPAIGN_COUNTS:
            raise GeometryCorpusReplayError("N9 fixture campaign drift")
        if not isinstance(page_number, int) or page_number <= 0:
            raise GeometryCorpusReplayError("N9 fixture page number is invalid")
        page_key = (campaign, page_number)
        if page_key in seen_pages:
            raise GeometryCorpusReplayError("duplicate N9 fixture page")
        seen_pages.add(page_key)
        if not cells:
            zero_cell_pages += 1

        for cell in cells:
            if not isinstance(cell, Mapping):
                raise GeometryCorpusReplayError("N9 cell must be an object")
            cell_id = _text(cell.get("cell_id"))
            if not cell_id or cell_id in seen_cells:
                raise GeometryCorpusReplayError("N9 cell IDs must be unique")
            if cell.get("publication_slug") != campaign or cell.get("page_number") != page_number:
                raise GeometryCorpusReplayError("N9 cell page identity drift")
            if cell.get("review_state") != "pending_visual_validation":
                raise GeometryCorpusReplayError("N9 cell review state drift")
            if cell.get("automatic_approval_allowed") is not False or cell.get("automatic_publish_allowed") is not False:
                raise GeometryCorpusReplayError("N9 cell automatic action drift")
            coords = []
            for key in ("region_x0", "region_y0", "region_x1", "region_y1"):
                try:
                    coords.append(float(cell[key]))
                except (KeyError, TypeError, ValueError) as exc:
                    raise GeometryCorpusReplayError(f"invalid N9 cell geometry: {cell_id}") from exc
            x0, y0, x1, y1 = coords
            if not (0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0):
                raise GeometryCorpusReplayError(f"N9 cell geometry outside normalized page: {cell_id}")
            seen_cells.add(cell_id)
            campaign_counts[campaign] += 1

        if page.get("raw_cell_count") != len(cells):
            raise GeometryCorpusReplayError("N9 page raw-cell count drift")

        normalized.append(dict(fixture))

    if len(seen_cells) != 100:
        raise GeometryCorpusReplayError("N9 manifest must contain exactly 100 unique cells")
    if dict(campaign_counts) != EXPECTED_CAMPAIGN_COUNTS:
        raise GeometryCorpusReplayError("N9 campaign cell counts drift")
    if zero_cell_pages != 6:
        raise GeometryCorpusReplayError("N9 zero-cell control page count drift")
    return normalized


def load_exact_n9_manifest(path: Path) -> list[dict[str, Any]]:
    if sha_file(path) != EXPECTED_N9_MANIFEST_SHA256:
        raise GeometryCorpusReplayError("N9 fixture-manifest SHA256 mismatch")
    return validate_n9_manifest(load_json(path))


def validate_n10(payload: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, Mapping):
        raise GeometryCorpusReplayError("N10 root must be an object")
    if payload.get("source_n9_fixture_manifest_sha256") != EXPECTED_N9_MANIFEST_SHA256:
        raise GeometryCorpusReplayError("N10 N9-manifest binding mismatch")
    if payload.get("reviewed_page_count") != 17 or payload.get("reviewed_cell_count") != 100:
        raise GeometryCorpusReplayError("N10 page/cell counts drift")
    _require_false(
        payload,
        ("automatic_approval", "automatic_publish", "production_write_performed"),
        "N10",
    )
    rows = payload.get("cell_reviews")
    if not isinstance(rows, list) or len(rows) != 100:
        raise GeometryCorpusReplayError("N10 must contain exactly 100 cell reviews")

    result: dict[str, dict[str, Any]] = {}
    counts: Counter[str] = Counter()
    for row in rows:
        if not isinstance(row, Mapping):
            raise GeometryCorpusReplayError("N10 review row must be an object")
        cell_id = _text(row.get("cell_id"))
        campaign = _text(row.get("publication_slug"))
        page_number = row.get("page_number")
        if not cell_id or cell_id in result:
            raise GeometryCorpusReplayError("N10 cell IDs must be unique")
        if campaign not in EXPECTED_CAMPAIGN_COUNTS:
            raise GeometryCorpusReplayError("N10 campaign drift")
        if not isinstance(page_number, int) or page_number <= 0:
            raise GeometryCorpusReplayError("N10 page number is invalid")
        if row.get("automatic_approval_allowed") is not False or row.get("automatic_publish_allowed") is not False:
            raise GeometryCorpusReplayError("N10 automatic action drift")
        result[cell_id] = dict(row)
        counts[campaign] += 1
    if dict(counts) != EXPECTED_CAMPAIGN_COUNTS:
        raise GeometryCorpusReplayError("N10 campaign counts drift")
    return result


def load_exact_n10(path: Path = DEFAULT_N10) -> dict[str, dict[str, Any]]:
    if path.stat().st_size != EXPECTED_N10_BYTES or sha_file(path) != EXPECTED_N10_SHA256:
        raise GeometryCorpusReplayError("N10 raw ledger identity mismatch")
    return validate_n10(load_json(path))


def locate_exact_pdfs(corpus_root: Path) -> dict[str, Path]:
    if corpus_root.is_symlink() or not corpus_root.is_dir():
        raise GeometryCorpusReplayError("corpus root must be a regular directory")
    found: dict[str, Path] = {}
    for manifest_path in sorted(corpus_root.glob("*/corpus-manifest.json")):
        if manifest_path.is_symlink() or not manifest_path.is_file():
            continue
        manifest = load_json(manifest_path)
        if not isinstance(manifest, Mapping):
            continue
        campaign = _text(manifest.get("publication_slug"))
        if campaign not in CAMPAIGN_PDFS:
            continue
        if campaign in found:
            raise GeometryCorpusReplayError(f"duplicate corpus campaign: {campaign}")
        pdf_path = manifest_path.parent / "source.pdf"
        if pdf_path.is_symlink() or not pdf_path.is_file():
            raise GeometryCorpusReplayError(f"corpus PDF missing: {campaign}")
        expected = CAMPAIGN_PDFS[campaign]
        if sha_file(pdf_path) != expected["pdf_sha256"]:
            raise GeometryCorpusReplayError(f"corpus PDF SHA256 mismatch: {campaign}")
        if manifest.get("pdf_sha256") not in (None, expected["pdf_sha256"]):
            raise GeometryCorpusReplayError(f"corpus manifest PDF SHA drift: {campaign}")
        if manifest.get("page_count") not in (None, expected["page_count"]):
            raise GeometryCorpusReplayError(f"corpus manifest page-count drift: {campaign}")
        found[campaign] = pdf_path
    if set(found) != set(CAMPAIGN_PDFS):
        raise GeometryCorpusReplayError("both authoritative Netto campaign PDFs are required")
    return found


def load_geometry_module() -> Any:
    spec = importlib.util.spec_from_file_location("netto_geometry_corpus_replay_parser", GEOMETRY_TOOL)
    if spec is None or spec.loader is None:
        raise GeometryCorpusReplayError("cannot load geometry parser")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if getattr(module, "PARSER_IDENTITY", None) != EXPECTED_GEOMETRY_PARSER:
        raise GeometryCorpusReplayError("geometry parser identity mismatch")
    return module


def cell_rect(cell: Mapping[str, Any], width: float, height: float) -> tuple[float, float, float, float]:
    if width <= 0 or height <= 0:
        raise GeometryCorpusReplayError("page dimensions must be positive")
    return (
        float(cell["region_x0"]) * width,
        float(cell["region_y0"]) * height,
        float(cell["region_x1"]) * width,
        float(cell["region_y1"]) * height,
    )


def _bbox(group: Mapping[str, Any]) -> tuple[float, float, float, float]:
    raw = group.get("bbox")
    if not isinstance(raw, Mapping):
        raise GeometryCorpusReplayError("geometry group bbox missing")
    try:
        x0, y0, x1, y1 = (float(raw[key]) for key in ("x0", "y0", "x1", "y1"))
    except (KeyError, TypeError, ValueError) as exc:
        raise GeometryCorpusReplayError("invalid geometry group bbox") from exc
    if not (x0 < x1 and y0 < y1):
        raise GeometryCorpusReplayError("empty geometry group bbox")
    return x0, y0, x1, y1


def _center(box: tuple[float, float, float, float]) -> tuple[float, float]:
    x0, y0, x1, y1 = box
    return (x0 + x1) / 2.0, (y0 + y1) / 2.0


def _contains_point(rect: tuple[float, float, float, float], point: tuple[float, float]) -> bool:
    x0, y0, x1, y1 = rect
    x, y = point
    return x0 <= x < x1 and y0 <= y < y1


def _intersects(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3])


def map_fixture(
    fixture: Mapping[str, Any],
    analysis: Mapping[str, Any],
    n10: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    page_meta = analysis.get("page")
    groups = analysis.get("groups")
    if not isinstance(page_meta, Mapping) or not isinstance(groups, list):
        raise GeometryCorpusReplayError("geometry analysis page/groups shape invalid")
    width = float(page_meta.get("width_points") or 0.0)
    height = float(page_meta.get("height_points") or 0.0)
    if width <= 0 or height <= 0:
        raise GeometryCorpusReplayError("geometry analysis page dimensions invalid")

    prepared_groups: list[tuple[str, tuple[float, float, float, float], Mapping[str, Any]]] = []
    for group in groups:
        if not isinstance(group, Mapping):
            raise GeometryCorpusReplayError("geometry group must be an object")
        group_id = _text(group.get("group_id"))
        if not group_id:
            raise GeometryCorpusReplayError("geometry group ID missing")
        prepared_groups.append((group_id, _bbox(group), group))

    provisional: dict[str, str] = {}
    rows: list[dict[str, Any]] = []
    cells = fixture.get("cells")
    if not isinstance(cells, list):
        raise GeometryCorpusReplayError("fixture cells missing")

    for raw_cell in cells:
        cell = dict(raw_cell)
        cell_id = str(cell["cell_id"])
        truth = n10.get(cell_id)
        if truth is None:
            raise GeometryCorpusReplayError(f"N10 cell missing: {cell_id}")
        if truth.get("publication_slug") != cell.get("publication_slug") or truth.get("page_number") != cell.get("page_number"):
            raise GeometryCorpusReplayError(f"N9/N10 page identity mismatch: {cell_id}")

        rect = cell_rect(cell, width, height)
        center_ids = [group_id for group_id, box, _ in prepared_groups if _contains_point(rect, _center(box))]
        intersecting_ids = [group_id for group_id, box, _ in prepared_groups if _intersects(rect, box)]
        scope_excluded = cell.get("scope_state") == "excluded_non_target_card"
        if scope_excluded:
            binding_state = "excluded_scope_control"
            chosen_id = None
        elif len(center_ids) == 1:
            binding_state = "single_center_group"
            chosen_id = center_ids[0]
            provisional[cell_id] = chosen_id
        elif not center_ids:
            binding_state = "no_center_group_review_required"
            chosen_id = None
        else:
            binding_state = "multiple_center_groups_review_required"
            chosen_id = None

        rows.append(
            {
                "cell_id": cell_id,
                "publication_slug": cell["publication_slug"],
                "page_number": cell["page_number"],
                "scope_state": cell.get("scope_state"),
                "cell_rect_points": [round(value, 3) for value in rect],
                "center_group_ids": sorted(center_ids),
                "intersecting_group_ids": sorted(intersecting_ids),
                "geometry_binding_state": binding_state,
                "geometry_group_id": chosen_id,
                "selected_title": None,
                "selected_normal_price": None,
                "geometry_group_route": None,
                "title_exact_match": None,
                "title_normalized_match": None,
                "normal_price_match": None,
                "truth_comparison_state": "not_compared",
                "expected_title": truth.get("expected_title"),
                "expected_normal_price": truth.get("expected_primary_price_eur"),
                "promotion_ready": False,
            }
        )

    users: defaultdict[str, list[str]] = defaultdict(list)
    for cell_id, group_id in provisional.items():
        users[group_id].append(cell_id)
    reused = {group_id for group_id, cell_ids in users.items() if len(cell_ids) > 1}
    by_group = {group_id: group for group_id, _, group in prepared_groups}

    for row in rows:
        group_id = row["geometry_group_id"]
        if group_id is None:
            continue
        if group_id in reused:
            row["geometry_binding_state"] = "cross_cell_group_reuse_review_required"
            row["geometry_group_id"] = None
            continue
        group = by_group[group_id]
        selected_title = group.get("selected_title")
        selected_price = group.get("selected_normal_price")
        expected_title = row["expected_title"]
        expected_price = row["expected_normal_price"]
        row["selected_title"] = selected_title
        row["selected_normal_price"] = selected_price
        row["geometry_group_route"] = group.get("route")
        row["title_exact_match"] = _text(selected_title) == _text(expected_title)
        row["title_normalized_match"] = _normalized_title(selected_title) == _normalized_title(expected_title)
        row["normal_price_match"] = _price(selected_price) == _price(expected_price)
        row["truth_comparison_state"] = (
            "reproduced_match"
            if row["title_normalized_match"] and row["normal_price_match"]
            else "reproducible_disagreement"
        )
    return rows


def replay_geometry_corpus(
    fixtures: Sequence[Mapping[str, Any]],
    n10: Mapping[str, Mapping[str, Any]],
    pdfs: Mapping[str, Path],
    geometry_module: Any | None = None,
    analyze_page: Callable[[Path, int], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    module = geometry_module or load_geometry_module()
    if analyze_page is None:
        def analyze_page(pdf_path: Path, page_number: int) -> Mapping[str, Any]:
            layout = module.extract_layout_from_pdf(pdf_path, page_number)
            return module.analyze_layout(layout)

    all_rows: list[dict[str, Any]] = []
    rotations: Counter[int] = Counter()
    for fixture in fixtures:
        page = fixture["page"]
        campaign = str(page["publication_slug"])
        page_number = int(page["page_number"])
        pdf_path = pdfs[campaign]
        analysis = analyze_page(pdf_path, page_number)
        analysis_page = analysis.get("page") if isinstance(analysis, Mapping) else None
        if not isinstance(analysis_page, Mapping):
            raise GeometryCorpusReplayError("analysis page metadata missing")
        if analysis_page.get("page_number") != page_number:
            raise GeometryCorpusReplayError("analysis page-number mismatch")
        rotations[int(analysis_page.get("rotation") or 0)] += 1
        all_rows.extend(map_fixture(fixture, analysis, n10))

    if len(all_rows) != 100 or len({row["cell_id"] for row in all_rows}) != 100:
        raise GeometryCorpusReplayError("replay output must contain exactly 100 unique cells")
    states = Counter(row["geometry_binding_state"] for row in all_rows)
    comparisons = Counter(row["truth_comparison_state"] for row in all_rows)
    return {
        "schema_version": 1,
        "strategy": "netto_visual_geometry_corpus_replay_v1",
        "geometry_parser_identity": EXPECTED_GEOMETRY_PARSER,
        "source_archive_sha256": EXPECTED_SOURCE_ARCHIVE_SHA256,
        "source_n9_fixture_manifest_sha256": EXPECTED_N9_MANIFEST_SHA256,
        "source_n10_ledger_sha256": EXPECTED_N10_SHA256,
        "campaign_pdf_sha256": {
            campaign: values["pdf_sha256"] for campaign, values in sorted(CAMPAIGN_PDFS.items())
        },
        "fixture_page_count": 17,
        "cell_count": 100,
        "page_rotation_counts": {str(key): value for key, value in sorted(rotations.items())},
        "geometry_binding_counts": dict(sorted(states.items())),
        "truth_comparison_counts": dict(sorted(comparisons.items())),
        "unsafe_cross_binding_count": states.get("cross_cell_group_reuse_review_required", 0),
        "second_review_status": "replay_evidence_only",
        "review_only_default": True,
        "promotion_ready": False,
        "automatic_approval_enabled": False,
        "automatic_publish_enabled": False,
        "database_write_performed": False,
        "deployment_performed": False,
        "production_apply_authorized": False,
        "rows": all_rows,
    }


def write_create_only(path: Path, payload: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise GeometryCorpusReplayError("output already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay the exact Netto N9/N10 100-cell corpus through the merged geometry parser.")
    parser.add_argument("--n9-manifest", type=Path, required=True)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--n10-ledger", type=Path, default=DEFAULT_N10)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    fixtures = load_exact_n9_manifest(args.n9_manifest)
    n10 = load_exact_n10(args.n10_ledger)
    pdfs = locate_exact_pdfs(args.corpus_root)
    payload = replay_geometry_corpus(fixtures, n10, pdfs)
    write_create_only(args.output, payload)
    print(json.dumps({
        "geometry_binding_counts": payload["geometry_binding_counts"],
        "truth_comparison_counts": payload["truth_comparison_counts"],
        "unsafe_cross_binding_count": payload["unsafe_cross_binding_count"],
        "promotion_ready": payload["promotion_ready"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
