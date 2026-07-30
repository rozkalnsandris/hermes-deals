#!/usr/bin/env python3
from __future__ import annotations

import argparse
from hashlib import sha256
from importlib.metadata import version
import json
import os
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile
from typing import Any

import pymupdf


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_output_path(root: Path, relative: str) -> Path:
    rel = PurePosixPath(relative)
    if rel.is_absolute() or not rel.parts or ".." in rel.parts:
        raise ValueError(f"unsafe relative output path: {relative!r}")
    target = root.joinpath(*rel.parts)
    resolved_parent = target.parent.resolve()
    resolved_parent.relative_to(root.resolve())
    return target


def rects(values: Any) -> list[pymupdf.Rect]:
    result: list[pymupdf.Rect] = []
    for value in values or []:
        if not isinstance(value, list) or len(value) != 4:
            raise ValueError(f"invalid bbox: {value!r}")
        rect = pymupdf.Rect(*(float(part) for part in value))
        if rect.is_empty or rect.is_infinite:
            raise ValueError(f"invalid bbox: {value!r}")
        result.append(rect)
    return result


def draw_boxes(page: pymupdf.Page, boxes: list[pymupdf.Rect]) -> None:
    if not boxes:
        return
    shape = page.new_shape()
    drawn = False
    for rect in boxes:
        clipped = rect & page.rect
        if clipped.is_empty:
            continue
        shape.draw_rect(clipped)
        drawn = True
    if drawn:
        shape.finish(color=(0.86, 0.08, 0.08), width=2.2)
        shape.commit(overlay=True)


def band_clip(page: pymupdf.Page, boxes: list[pymupdf.Rect]) -> pymupdf.Rect:
    if len(boxes) != 1:
        raise ValueError("band preview requires exactly one bbox")
    box = boxes[0] & page.rect
    if box.is_empty:
        raise ValueError("band bbox is outside the PDF page")
    y0 = max(0.0, box.y0 - 145.0)
    y1 = min(page.rect.height, box.y1 + 190.0)
    if y1 - y0 < 220.0:
        center = (y0 + y1) / 2.0
        y0 = max(0.0, center - 110.0)
        y1 = min(page.rect.height, center + 110.0)
    return pymupdf.Rect(0.0, y0, page.rect.width, y1)


def render_one(pdf: Path, entry: dict[str, Any], output_root: Path) -> dict[str, Any]:
    page_number = entry.get("page_number")
    mode = entry.get("mode")
    if isinstance(page_number, bool) or not isinstance(page_number, int) or page_number < 1:
        raise ValueError(f"invalid page_number: {page_number!r}")
    if mode not in {"page", "band"}:
        raise ValueError(f"invalid mode: {mode!r}")

    boxes = rects(entry.get("boxes"))
    output = safe_output_path(output_root, str(entry.get("relative_path") or ""))
    output.parent.mkdir(parents=True, exist_ok=True)

    with pymupdf.open(pdf) as document:
        if page_number > document.page_count:
            raise ValueError(
                f"page {page_number} exceeds PDF page count {document.page_count}"
            )
        page = document.load_page(page_number - 1)
        draw_boxes(page, boxes)
        clip = page.rect if mode == "page" else band_clip(page, boxes)
        zoom = 1.45 if mode == "page" else 2.0
        pixmap = page.get_pixmap(
            matrix=pymupdf.Matrix(zoom, zoom),
            clip=clip,
            alpha=False,
            annots=True,
        )
        data = pixmap.tobytes("png")
        width = pixmap.width
        height = pixmap.height

    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("renderer did not produce PNG data")

    with NamedTemporaryFile(
        dir=output.parent,
        prefix=".preview-",
        delete=False,
    ) as handle:
        handle.write(data)
        temporary = Path(handle.name)
    os.replace(temporary, output)

    return {
        "name": entry.get("name"),
        "page_number": page_number,
        "mode": mode,
        "boxes": entry.get("boxes") or [],
        "relative_path": str(entry["relative_path"]),
        "bytes": len(data),
        "width": width,
        "height": height,
        "sha256": sha256(data).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--pdf-sha256", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    pdf = Path(args.pdf).resolve(strict=True)
    expected_sha = args.pdf_sha256.strip().lower()
    actual_sha = file_sha256(pdf)
    if actual_sha != expected_sha:
        raise SystemExit(
            f"source PDF SHA mismatch: expected={expected_sha} actual={actual_sha}"
        )

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    entries = manifest.get("assets")
    if not isinstance(entries, list) or not entries:
        raise SystemExit("manifest has no assets")

    by_path: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise SystemExit("manifest asset is not an object")
        relative = str(entry.get("relative_path") or "")
        previous = by_path.get(relative)
        if previous is not None and previous != entry:
            raise SystemExit(f"conflicting duplicate asset path: {relative}")
        by_path[relative] = entry

    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    rendered = [
        render_one(pdf, by_path[relative], output_root)
        for relative in sorted(by_path)
    ]
    report = {
        "renderer": "hermes-lidl-review-preview-renderer-v1",
        "pymupdf_version": version("PyMuPDF"),
        "source_pdf": str(pdf),
        "source_pdf_sha256": actual_sha,
        "asset_count": len(rendered),
        "assets": rendered,
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
