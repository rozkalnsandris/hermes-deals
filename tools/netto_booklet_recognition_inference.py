#!/usr/bin/env python3
"""Local-only model runner for the Netto booklet recognition PoC (#1140).

The default is deliberately offline: model weights must already exist locally.
No database, collector, publication or production writes are performed.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import resource
import re
import math
import tempfile
import time

MAX_PDF_BYTES = 150 * 1024 * 1024
MAX_PAGES = 300
MAX_SAMPLE_PAGES = 12
MAX_FLORENCE_PRICE_CROPS = 12
PRIMARY_PRICE_HEIGHT_RATIO = 0.60
NATIVE_PRICE_GROUP_RADIUS = 0.24
NATIVE_PRICE_GROUP_PADDING = 0.012
NATIVE_IMAGE_MIN_PIXELS = 2500
NATIVE_IMAGE_MAX_ASPECT = 8.0


class InferenceRunnerError(ValueError):
    pass


_NATIVE_PRICE = re.compile(r"^(?:\d{1,3}[.,]\d{2}|\d+[.,]-)\*?$")


def _normalized_bbox(raw, width: float, height: float) -> list[float]:
    if (
        not isinstance(raw, (list, tuple))
        or len(raw) != 4
        or width <= 0
        or height <= 0
    ):
        raise InferenceRunnerError("invalid native PDF rectangle")
    x0, y0, x1, y1 = (float(value) for value in raw)
    if not all(math.isfinite(value) for value in (x0, y0, x1, y1)):
        raise InferenceRunnerError("invalid native PDF rectangle")
    if not (0 <= x0 < x1 <= width + 0.001 and 0 <= y0 < y1 <= height + 0.001):
        raise InferenceRunnerError("native PDF rectangle outside page")
    return [
        round(x0 / width, 6),
        round(y0 / height, 6),
        round((x1 - x0) / width, 6),
        round((y1 - y0) / height, 6),
    ]


def _normalized_visible_image_bbox(raw, width: float, height: float) -> list[float]:
    if (
        not isinstance(raw, (list, tuple))
        or len(raw) != 4
        or width <= 0
        or height <= 0
    ):
        raise InferenceRunnerError("invalid native PDF image rectangle")
    x0, y0, x1, y1 = (float(value) for value in raw)
    if not all(math.isfinite(value) for value in (x0, y0, x1, y1)):
        raise InferenceRunnerError("invalid native PDF image rectangle")
    if not (x0 < x1 and y0 < y1):
        raise InferenceRunnerError("degenerate native PDF image rectangle")

    visible_x0 = max(0.0, x0)
    visible_y0 = max(0.0, y0)
    visible_x1 = min(width, x1)
    visible_y1 = min(height, y1)
    if not (visible_x0 < visible_x1 and visible_y0 < visible_y1):
        raise InferenceRunnerError("native PDF image rectangle does not intersect page")

    return [
        round(visible_x0 / width, 6),
        round(visible_y0 / height, 6),
        round((visible_x1 - visible_x0) / width, 6),
        round((visible_y1 - visible_y0) / height, 6),
    ]


def _bbox_center(bbox: list[float]) -> tuple[float, float]:
    return bbox[0] + bbox[2] / 2, bbox[1] + bbox[3] / 2


def _bbox_distance(a: list[float], b: list[float]) -> float:
    ax, ay = _bbox_center(a)
    bx, by = _bbox_center(b)
    return math.hypot(ax - bx, ay - by)


def _bbox_union_normalized(boxes: list[list[float]]) -> list[float]:
    if not boxes:
        raise InferenceRunnerError("cannot union empty native PDF rectangles")
    x0 = min(box[0] for box in boxes)
    y0 = min(box[1] for box in boxes)
    x1 = max(box[0] + box[2] for box in boxes)
    y1 = max(box[1] + box[3] for box in boxes)
    return [x0, y0, x1 - x0, y1 - y0]


def _expanded_normalized_bbox(bbox: list[float], padding: float) -> list[float]:
    x, y, width, height = bbox
    x0 = max(0.0, x - padding)
    y0 = max(0.0, y - padding)
    x1 = min(1.0, x + width + padding)
    y1 = min(1.0, y + height + padding)
    return [
        round(x0, 6),
        round(y0, 6),
        round(x1 - x0, 6),
        round(y1 - y0, 6),
    ]


def _primary_price_candidates(price_candidates: list[dict]) -> list[dict]:
    """Keep visually prominent price-like tokens as primary offer anchors.

    The threshold is page-relative: reference prices, deposits and quantities
    remain in price_candidates evidence but do not become primary anchors when
    their word boxes are materially smaller than the largest price on the page.
    """
    if not price_candidates:
        return []
    max_height = max(float(row["bbox"][3]) for row in price_candidates)
    threshold = max_height * PRIMARY_PRICE_HEIGHT_RATIO
    return [
        row
        for row in price_candidates
        if float(row["bbox"][3]) + 1e-9 >= threshold
    ]


def _substantive_native_image(row: dict) -> bool:
    width = int(row.get("pixel_width") or 0)
    height = int(row.get("pixel_height") or 0)
    if width <= 0 or height <= 0 or width * height < NATIVE_IMAGE_MIN_PIXELS:
        return False
    aspect = max(width / height, height / width)
    return aspect <= NATIVE_IMAGE_MAX_ASPECT


def _native_price_anchor_candidates(
    words: list[dict],
    images: list[dict],
    primary_price_candidates: list[dict],
) -> list[dict]:
    """Group nearby native evidence around visually prominent price anchors.

    Words and substantive images are assigned to their nearest primary price
    within a bounded normalized-page radius. The resulting crop is Review-only:
    it is an inspection region, not a proven product boundary or identity.
    """
    if not primary_price_candidates:
        return []

    word_by_id = {row["region_id"]: row for row in words}
    anchor_ids = {row["region_id"] for row in primary_price_candidates}
    grouped_words = {row["region_id"]: [] for row in primary_price_candidates}
    grouped_images = {row["region_id"]: [] for row in primary_price_candidates}

    for row in words:
        if row["region_id"] in anchor_ids:
            continue
        anchor = min(
            primary_price_candidates,
            key=lambda candidate: _bbox_distance(row["bbox"], candidate["bbox"]),
        )
        if _bbox_distance(row["bbox"], anchor["bbox"]) <= NATIVE_PRICE_GROUP_RADIUS:
            grouped_words[anchor["region_id"]].append(row)

    for row in images:
        if not _substantive_native_image(row):
            continue
        anchor = min(
            primary_price_candidates,
            key=lambda candidate: _bbox_distance(row["bbox"], candidate["bbox"]),
        )
        if _bbox_distance(row["bbox"], anchor["bbox"]) <= NATIVE_PRICE_GROUP_RADIUS:
            grouped_images[anchor["region_id"]].append(row)

    candidates = []
    for index, anchor in enumerate(primary_price_candidates, 1):
        anchor_word = word_by_id.get(anchor["region_id"])
        if anchor_word is None:
            raise InferenceRunnerError("native price anchor word is missing")

        nearby_words = [anchor_word, *grouped_words[anchor["region_id"]]]
        nearby_images = grouped_images[anchor["region_id"]]
        nearby_words.sort(
            key=lambda row: (row["bbox"][1], row["bbox"][0], row["region_id"])
        )
        nearby_images.sort(
            key=lambda row: (row["bbox"][1], row["bbox"][0], row["region_id"])
        )
        grouped_boxes = [row["bbox"] for row in nearby_words] + [
            row["bbox"] for row in nearby_images
        ]
        crop = _expanded_normalized_bbox(
            _bbox_union_normalized(grouped_boxes),
            NATIVE_PRICE_GROUP_PADDING,
        )
        candidates.append(
            {
                "candidate_id": f"native-price-{index}",
                "price_region_id": anchor["region_id"],
                "price_text": anchor["text"],
                "price_bbox": anchor["bbox"],
                "crop_bbox": crop,
                "native_text_region_ids": [row["region_id"] for row in nearby_words],
                "native_text": [row["text"] for row in nearby_words],
                "native_image_region_ids": [row["region_id"] for row in nearby_images],
                "price_block_no": anchor_word["block_no"],
                "basis": "native_pdf_nearest_primary_price_group_v2",
                "group_radius": NATIVE_PRICE_GROUP_RADIUS,
                "product_boundary_proven": False,
                "verified_product_identity": None,
                "hermes_offer_link": None,
                "state": "REVIEW_ONLY",
            }
        )
    return candidates


def native_page_structure(page) -> dict:
    """Extract source-native PDF text/image geometry without OCR or model inference."""
    width = float(page.rect.width)
    height = float(page.rect.height)
    if not (1 <= width <= 20000 and 1 <= height <= 20000):
        raise InferenceRunnerError("invalid native PDF page size")

    words = []
    for index, raw in enumerate(page.get_text("words", sort=False), 1):
        if len(raw) < 8:
            raise InferenceRunnerError("invalid native PDF word result")
        x0, y0, x1, y1, text, block_no, line_no, word_no = raw[:8]
        text = str(text).strip()
        if not text:
            continue
        words.append(
            {
                "region_id": f"native-word-{index}",
                "text": text,
                "bbox": _normalized_bbox([x0, y0, x1, y1], width, height),
                "block_no": int(block_no),
                "line_no": int(line_no),
                "word_no": int(word_no),
                "state": "REVIEW_ONLY",
            }
        )

    images = []
    for index, info in enumerate(page.get_image_info(hashes=True, xrefs=True), 1):
        if not isinstance(info, dict) or "bbox" not in info:
            raise InferenceRunnerError("invalid native PDF image result")
        digest = info.get("digest")
        if isinstance(digest, bytes):
            digest = digest.hex()
        elif digest is not None:
            digest = str(digest)
        images.append(
            {
                "region_id": f"native-image-{index}",
                "bbox": _normalized_visible_image_bbox(info["bbox"], width, height),
                "pixel_width": int(info.get("width") or 0),
                "pixel_height": int(info.get("height") or 0),
                "xref": int(info.get("xref") or 0),
                "digest": digest,
                "state": "REVIEW_ONLY",
            }
        )

    price_candidates = [
        {
            "region_id": row["region_id"],
            "text": row["text"],
            "bbox": row["bbox"],
            "basis": "native_pdf_price_like_token",
            "product_boundary_proven": False,
            "verified_product_identity": None,
            "hermes_offer_link": None,
            "state": "REVIEW_ONLY",
        }
        for row in words
        if _NATIVE_PRICE.fullmatch(row["text"].replace("€", "").strip())
    ]
    primary_price_candidates = _primary_price_candidates(price_candidates)
    price_anchor_candidates = _native_price_anchor_candidates(
        words,
        images,
        primary_price_candidates,
    )

    return {
        "page_size_points": [round(width, 3), round(height, 3)],
        "text_regions": words,
        "image_regions": images,
        "price_candidates": price_candidates,
        "primary_price_candidates": primary_price_candidates,
        "price_anchor_candidates": price_anchor_candidates,
        "text_region_count": len(words),
        "image_region_count": len(images),
        "price_candidate_count": len(price_candidates),
        "primary_price_candidate_count": len(primary_price_candidates),
        "price_anchor_candidate_count": len(price_anchor_candidates),
        "product_boundaries_proven": 0,
        "verified_product_identities": 0,
        "automatic_offer_links": 0,
    }


def _read_pdf(path: Path, expected_sha256: str) -> bytes:
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
        raise InferenceRunnerError("malformed PDF SHA256")
    if path.is_symlink():
        raise InferenceRunnerError("invalid PDF path")
    path = path.resolve(strict=True)
    if not path.is_file():
        raise InferenceRunnerError("invalid PDF path")
    size = path.stat().st_size
    if not 0 < size <= MAX_PDF_BYTES:
        raise InferenceRunnerError("PDF size outside limit")
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != expected_sha256:
        raise InferenceRunnerError("PDF SHA256 mismatch")
    return raw


def parse_pages(spec: str, page_count: int) -> list[int]:
    if not isinstance(spec, str) or not spec.strip():
        raise InferenceRunnerError("missing page selection")
    if type(page_count) is not int or not 1 <= page_count <= MAX_PAGES:
        raise InferenceRunnerError("invalid PDF page count")

    pages: set[int] = set()
    for token in spec.split(","):
        token = token.strip()
        if not token:
            raise InferenceRunnerError("empty page token")
        if "-" in token:
            parts = token.split("-")
            if len(parts) != 2 or not all(part.isdigit() for part in parts):
                raise InferenceRunnerError("malformed page range")
            start, end = map(int, parts)
            if start > end:
                raise InferenceRunnerError("descending page range")
            pages.update(range(start, end + 1))
        elif token.isdigit():
            pages.add(int(token))
        else:
            raise InferenceRunnerError("malformed page number")

    ordered = sorted(pages)
    if not ordered or len(ordered) > MAX_SAMPLE_PAGES:
        raise InferenceRunnerError("sample page count outside limit")
    if ordered[0] < 1 or ordered[-1] > page_count:
        raise InferenceRunnerError("sample page outside PDF")
    return ordered


def parse_florence_price_regions(values: list[str] | None) -> dict[int, set[str]] | None:
    if values is None:
        return None
    if not 1 <= len(values) <= MAX_FLORENCE_PRICE_CROPS:
        raise InferenceRunnerError("Florence price crop count outside PoC limit")

    parsed: dict[int, set[str]] = {}
    for value in values:
        match = re.fullmatch(r"([1-9]\d*):(native-word-[1-9]\d*)", value or "")
        if match is None:
            raise InferenceRunnerError("malformed Florence price crop selection")
        page_number = int(match.group(1))
        region_id = match.group(2)
        bucket = parsed.setdefault(page_number, set())
        if region_id in bucket:
            raise InferenceRunnerError("duplicate Florence price crop selection")
        bucket.add(region_id)
    return parsed


def _json_value(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise InferenceRunnerError("model result JSON is malformed") from exc
        if isinstance(parsed, dict):
            return parsed
    raise InferenceRunnerError("model result is not a JSON object")


def _paddle_result_to_json(result) -> dict:
    value = getattr(result, "json", None)
    if callable(value):
        value = value()
    return _json_value(value)


class PaddleBackend:
    def __init__(
        self,
        *,
        det_model_dir: Path | None,
        rec_model_dir: Path | None,
        allow_model_download: bool,
    ) -> None:
        if (det_model_dir is None) != (rec_model_dir is None):
            raise InferenceRunnerError("both PaddleOCR model directories are required together")
        if det_model_dir is None and not allow_model_download:
            raise InferenceRunnerError(
                "offline PaddleOCR requires --paddle-det-model-dir and --paddle-rec-model-dir"
            )

        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise InferenceRunnerError("PaddleOCR is not installed in this PoC environment") from exc

        kwargs = {
            "lang": "de",
            "ocr_version": "PP-OCRv6",
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
            "engine": "paddle",
        }
        if det_model_dir is not None:
            if det_model_dir.is_symlink() or rec_model_dir.is_symlink():
                raise InferenceRunnerError("PaddleOCR model directory is invalid")
            det = det_model_dir.resolve(strict=True)
            rec = rec_model_dir.resolve(strict=True)
            if not det.is_dir() or not rec.is_dir():
                raise InferenceRunnerError("PaddleOCR model directory is invalid")
            kwargs["text_detection_model_dir"] = str(det)
            kwargs["text_recognition_model_dir"] = str(rec)
        self._ocr = PaddleOCR(**kwargs)

    def predict_file(self, path: Path) -> dict:
        results = list(self._ocr.predict(str(path)))
        if len(results) != 1:
            raise InferenceRunnerError("unexpected PaddleOCR result count")
        return _paddle_result_to_json(results[0])


def _validate_florence_generation(max_new_tokens: int, num_beams: int) -> tuple[int, int]:
    if type(max_new_tokens) is not int or not 64 <= max_new_tokens <= 2048:
        raise InferenceRunnerError("Florence max_new_tokens outside PoC limit")
    if type(num_beams) is not int or not 1 <= num_beams <= 5:
        raise InferenceRunnerError("Florence num_beams outside PoC limit")
    return max_new_tokens, num_beams


class FlorenceBackend:
    TASK = "<DENSE_REGION_CAPTION>"

    def __init__(
        self,
        *,
        model_ref: str,
        device: str,
        allow_model_download: bool,
        max_new_tokens: int = 1024,
        num_beams: int = 3,
    ) -> None:
        if not isinstance(model_ref, str) or not model_ref or len(model_ref) > 300:
            raise InferenceRunnerError("invalid Florence model reference")
        if device not in {"auto", "cpu", "cuda"}:
            raise InferenceRunnerError("invalid Florence device")
        max_new_tokens, num_beams = _validate_florence_generation(
            max_new_tokens,
            num_beams,
        )

        try:
            import torch
            from transformers import AutoProcessor, Florence2ForConditionalGeneration
        except ImportError as exc:
            raise InferenceRunnerError(
                "Florence-2 PoC requires torch and transformers in the PoC environment"
            ) from exc

        resolved_device = device
        if resolved_device == "auto":
            resolved_device = "cuda" if torch.cuda.is_available() else "cpu"
        if resolved_device == "cuda" and not torch.cuda.is_available():
            raise InferenceRunnerError("CUDA requested but unavailable")

        local_only = not allow_model_download
        try:
            processor = AutoProcessor.from_pretrained(
                model_ref,
                local_files_only=local_only,
            )
            model = Florence2ForConditionalGeneration.from_pretrained(
                model_ref,
                local_files_only=local_only,
            )
        except OSError as exc:
            mode = "local-only" if local_only else "download-enabled"
            raise InferenceRunnerError(f"Florence model load failed in {mode} mode") from exc

        self._torch = torch
        self._processor = processor
        self._device = resolved_device
        self._dtype = torch.bfloat16 if resolved_device == "cuda" else torch.float32
        self._model = model.to(resolved_device)
        self._max_new_tokens = max_new_tokens
        self._num_beams = num_beams

    def predict_png(self, png: bytes) -> dict:
        try:
            from PIL import Image
        except ImportError as exc:
            raise InferenceRunnerError("Pillow is required for Florence-2 inference") from exc

        image = Image.open(BytesIO(png)).convert("RGB")
        inputs = self._processor(
            text=self.TASK,
            images=image,
            return_tensors="pt",
        )
        inputs = {
            key: value.to(self._device, self._dtype)
            if key == "pixel_values"
            else value.to(self._device)
            for key, value in inputs.items()
        }
        with self._torch.inference_mode():
            generated_ids = self._model.generate(
                **inputs,
                max_new_tokens=self._max_new_tokens,
                num_beams=self._num_beams,
            )
        generated = self._processor.batch_decode(
            generated_ids,
            skip_special_tokens=False,
        )[0]
        parsed = self._processor.post_process_generation(
            generated,
            task=self.TASK,
            image_size=(image.width, image.height),
        )
        if not isinstance(parsed, dict):
            raise InferenceRunnerError("Florence parsed result is not an object")
        return parsed


def run_inference(
    pdf_raw: bytes,
    pages: list[int],
    *,
    paddle=None,
    florence=None,
    render_dpi: int = 160,
    include_native: bool = False,
    florence_price_regions: dict[int, set[str]] | None = None,
) -> dict:
    import fitz

    if paddle is None and florence is None and not include_native:
        raise InferenceRunnerError("at least one inference backend is required")
    if florence_price_regions is not None and florence is None:
        raise InferenceRunnerError("Florence price crops require Florence backend")
    if type(render_dpi) is not int or not 96 <= render_dpi <= 240:
        raise InferenceRunnerError("render DPI outside PoC limit")
    if florence_price_regions is not None:
        if set(florence_price_regions) - set(pages):
            raise InferenceRunnerError("Florence price crop page outside selection")
        if sum(len(value) for value in florence_price_regions.values()) > MAX_FLORENCE_PRICE_CROPS:
            raise InferenceRunnerError("Florence price crop count outside PoC limit")

    output = []
    with fitz.open(stream=pdf_raw, filetype="pdf") as document, tempfile.TemporaryDirectory(
        prefix="hermes-netto-recognition-"
    ) as temp_dir:
        if document.needs_pass or not 1 <= document.page_count <= MAX_PAGES:
            raise InferenceRunnerError("unusable PDF")
        if pages != parse_pages(",".join(map(str, pages)), document.page_count):
            raise InferenceRunnerError("page selection is not canonical")

        scale = render_dpi / 72.0
        matrix = fitz.Matrix(scale, scale)
        for page_number in pages:
            started = time.perf_counter()
            page = document[page_number - 1]
            pix = page.get_pixmap(matrix=matrix, alpha=False, annots=False)
            if not 100 <= pix.width <= 10000 or not 100 <= pix.height <= 15000:
                raise InferenceRunnerError("rendered page dimensions outside limit")
            png = pix.tobytes("png")
            row = {
                "page_number": page_number,
                "image_width": pix.width,
                "image_height": pix.height,
            }
            native = None
            if include_native or florence_price_regions is not None:
                native = native_page_structure(page)
                row["native"] = native
            if paddle is not None:
                image_path = Path(temp_dir) / f"page-{page_number:03d}.png"
                image_path.write_bytes(png)
                row["paddle"] = paddle.predict_file(image_path)
            if florence is not None:
                if florence_price_regions is None:
                    row["florence"] = florence.predict_png(png)
                else:
                    requested = florence_price_regions.get(page_number, set())
                    candidates = {
                        candidate["price_region_id"]: candidate
                        for candidate in native["price_anchor_candidates"]
                    }
                    missing = requested - set(candidates)
                    if missing:
                        raise InferenceRunnerError(
                            "Florence price crop selection is not a native price anchor"
                        )
                    crop_rows = []
                    for candidate in native["price_anchor_candidates"]:
                        price_region_id = candidate["price_region_id"]
                        if price_region_id not in requested:
                            continue
                        x, y, width, height = candidate["crop_bbox"]
                        clip = fitz.Rect(
                            x * page.rect.width,
                            y * page.rect.height,
                            (x + width) * page.rect.width,
                            (y + height) * page.rect.height,
                        )
                        crop_pix = page.get_pixmap(
                            matrix=matrix,
                            clip=clip,
                            alpha=False,
                            annots=False,
                        )
                        if not 64 <= crop_pix.width <= 10000 or not 64 <= crop_pix.height <= 15000:
                            raise InferenceRunnerError("rendered Florence crop outside limit")
                        crop_rows.append(
                            {
                                "candidate_id": candidate["candidate_id"],
                                "price_region_id": price_region_id,
                                "price_text": candidate["price_text"],
                                "crop_bbox": candidate["crop_bbox"],
                                "image_width": crop_pix.width,
                                "image_height": crop_pix.height,
                                "florence": florence.predict_png(crop_pix.tobytes("png")),
                                "product_boundary_proven": False,
                                "verified_product_identity": None,
                                "hermes_offer_link": None,
                                "state": "REVIEW_ONLY",
                            }
                        )
                    row["florence_price_crops"] = crop_rows
            row["runtime_seconds"] = round(time.perf_counter() - started, 3)
            output.append(row)
    return {"pages": output}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--pdf-sha256", required=True)
    parser.add_argument("--pages", required=True, help="e.g. 2,17,31,44 or 2-5")
    parser.add_argument(
        "--backend",
        choices=("native", "paddle", "florence", "both"),
        default="both",
    )
    parser.add_argument("--render-dpi", type=int, default=160)
    parser.add_argument(
        "--include-native",
        action="store_true",
        help="Include PyMuPDF source-native text, image and price-token geometry.",
    )
    parser.add_argument("--paddle-det-model-dir", type=Path)
    parser.add_argument("--paddle-rec-model-dir", type=Path)
    parser.add_argument(
        "--florence-model",
        default="microsoft/Florence-2-base",
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cpu", "cuda"),
        default="auto",
    )
    parser.add_argument(
        "--allow-model-download",
        action="store_true",
        help="Explicitly allow model libraries to fetch missing weights. Default is offline.",
    )
    parser.add_argument(
        "--florence-max-new-tokens",
        type=int,
        default=1024,
        help="Bound Florence generation length; RPi5 PoC should start at 384.",
    )
    parser.add_argument(
        "--florence-num-beams",
        type=int,
        default=3,
        help="Florence beam count; RPi5 PoC should use 1.",
    )
    parser.add_argument(
        "--florence-price-region",
        action="append",
        metavar="PAGE:NATIVE-WORD-ID",
        help=(
            "Run Florence only on an explicit native price-anchor crop, e.g. "
            "20:native-word-57. Repeat up to 12 times. Full-page Florence is skipped."
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    output = args.output.resolve()
    if output.exists() or output.is_symlink():
        raise InferenceRunnerError("will not overwrite inference evidence")

    pdf_raw = _read_pdf(args.pdf, args.pdf_sha256)
    import fitz

    with fitz.open(stream=pdf_raw, filetype="pdf") as document:
        pages = parse_pages(args.pages, document.page_count)
    florence_price_regions = parse_florence_price_regions(args.florence_price_region)
    if florence_price_regions is not None:
        if args.backend not in {"florence", "both"}:
            raise InferenceRunnerError("Florence price crops require Florence backend")
        if set(florence_price_regions) - set(pages):
            raise InferenceRunnerError("Florence price crop page outside selection")

    paddle = None
    florence = None
    started = time.perf_counter()
    if args.backend in {"paddle", "both"}:
        paddle = PaddleBackend(
            det_model_dir=args.paddle_det_model_dir,
            rec_model_dir=args.paddle_rec_model_dir,
            allow_model_download=args.allow_model_download,
        )
    if args.backend in {"florence", "both"}:
        florence = FlorenceBackend(
            model_ref=args.florence_model,
            device=args.device,
            allow_model_download=args.allow_model_download,
            max_new_tokens=args.florence_max_new_tokens,
            num_beams=args.florence_num_beams,
        )

    include_native = (
        args.include_native
        or args.backend == "native"
        or florence_price_regions is not None
    )
    result = run_inference(
        pdf_raw,
        pages,
        paddle=paddle,
        florence=florence,
        render_dpi=args.render_dpi,
        include_native=include_native,
        florence_price_regions=florence_price_regions,
    )
    result["runner"] = {
        "backend": args.backend,
        "render_dpi": args.render_dpi,
        "include_native": bool(include_native),
        "model_download_allowed": bool(args.allow_model_download),
        "florence_price_regions": args.florence_price_region or [],
        "florence_model": args.florence_model if args.backend in {"florence", "both"} else None,
        "florence_max_new_tokens": (
            args.florence_max_new_tokens if args.backend in {"florence", "both"} else None
        ),
        "florence_num_beams": (
            args.florence_num_beams if args.backend in {"florence", "both"} else None
        ),
        "wall_seconds": round(time.perf_counter() - started, 3),
        "peak_rss_kib": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
    print(
        json.dumps(
            {
                "backend": args.backend,
                "pages": pages,
                "include_native": bool(include_native),
                "model_download_allowed": bool(args.allow_model_download),
                "florence_price_crop_count": sum(
                    len(value) for value in (florence_price_regions or {}).values()
                ),
                "peak_rss_kib": result["runner"]["peak_rss_kib"],
                "wall_seconds": result["runner"]["wall_seconds"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())