from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import importlib.metadata
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


PACK_STRATEGY = "netto_blind_independent_source_review_pack_v1"
REVIEW_LEDGER_STRATEGY = "netto_blind_independent_review_ledger_v1"
EXPECTED_N9_MANIFEST_SHA256 = (
    "2b180d67af4c5d1e586704088e3d685cff21ae2e12f3052254daf4553dd4e147"
)
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
EXPECTED_PYMUPDF_VERSION = "1.28.0"
RENDER_DPI = 144


class BlindReviewPackError(ValueError):
    pass


def sha_bytes(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def sha_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_bytes(payload: Any) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def load_json(path: Path) -> Any:
    if path.is_symlink() or not path.is_file():
        raise BlindReviewPackError(f"input must be a regular file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BlindReviewPackError(f"invalid UTF-8 JSON: {path}") from exc


def _text(value: Any) -> str | None:
    if value is None:
        return None
    result = " ".join(str(value).split()).strip()
    return result or None


def validate_n9_manifest(fixtures: Any) -> list[dict[str, Any]]:
    if not isinstance(fixtures, list) or len(fixtures) != 17:
        raise BlindReviewPackError("N9 manifest must contain exactly 17 fixtures")

    seen_pages: set[tuple[str, int]] = set()
    seen_cells: set[str] = set()
    campaign_counts: Counter[str] = Counter()
    zero_cell_pages = 0
    normalized: list[dict[str, Any]] = []

    for fixture in fixtures:
        if not isinstance(fixture, Mapping):
            raise BlindReviewPackError("N9 fixture must be an object")
        if fixture.get("strategy") != "netto_n9_n8_v2_visual_cell_fixture_v1":
            raise BlindReviewPackError("unexpected N9 fixture strategy")
        if fixture.get("review_state") != "pending_visual_validation":
            raise BlindReviewPackError("N9 fixture review state drift")
        if fixture.get("automatic_approval_count") != 0:
            raise BlindReviewPackError("N9 fixture automatic approval drift")
        if fixture.get("automatic_publish_count") != 0:
            raise BlindReviewPackError("N9 fixture automatic publication drift")
        if fixture.get("production_write_performed") is not False:
            raise BlindReviewPackError("N9 fixture production-write flag drift")

        page = fixture.get("page")
        cells = fixture.get("cells")
        if not isinstance(page, Mapping) or not isinstance(cells, list):
            raise BlindReviewPackError("N9 fixture page/cells shape is invalid")
        campaign = _text(page.get("publication_slug"))
        page_number = page.get("page_number")
        if campaign not in EXPECTED_CAMPAIGN_COUNTS:
            raise BlindReviewPackError("N9 fixture campaign drift")
        if not isinstance(page_number, int) or page_number <= 0:
            raise BlindReviewPackError("N9 fixture page number is invalid")
        page_key = (campaign, page_number)
        if page_key in seen_pages:
            raise BlindReviewPackError("duplicate N9 fixture page")
        seen_pages.add(page_key)
        if not cells:
            zero_cell_pages += 1

        normalized_cells: list[dict[str, Any]] = []
        for cell in cells:
            if not isinstance(cell, Mapping):
                raise BlindReviewPackError("N9 cell must be an object")
            cell_id = _text(cell.get("cell_id"))
            if not cell_id or cell_id in seen_cells:
                raise BlindReviewPackError("N9 cell IDs must be unique")
            if cell.get("publication_slug") != campaign:
                raise BlindReviewPackError("N9 cell campaign identity drift")
            if cell.get("page_number") != page_number:
                raise BlindReviewPackError("N9 cell page identity drift")
            if cell.get("review_state") != "pending_visual_validation":
                raise BlindReviewPackError("N9 cell review state drift")
            if cell.get("automatic_approval_allowed") is not False:
                raise BlindReviewPackError("N9 cell automatic approval drift")
            if cell.get("automatic_publish_allowed") is not False:
                raise BlindReviewPackError("N9 cell automatic publication drift")
            try:
                x0, y0, x1, y1 = (
                    float(cell[key])
                    for key in ("region_x0", "region_y0", "region_x1", "region_y1")
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise BlindReviewPackError(f"invalid N9 cell geometry: {cell_id}") from exc
            if not (0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0):
                raise BlindReviewPackError(
                    f"N9 cell geometry outside normalized page: {cell_id}"
                )
            seen_cells.add(cell_id)
            campaign_counts[campaign] += 1
            normalized_cells.append(dict(cell))

        if page.get("raw_cell_count") != len(cells):
            raise BlindReviewPackError("N9 page raw-cell count drift")
        normalized.append({**dict(fixture), "cells": normalized_cells})

    if len(seen_cells) != 100:
        raise BlindReviewPackError("N9 manifest must contain exactly 100 unique cells")
    if dict(campaign_counts) != EXPECTED_CAMPAIGN_COUNTS:
        raise BlindReviewPackError("N9 campaign cell counts drift")
    if zero_cell_pages != 6:
        raise BlindReviewPackError("N9 zero-cell control page count drift")

    return sorted(
        normalized,
        key=lambda row: (
            str(row["page"]["publication_slug"]),
            int(row["page"]["page_number"]),
        ),
    )


def load_exact_n9_manifest(path: Path) -> list[dict[str, Any]]:
    if sha_file(path) != EXPECTED_N9_MANIFEST_SHA256:
        raise BlindReviewPackError("N9 fixture-manifest SHA256 mismatch")
    return validate_n9_manifest(load_json(path))


def locate_exact_pdfs(corpus_root: Path) -> dict[str, Path]:
    if corpus_root.is_symlink() or not corpus_root.is_dir():
        raise BlindReviewPackError("corpus root must be a regular directory")

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
            raise BlindReviewPackError(f"duplicate corpus campaign: {campaign}")
        pdf_path = manifest_path.parent / "source.pdf"
        if pdf_path.is_symlink() or not pdf_path.is_file():
            raise BlindReviewPackError(f"corpus PDF missing: {campaign}")
        expected = CAMPAIGN_PDFS[campaign]
        if sha_file(pdf_path) != expected["pdf_sha256"]:
            raise BlindReviewPackError(f"corpus PDF SHA256 mismatch: {campaign}")
        if manifest.get("pdf_sha256") not in (None, expected["pdf_sha256"]):
            raise BlindReviewPackError(f"corpus manifest PDF SHA drift: {campaign}")
        if manifest.get("page_count") not in (None, expected["page_count"]):
            raise BlindReviewPackError(f"corpus manifest page-count drift: {campaign}")
        found[campaign] = pdf_path

    if set(found) != set(CAMPAIGN_PDFS):
        raise BlindReviewPackError(
            "both authoritative Netto campaign PDFs are required"
        )
    return found


def cell_rect(
    cell: Mapping[str, Any],
    width: float,
    height: float,
) -> tuple[float, float, float, float]:
    if width <= 0 or height <= 0:
        raise BlindReviewPackError("page dimensions must be positive")
    return (
        float(cell["region_x0"]) * width,
        float(cell["region_y0"]) * height,
        float(cell["region_x1"]) * width,
        float(cell["region_y1"]) * height,
    )


def _intersects(
    a: Sequence[float],
    b: Sequence[float],
) -> bool:
    return (
        max(float(a[0]), float(b[0])) < min(float(a[2]), float(b[2]))
        and max(float(a[1]), float(b[1])) < min(float(a[3]), float(b[3]))
    )


def text_spans_for_rect(page: Any, rect: Sequence[float]) -> list[dict[str, Any]]:
    text = page.get_text("dict")
    result: list[dict[str, Any]] = []
    for block in text.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                value = re.sub(r"\s+", " ", str(span.get("text") or "")).strip()
                bbox = span.get("bbox")
                if not value or not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
                    continue
                numeric_bbox = tuple(float(bbox[index]) for index in range(4))
                if not _intersects(numeric_bbox, rect):
                    continue
                result.append(
                    {
                        "text": value,
                        "bbox": [round(value, 3) for value in numeric_bbox],
                        "size": round(float(span.get("size") or 0.0), 3),
                        "font": str(span.get("font") or ""),
                        "color": int(span.get("color") or 0),
                        "flags": int(span.get("flags") or 0),
                    }
                )
    return sorted(
        result,
        key=lambda row: (
            row["bbox"][1],
            row["bbox"][0],
            row["text"],
        ),
    )


def stable_cell_member_name(ordinal: int, cell_id: str) -> str:
    digest = sha256(cell_id.encode("utf-8")).hexdigest()[:12]
    return f"{ordinal:03d}-{digest}"


def blank_review_ledger(
    fixtures: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    rows = []
    for fixture in fixtures:
        page = fixture["page"]
        campaign = str(page["publication_slug"])
        page_number = int(page["page_number"])
        for cell in fixture["cells"]:
            rows.append(
                {
                    "cell_id": str(cell["cell_id"]),
                    "publication_slug": campaign,
                    "page_number": page_number,
                    "observed_product_title": None,
                    "observed_normal_price": None,
                    "observed_member_price": None,
                    "card_ownership_state": None,
                    "scope_classification": None,
                    "reviewer_confidence": None,
                    "reviewer_note": None,
                }
            )
    rows.sort(key=lambda row: row["cell_id"])
    return {
        "schema_version": 1,
        "strategy": REVIEW_LEDGER_STRATEGY,
        "source_n9_fixture_manifest_sha256": EXPECTED_N9_MANIFEST_SHA256,
        "cell_count": len(rows),
        "review_state": "blank_independent_review",
        "rows": rows,
    }


def _write_create_only(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(payload)
    except FileExistsError as exc:
        raise BlindReviewPackError(f"output member already exists: {path}") from exc
    return sha_bytes(payload)


def _render_png(page: Any, rect: Any | None = None) -> bytes:
    import pymupdf

    matrix = pymupdf.Matrix(RENDER_DPI / 72.0, RENDER_DPI / 72.0)
    pixmap = page.get_pixmap(matrix=matrix, clip=rect, alpha=False)
    return pixmap.tobytes("png")


def generate_pack(
    n9_manifest: Path,
    corpus_root: Path,
    output: Path,
) -> dict[str, Any]:
    if output.exists() or output.is_symlink():
        raise BlindReviewPackError("output directory already exists")

    version = importlib.metadata.version("PyMuPDF")
    if version != EXPECTED_PYMUPDF_VERSION:
        raise BlindReviewPackError(
            f"PyMuPDF runtime mismatch: expected {EXPECTED_PYMUPDF_VERSION}, got {version}"
        )

    import pymupdf

    fixtures = load_exact_n9_manifest(n9_manifest)
    pdfs = locate_exact_pdfs(corpus_root)
    output.mkdir(parents=True)

    members: list[dict[str, Any]] = []
    pages_manifest: list[dict[str, Any]] = []
    cells_manifest: list[dict[str, Any]] = []
    ordinal = 0

    for fixture in fixtures:
        page_meta = fixture["page"]
        campaign = str(page_meta["publication_slug"])
        page_number = int(page_meta["page_number"])
        pdf_path = pdfs[campaign]

        document = pymupdf.open(pdf_path)
        try:
            if document.page_count != CAMPAIGN_PDFS[campaign]["page_count"]:
                raise BlindReviewPackError(
                    f"PDF page-count mismatch at runtime: {campaign}"
                )
            page = document.load_page(page_number - 1)
            source_rotation = int(page.rotation)
            if source_rotation:
                page.set_rotation(0)

            width = float(page.cropbox.width)
            height = float(page.cropbox.height)
            if width <= 0 or height <= 0:
                raise BlindReviewPackError("PDF page dimensions are invalid")

            page_member = f"pages/{campaign}-p{page_number:03d}.png"
            page_png = _render_png(
                page,
                pymupdf.Rect(0.0, 0.0, width, height),
            )
            page_sha = _write_create_only(output / page_member, page_png)
            members.append(
                {
                    "path": page_member,
                    "sha256": page_sha,
                    "bytes": len(page_png),
                    "kind": "page_context_png",
                }
            )
            pages_manifest.append(
                {
                    "publication_slug": campaign,
                    "page_number": page_number,
                    "source_pdf_sha256": CAMPAIGN_PDFS[campaign]["pdf_sha256"],
                    "source_rotation": source_rotation,
                    "unrotated_width_points": round(width, 3),
                    "unrotated_height_points": round(height, 3),
                    "context_image": page_member,
                    "context_image_sha256": page_sha,
                }
            )

            for cell in sorted(fixture["cells"], key=lambda row: str(row["cell_id"])):
                ordinal += 1
                cell_id = str(cell["cell_id"])
                rect_values = cell_rect(cell, width, height)
                rect = pymupdf.Rect(*rect_values)
                page_rect = pymupdf.Rect(0.0, 0.0, width, height)
                if (
                    rect.is_empty
                    or rect.x0 < page_rect.x0
                    or rect.y0 < page_rect.y0
                    or rect.x1 > page_rect.x1
                    or rect.y1 > page_rect.y1
                ):
                    raise BlindReviewPackError(
                        f"cell rectangle outside unrotated page: {cell_id}"
                    )

                member_stem = stable_cell_member_name(ordinal, cell_id)
                crop_member = f"cells/{member_stem}.png"
                text_member = f"cells/{member_stem}.json"

                crop_png = _render_png(page, rect)
                crop_sha = _write_create_only(output / crop_member, crop_png)
                text_payload = {
                    "schema_version": 1,
                    "cell_id": cell_id,
                    "publication_slug": campaign,
                    "page_number": page_number,
                    "source_pdf_sha256": CAMPAIGN_PDFS[campaign]["pdf_sha256"],
                    "cell_rect_points": [round(value, 3) for value in rect_values],
                    "coordinate_space": "unrotated_page_points",
                    "text_spans": text_spans_for_rect(page, rect_values),
                }
                text_bytes = json_bytes(text_payload)
                text_sha = _write_create_only(output / text_member, text_bytes)

                members.extend(
                    (
                        {
                            "path": crop_member,
                            "sha256": crop_sha,
                            "bytes": len(crop_png),
                            "kind": "cell_crop_png",
                        },
                        {
                            "path": text_member,
                            "sha256": text_sha,
                            "bytes": len(text_bytes),
                            "kind": "cell_text_evidence_json",
                        },
                    )
                )
                cells_manifest.append(
                    {
                        "cell_id": cell_id,
                        "publication_slug": campaign,
                        "page_number": page_number,
                        "source_pdf_sha256": CAMPAIGN_PDFS[campaign]["pdf_sha256"],
                        "cell_rect_points": [round(value, 3) for value in rect_values],
                        "coordinate_space": "unrotated_page_points",
                        "crop_image": crop_member,
                        "crop_image_sha256": crop_sha,
                        "text_evidence": text_member,
                        "text_evidence_sha256": text_sha,
                    }
                )
        finally:
            document.close()

    ledger = blank_review_ledger(fixtures)
    ledger_bytes = json_bytes(ledger)
    ledger_member = "independent-review-ledger.json"
    ledger_sha = _write_create_only(output / ledger_member, ledger_bytes)
    members.append(
        {
            "path": ledger_member,
            "sha256": ledger_sha,
            "bytes": len(ledger_bytes),
            "kind": "blank_independent_review_ledger",
        }
    )

    if len(pages_manifest) != 17 or len(cells_manifest) != 100:
        raise BlindReviewPackError("generated page/cell count drift")

    manifest = {
        "schema_version": 1,
        "strategy": PACK_STRATEGY,
        "source_n9_fixture_manifest_sha256": EXPECTED_N9_MANIFEST_SHA256,
        "source_pdfs": {
            campaign: {
                "sha256": values["pdf_sha256"],
                "page_count": values["page_count"],
            }
            for campaign, values in sorted(CAMPAIGN_PDFS.items())
        },
        "pymupdf_version": version,
        "render_dpi": RENDER_DPI,
        "coordinate_space": "unrotated_page_points",
        "fixture_page_count": len(pages_manifest),
        "cell_count": len(cells_manifest),
        "blind_review_contract": {
            "expected_truth_included": False,
            "parser_predictions_included": False,
            "automatic_approval_enabled": False,
            "automatic_publish_enabled": False,
            "production_write_performed": False,
        },
        "blank_review_ledger": ledger_member,
        "blank_review_ledger_sha256": ledger_sha,
        "pages": pages_manifest,
        "cells": sorted(cells_manifest, key=lambda row: row["cell_id"]),
        "members": sorted(members, key=lambda row: row["path"]),
    }
    manifest_bytes = json_bytes(manifest)
    _write_create_only(output / "manifest.json", manifest_bytes)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate the exact blind Netto 100-cell source-review pack "
            "without first-pass truth or parser predictions."
        )
    )
    parser.add_argument("--n9-manifest", type=Path, required=True)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    manifest = generate_pack(args.n9_manifest, args.corpus_root, args.output)
    print(
        json.dumps(
            {
                "strategy": manifest["strategy"],
                "fixture_page_count": manifest["fixture_page_count"],
                "cell_count": manifest["cell_count"],
                "pymupdf_version": manifest["pymupdf_version"],
                "output": str(args.output),
                "production_write_performed": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
