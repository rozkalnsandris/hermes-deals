#!/usr/bin/env python3
"""Normalize OCR/VLM booklet detections into fail-closed Review-only hotspot candidates.

This PoC never proves product identity and never writes application/production state.
It consumes already-produced model JSON plus an exact SHA-pinned PDF and emits
normalized coordinates suitable for evaluating the existing Hermes booklet viewer.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from urllib.parse import urlparse

FORMAT = "hermes.netto.booklet_recognition_poc.v1"
HEX = re.compile(r"[0-9a-f]{64}\Z")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
PRICE = re.compile(r"(?<!\d)(?:\d{1,3}[.,]\d{2}|\d+[.,]-)(?:\s*€)?(?!\d)")


class RecognitionEvidenceError(ValueError):
    pass


def _number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(float(value))


def _normalize_rect(raw: object, width: float, height: float) -> list[float]:
    if (
        not isinstance(raw, (list, tuple))
        or len(raw) != 4
        or not all(_number(value) for value in raw)
        or not _number(width)
        or not _number(height)
    ):
        raise RecognitionEvidenceError("missing or nonnumeric rectangle")
    x0, y0, x1, y1 = (float(value) for value in raw)
    width = float(width)
    height = float(height)
    if (
        not (1 <= width <= 20000 and 1 <= height <= 20000)
        or not (0 <= x0 < x1 <= width + 0.001)
        or not (0 <= y0 < y1 <= height + 0.001)
    ):
        raise RecognitionEvidenceError("out-of-page rectangle")
    return [
        round(x0 / width, 6),
        round(y0 / height, 6),
        round((x1 - x0) / width, 6),
        round((y1 - y0) / height, 6),
    ]


def _payload_result(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise RecognitionEvidenceError("model result must be an object")
    result = payload.get("res")
    if isinstance(result, dict):
        return result
    return payload


def paddle_text_regions(
    payload: object,
    width: float,
    height: float,
    *,
    min_score: float = 0.35,
) -> list[dict]:
    """Normalize PaddleOCR 3.x rec_texts/rec_scores/rec_boxes output."""
    result = _payload_result(payload)
    texts = result.get("rec_texts")
    scores = result.get("rec_scores")
    boxes = result.get("rec_boxes")
    if not all(isinstance(value, list) for value in (texts, scores, boxes)):
        raise RecognitionEvidenceError("missing PaddleOCR recognition arrays")
    if not (len(texts) == len(scores) == len(boxes)) or len(texts) > 5000:
        raise RecognitionEvidenceError("inconsistent PaddleOCR recognition arrays")
    if not _number(min_score) or not 0 <= float(min_score) <= 1:
        raise RecognitionEvidenceError("invalid OCR score threshold")

    rows: list[dict] = []
    for index, (text, score, box) in enumerate(zip(texts, scores, boxes), 1):
        if not isinstance(text, str) or not text.strip() or len(text) > 1000:
            raise RecognitionEvidenceError("invalid OCR text")
        if not _number(score) or not 0 <= float(score) <= 1:
            raise RecognitionEvidenceError("invalid OCR confidence")
        if float(score) < float(min_score):
            continue
        rows.append(
            {
                "region_id": f"ocr-{index}",
                "text": text.strip(),
                "confidence": round(float(score), 6),
                "bbox": _normalize_rect(box, width, height),
                "basis": "paddleocr_text_box",
                "state": "REVIEW_ONLY",
                "verified_product_identity": None,
                "hermes_offer_link": None,
            }
        )
    return rows


def _normalize_unit_rect(raw: object) -> list[float]:
    if (
        not isinstance(raw, (list, tuple))
        or len(raw) != 4
        or not all(_number(value) for value in raw)
    ):
        raise RecognitionEvidenceError("missing or nonnumeric normalized rectangle")
    x, y, width, height = (float(value) for value in raw)
    if (
        not (0 <= x < 1 and 0 <= y < 1)
        or not (0 < width <= 1 and 0 < height <= 1)
        or x + width > 1.000001
        or y + height > 1.000001
    ):
        raise RecognitionEvidenceError("out-of-page normalized rectangle")
    return [round(x, 6), round(y, 6), round(width, 6), round(height, 6)]


def native_price_candidates(payload: object) -> list[dict]:
    """Normalize source-native primary-price groups into Review-only hotspots."""
    if not isinstance(payload, dict):
        raise RecognitionEvidenceError("native result must be an object")
    candidates = payload.get("price_anchor_candidates")
    if not isinstance(candidates, list) or len(candidates) > 500:
        raise RecognitionEvidenceError("missing or excessive native price candidates")

    rows = []
    seen: set[str] = set()
    for row in candidates:
        if not isinstance(row, dict):
            raise RecognitionEvidenceError("native price candidate must be an object")
        candidate_id = row.get("candidate_id")
        price_region_id = row.get("price_region_id")
        price_text = row.get("price_text")
        texts = row.get("native_text")
        image_ids = row.get("native_image_region_ids")
        basis = row.get("basis")
        if (
            not isinstance(candidate_id, str)
            or not candidate_id
            or len(candidate_id) > 100
            or candidate_id in seen
        ):
            raise RecognitionEvidenceError("invalid or duplicate native candidate id")
        seen.add(candidate_id)
        if not isinstance(price_region_id, str) or not price_region_id or len(price_region_id) > 100:
            raise RecognitionEvidenceError("invalid native price region id")
        if not isinstance(price_text, str) or not PRICE.search(price_text) or len(price_text) > 100:
            raise RecognitionEvidenceError("invalid native price text")
        if (
            not isinstance(texts, list)
            or len(texts) > 1000
            or any(not isinstance(value, str) or len(value) > 1000 for value in texts)
        ):
            raise RecognitionEvidenceError("invalid native text evidence")
        if (
            not isinstance(image_ids, list)
            or len(image_ids) > 500
            or any(not isinstance(value, str) or not value or len(value) > 100 for value in image_ids)
        ):
            raise RecognitionEvidenceError("invalid native image evidence")
        if not isinstance(basis, str) or not basis or len(basis) > 200:
            raise RecognitionEvidenceError("invalid native candidate basis")
        if (
            row.get("state") != "REVIEW_ONLY"
            or row.get("product_boundary_proven") is not False
            or row.get("verified_product_identity") is not None
            or row.get("hermes_offer_link") is not None
        ):
            raise RecognitionEvidenceError("native candidate violates Review-only policy")

        rows.append(
            {
                "candidate_id": candidate_id,
                "bbox": _normalize_unit_rect(row.get("crop_bbox")),
                "texts": list(texts),
                "price_anchor_text": price_text,
                "price_region_id": price_region_id,
                "native_image_region_ids": list(image_ids),
                "basis": "native_pdf_primary_price_group",
                "source_basis": basis,
                "product_boundary_proven": False,
                "state": "REVIEW_ONLY",
                "verified_product_identity": None,
                "hermes_offer_link": None,
            }
        )
    return rows


def _bbox_union(boxes: list[list[float]]) -> list[float]:
    if not boxes:
        raise RecognitionEvidenceError("cannot union empty boxes")
    x0 = min(box[0] for box in boxes)
    y0 = min(box[1] for box in boxes)
    x1 = max(box[0] + box[2] for box in boxes)
    y1 = max(box[1] + box[3] for box in boxes)
    return [round(x0, 6), round(y0, 6), round(x1 - x0, 6), round(y1 - y0, 6)]


def _center(box: list[float]) -> tuple[float, float]:
    return box[0] + box[2] / 2, box[1] + box[3] / 2


def ocr_price_clusters(regions: list[dict]) -> list[dict]:
    """Create text-neighborhood candidates around printed prices.

    These are not product boundaries. They only make PaddleOCR-only output
    comparable with a later vision-region stage.
    """
    anchors = [row for row in regions if PRICE.search(row["text"])]
    candidates: list[dict] = []
    for index, anchor in enumerate(anchors, 1):
        ax, ay = _center(anchor["bbox"])
        neighborhood = []
        for row in regions:
            rx, ry = _center(row["bbox"])
            if abs(rx - ax) <= 0.34 and abs(ry - ay) <= 0.16:
                neighborhood.append(row)
        if anchor not in neighborhood:
            neighborhood.append(anchor)
        neighborhood.sort(key=lambda row: (row["bbox"][1], row["bbox"][0], row["region_id"]))
        candidates.append(
            {
                "candidate_id": f"ocr-price-{index}",
                "bbox": _bbox_union([row["bbox"] for row in neighborhood]),
                "texts": [row["text"] for row in neighborhood],
                "price_anchor_text": anchor["text"],
                "basis": "ocr_price_neighborhood",
                "product_boundary_proven": False,
                "state": "REVIEW_ONLY",
                "verified_product_identity": None,
                "hermes_offer_link": None,
            }
        )
    return candidates


def florence_regions(
    payload: object,
    width: float,
    height: float,
    *,
    task: str = "<DENSE_REGION_CAPTION>",
) -> list[dict]:
    """Normalize Florence-2 post_process_generation bboxes/labels."""
    if not isinstance(payload, dict):
        raise RecognitionEvidenceError("Florence result must be an object")
    result = payload.get(task)
    if not isinstance(result, dict):
        raise RecognitionEvidenceError("missing Florence task result")
    boxes = result.get("bboxes")
    labels = result.get("labels")
    if not isinstance(boxes, list) or not isinstance(labels, list):
        raise RecognitionEvidenceError("missing Florence boxes or labels")
    if len(boxes) != len(labels) or len(boxes) > 2000:
        raise RecognitionEvidenceError("inconsistent Florence result arrays")
    rows = []
    for index, (box, label) in enumerate(zip(boxes, labels), 1):
        if not isinstance(label, str) or len(label) > 1000:
            raise RecognitionEvidenceError("invalid Florence label")
        rows.append(
            {
                "region_id": f"vision-{index}",
                "bbox": _normalize_rect(box, width, height),
                "label": label.strip(),
                "basis": "florence2_dense_region_caption",
                "state": "REVIEW_ONLY",
                "verified_product_identity": None,
                "hermes_offer_link": None,
            }
        )
    return rows


def _intersects(a: list[float], b: list[float]) -> bool:
    return (
        a[0] < b[0] + b[2]
        and b[0] < a[0] + a[2]
        and a[1] < b[1] + b[3]
        and b[1] < a[1] + a[3]
    )


def attach_ocr_to_vision(vision: list[dict], ocr: list[dict]) -> list[dict]:
    rows = []
    for region in vision:
        texts = [row for row in ocr if _intersects(region["bbox"], row["bbox"])]
        texts.sort(key=lambda row: (row["bbox"][1], row["bbox"][0], row["region_id"]))
        rows.append(
            {
                **region,
                "ocr_texts": [row["text"] for row in texts],
                "ocr_region_ids": [row["region_id"] for row in texts],
                "product_boundary_proven": False,
            }
        )
    return rows


def build_page(
    page_number: int,
    image_width: float,
    image_height: float,
    paddle_payload: object | None = None,
    florence_payload: object | None = None,
    native_payload: object | None = None,
) -> dict:
    if type(page_number) is not int or page_number < 1:
        raise RecognitionEvidenceError("invalid page number")
    text = (
        paddle_text_regions(paddle_payload, image_width, image_height)
        if paddle_payload is not None
        else []
    )
    ocr_candidates = ocr_price_clusters(text)
    native_candidates = (
        native_price_candidates(native_payload)
        if native_payload is not None
        else []
    )
    page = {
        "page_number": page_number,
        "model_image_size": [int(image_width), int(image_height)],
        "ocr_text_regions": text,
        "ocr_price_candidates": ocr_candidates,
        "native_price_candidates": native_candidates,
        "hotspot_candidates": native_candidates if native_candidates else ocr_candidates,
        "hotspot_candidate_source": "native" if native_candidates else ("paddle" if ocr_candidates else None),
        "vision_regions": [],
        "automatic_offer_links": 0,
        "verified_product_identities": 0,
    }
    if florence_payload is not None:
        page["vision_regions"] = attach_ocr_to_vision(
            florence_regions(florence_payload, image_width, image_height),
            text,
        )
    return page


def _verify_publication_url(value: str) -> str:
    if not isinstance(value, str) or len(value) > 500:
        raise RecognitionEvidenceError("invalid publication URL")
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise RecognitionEvidenceError("publication URL must be HTTPS")
    return value


def build_manifest(
    pdf: Path,
    expected_sha256: str,
    model_results: dict,
    *,
    store: str,
    valid_from: str,
    valid_to: str,
    publication_url: str,
) -> dict:
    import fitz

    if store != "5659":
        raise RecognitionEvidenceError("PoC is bound to Netto store 5659")
    if DATE.fullmatch(valid_from or "") is None or DATE.fullmatch(valid_to or "") is None:
        raise RecognitionEvidenceError("invalid validity dates")
    if valid_from > valid_to:
        raise RecognitionEvidenceError("invalid validity interval")
    publication_url = _verify_publication_url(publication_url)
    if HEX.fullmatch(expected_sha256 or "") is None:
        raise RecognitionEvidenceError("missing or malformed PDF SHA256")

    pdf = pdf.resolve(strict=True)
    if pdf.is_symlink() or not pdf.is_file() or not 0 < pdf.stat().st_size <= 150 * 1024 * 1024:
        raise RecognitionEvidenceError("invalid PDF file")
    raw = pdf.read_bytes()
    if sha256(raw).hexdigest() != expected_sha256:
        raise RecognitionEvidenceError("PDF SHA256 mismatch")

    pages = model_results.get("pages") if isinstance(model_results, dict) else None
    if not isinstance(pages, list) or not 1 <= len(pages) <= 100:
        raise RecognitionEvidenceError("missing model page results")

    with fitz.open(stream=raw, filetype="pdf") as document:
        if document.needs_pass or not 1 <= document.page_count <= 300:
            raise RecognitionEvidenceError("unusable PDF")
        page_count = document.page_count

    seen: set[int] = set()
    normalized = []
    for row in pages:
        if not isinstance(row, dict):
            raise RecognitionEvidenceError("model page row must be an object")
        page_number = row.get("page_number")
        width = row.get("image_width")
        height = row.get("image_height")
        if (
            type(page_number) is not int
            or page_number in seen
            or not 1 <= page_number <= page_count
            or not _number(width)
            or not _number(height)
        ):
            raise RecognitionEvidenceError("invalid or duplicate model page")
        seen.add(page_number)
        normalized.append(
            build_page(
                page_number,
                float(width),
                float(height),
                row.get("paddle"),
                row.get("florence"),
                row.get("native"),
            )
        )
    normalized.sort(key=lambda row: row["page_number"])
    return {
        "format": FORMAT,
        "retailer": "Netto Marken-Discount",
        "store": store,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "publication_url": publication_url,
        "source_pdf_sha256": expected_sha256,
        "source_pdf_page_count": page_count,
        "sample_page_count": len(normalized),
        "identity_policy": "REVIEW_ONLY_NO_VLM_OR_OCR_IDENTITY_PROMOTION",
        "automatic_offer_links": 0,
        "verified_product_identities": 0,
        "pages": normalized,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--pdf-sha256", required=True)
    parser.add_argument("--model-results", type=Path, required=True)
    parser.add_argument("--store", default="5659")
    parser.add_argument("--valid-from", required=True)
    parser.add_argument("--valid-to", required=True)
    parser.add_argument("--publication-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.model_results.is_symlink() or not args.model_results.is_file():
        raise RecognitionEvidenceError("invalid model-results file")
    if not 0 < args.model_results.stat().st_size <= 20 * 1024 * 1024:
        raise RecognitionEvidenceError("model-results file outside size limit")
    try:
        model_results = json.loads(args.model_results.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RecognitionEvidenceError("invalid model-results JSON") from exc

    output = args.output.resolve()
    if output.exists() or output.is_symlink():
        raise RecognitionEvidenceError("will not overwrite recognition evidence")
    result = build_manifest(
        args.pdf,
        args.pdf_sha256,
        model_results,
        store=args.store,
        valid_from=args.valid_from,
        valid_to=args.valid_to,
        publication_url=args.publication_url,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
    print(
        json.dumps(
            {
                "pdf_sha256": result["source_pdf_sha256"],
                "pdf_pages": result["source_pdf_page_count"],
                "sample_pages": result["sample_page_count"],
                "automatic_offer_links": 0,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
