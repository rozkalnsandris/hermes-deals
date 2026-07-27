# Phase 2B6 — Targeted Lidl OCR feasibility

Phase 2B5R proved that Lidl's public v4 flyer JSON is reliable for metadata and page images, but grocery prices are mostly absent from scalar JSON fields. Only 8/69 current pages exposed price-like scalar tokens while grocery terms appeared on 66/69 pages.

Phase 2B6 is intentionally a feasibility step, not a production parser and not a DB-write step.

## Strategy

- Keep the API container lean.
- Build the one-shot worker from `backend/Dockerfile.ocr` with Debian Bookworm Tesseract + German/English language data.
- Select representative grocery pages that have no usable scalar price metadata, plus small control samples.
- Download the existing Lidl `zoom` page image.
- Run Tesseract with `deu+eng`, page segmentation mode 11 (sparse text), and TSV output.
- Preserve OCR word geometry, confidence, reconstructed lines, and price-like candidates.
- Save images, TSV and plain text in `data/raw/lidl-analysis/<timestamp>-lidl-ocr-sample/`.
- Do not write Lidl offers to PostgreSQL yet.

## Decision gate

The deployment remains successful even if OCR quality is mediocre: this phase measures quality. It rolls back only when the OCR runtime itself is broken, required language data is missing, or too few sample pages can be processed.

The report recommendation is one of:

- `targeted_ocr_parser_candidate`
- `ocr_text_good_price_pairing_needs_geometry`
- `ocr_strategy_unresolved`

A later phase may use TSV geometry to associate price boxes with nearby product names, but only if this sample proves the OCR layer is useful.
