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
import tempfile
import time

MAX_PDF_BYTES = 150 * 1024 * 1024
MAX_PAGES = 300
MAX_SAMPLE_PAGES = 12


class InferenceRunnerError(ValueError):
    pass


_NATIVE_PRICE = re.compile(r"^(?:\\d{1,3}[.,]\\d{2}|\\d+[.,]-)\\*?$")


def _normalized_bbox(raw, width: float, height: float) -> list[float]:
    if (
        not isinstance(raw, (list, tuple))
        or len(raw) != 4
        or width <= 0
        or height <= 0
    ):
        raise InferenceRunnerError("invalid native PDF rectangle")
    x0, y0, x1, y1 = (float(value) for value in raw)
    if not (0 <= x0 < x1 <= width + 0.001 and 0 <= y0 < y1 <= height + 0.001):
        raise InferenceRunnerError("native PDF rectangle outside page")
    return [
        round(x0 / width, 6),
        round(y0 / height, 6),
        round((x1 - x0) / width, 6),
        round((y1 - y0) / height, 6),
    ]


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
                "bbox": _normalized_bbox(info["bbox"], width, height),
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

    return {
        "page_size_points": [round(width, 3), round(height, 3)],
        "text_regions": words,
        "image_regions": images,
        "price_candidates": price_candidates,
        "text_region_count": len(words),
        "image_region_count": len(images),
        "price_candidate_count": len(price_candidates),
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


class FlorenceBackend:
    TASK = "<DENSE_REGION_CAPTION>"

    def __init__(
        self,
        *,
        model_ref: str,
        device: str,
        allow_model_download: bool,
    ) -> None:
        if not isinstance(model_ref, str) or not model_ref or len(model_ref) > 300:
            raise InferenceRunnerError("invalid Florence model reference")
        if device not in {"auto", "cpu", "cuda"}:
            raise InferenceRunnerError("invalid Florence device")

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
                max_new_tokens=1024,
                num_beams=3,
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
) -> dict:
    import fitz

    if paddle is None and florence is None and not include_native:
        raise InferenceRunnerError("at least one inference backend is required")
    if type(render_dpi) is not int or not 96 <= render_dpi <= 240:
        raise InferenceRunnerError("render DPI outside PoC limit")

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
            if include_native:
                row["native"] = native_page_structure(page)
            if paddle is not None:
                image_path = Path(temp_dir) / f"page-{page_number:03d}.png"
                image_path.write_bytes(png)
                row["paddle"] = paddle.predict_file(image_path)
            if florence is not None:
                row["florence"] = florence.predict_png(png)
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
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    output = args.output.resolve()
    if output.exists() or output.is_symlink():
        raise InferenceRunnerError("will not overwrite inference evidence")

    pdf_raw = _read_pdf(args.pdf, args.pdf_sha256)
    import fitz

    with fitz.open(stream=pdf_raw, filetype="pdf") as document:
        pages = parse_pages(args.pages, document.page_count)

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
        )

    result = run_inference(
        pdf_raw,
        pages,
        paddle=paddle,
        florence=florence,
        render_dpi=args.render_dpi,
        include_native=args.include_native or args.backend == "native",
    )
    result["runner"] = {
        "backend": args.backend,
        "render_dpi": args.render_dpi,
        "include_native": bool(args.include_native or args.backend == "native"),
        "model_download_allowed": bool(args.allow_model_download),
        "florence_model": args.florence_model if args.backend in {"florence", "both"} else None,
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
                "include_native": bool(args.include_native or args.backend == "native"),
                "model_download_allowed": bool(args.allow_model_download),
                "peak_rss_kib": result["runner"]["peak_rss_kib"],
                "wall_seconds": result["runner"]["wall_seconds"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())