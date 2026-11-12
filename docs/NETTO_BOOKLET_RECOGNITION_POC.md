# Netto booklet product-recognition PoC

Issue: #1140  
Parent: #1069  
Related hotspot integrity work: #1123, #289, #27.

## Decision boundary

The existing Hermes booklet viewer is retained. This PoC evaluates only whether open-source
vision/OCR can create useful **Review-only product-region candidates** for a real Netto booklet.

The first target is the next Netto 5659 validity window expected for **2026-11-16 through
2026-11-21**. The exact publication slug, URL, validity, PDF SHA256 and page count must come
from the actually published first-party source. Do not infer them from the week number.

No OCR or vision result is a product identity proof. A candidate must remain Review-only until
an independent first-party identifier bridge proves exactly one eligible Hermes offer.

## Components

### Source-native PyMuPDF baseline

For PDFs with a usable native text layer, use PyMuPDF before OCR. The baseline records:
- word-level text boxes;
- visible image boxes without extracting image bytes;
- price-like text tokens as Review-only anchors;
- normalized 0..1 geometry, with zero product identity or automatic offer links.

The current Netto `hz46_hasb_4` evidence demonstrates that this path is useful: representative
physical-store pages already expose machine-readable product text, prices and image geometry.
Naive proximity still does not prove a product boundary, so Florence-2 remains a candidate for
ambiguous visual grouping.

Run a model-free baseline with:

```bash
python3 tools/netto_booklet_recognition_inference.py \
  --pdf /path/to/source.pdf \
  --pdf-sha256 <exact_sha256> \
  --pages 1,4,20,40,60 \
  --backend native \
  --output /path/to/native-results.json
```

For a direct comparison on the same pages, use `--backend florence --include-native`.

### RPi5 Florence guardrails

The first real Florence run is intentionally staged for the 4 GB RPi5:

1. run the model-free native baseline first;
2. run Florence on **one page only** with `--render-dpi 96`,
   `--florence-max-new-tokens 384` and `--florence-num-beams 1`;
3. review peak RSS, swap use, temperature/throttling and result completeness;
4. only if the one-page run is healthy, process pages 1, 4, 20, 40 and 60 sequentially
   with the same limits.

The runner accepts `--florence-max-new-tokens` only in 64..2048 and
`--florence-num-beams` only in 1..5. Defaults remain 1024/3 for non-constrained
hosts; the reduced RPi5 values must be explicitly selected.

No service stop/restart, Docker mutation, scheduler change or production write is required
for this PoC. The isolated process should be run at low priority and must fail closed on
OOM, thermal/runtime error or unexpected host drift.

### PaddleOCR

Fallback OCR/layout candidate for image-only or unusable-text PDFs:

- project: https://github.com/PaddlePaddle/PaddleOCR
- current researched release: **3.7.0** (2026-06-11)
- license: **Apache-2.0**
- PP-OCRv6 is the current general OCR family; PaddleOCR documentation states that it supports
  German and provides recognized text, confidence scores and pixel-space recognition boxes.
- the PoC normalizer consumes the documented `rec_texts`, `rec_scores`, and `rec_boxes`
  result fields.

The Hermes production requirements are intentionally unchanged. PaddleOCR is not added to
`backend/requirements.txt` or `runtime-requirements.lock`.

### Florence-2

Optional second-stage region candidate:

- model family: https://huggingface.co/microsoft/Florence-2-base
- license: **MIT**
- use the **base** model first for the PoC; the large model is materially heavier.
- candidate tasks: `<DENSE_REGION_CAPTION>`, `<REGION_PROPOSAL>`, or targeted
  `<CAPTION_TO_PHRASE_GROUNDING>`.
- the normalizer currently accepts the documented dense-region result shape:
  `{"<DENSE_REGION_CAPTION>": {"bboxes": [...], "labels": [...]}}`.

Florence output remains vision evidence only. A caption such as "chocolate bar" or a visually
plausible brand must not become an automatic SKU or Hermes offer link.

## PoC data flow

```text
exact next-week Netto PDF + SHA256
        |
        +--> PaddleOCR result JSON
        |
        +--> optional Florence-2 parsed result JSON
        |
        v
tools/netto_booklet_recognition_poc.py
        |
        v
normalized Review-only JSON
  - OCR text boxes
  - OCR price-neighborhood candidates
  - optional vision regions
  - OCR text intersecting each vision region
  - automatic_offer_links = 0
  - verified_product_identities = 0
```

The output geometry is normalized as `[x, y, width, height]` in the 0..1 page coordinate
space used for later viewer/hotspot evaluation.

## Model-result input

The normalizer itself performs no network access and downloads no models. Model execution is
kept separate so the repository CI never downloads large weights.

### Local inference runner

`tools/netto_booklet_recognition_inference.py` renders only an explicit sample of at most
12 SHA-pinned PDF pages and produces the model-result JSON consumed by the normalizer.

The runner is **offline by default**:
- PaddleOCR requires explicit local detection and recognition model directories.
- Florence-2 uses `local_files_only=True` unless `--allow-model-download` is explicitly set.
- `--allow-model-download` changes only the tool's local behavior; using it on an RPi5 or
  other retained/runtime environment still requires the applicable owner authorization.
- no model package is added to Hermes production dependencies.

The current source contract follows PaddleOCR 3.7 / PP-OCRv6's documented `predict()`
result fields and Hugging Face Transformers Florence-2
`<DENSE_REGION_CAPTION>` + `post_process_generation()` API.

Example offline invocation after weights already exist locally:

```bash
python3 tools/netto_booklet_recognition_inference.py \
  --pdf /path/to/source.pdf \
  --pdf-sha256 <exact_sha256> \
  --pages 2,17,31,44 \
  --backend both \
  --paddle-det-model-dir /path/to/PP-OCRv6-det \
  --paddle-rec-model-dir /path/to/PP-OCRv6-rec \
  --florence-model /path/to/Florence-2-base \
  --device cpu \
  --output /path/to/model-results.json
```

The output also records wall time, per-page time and peak process RSS for the PoC resource
assessment.

Example input:

```json
{
  "pages": [
    {
      "page_number": 7,
      "image_width": 1600,
      "image_height": 2263,
      "paddle": {
        "res": {
          "rec_texts": ["Milka Alpenmilch", "100 g", "0,99 €"],
          "rec_scores": [0.98, 0.93, 0.99],
          "rec_boxes": [[120, 100, 490, 150], [130, 160, 230, 195], [390, 205, 500, 270]]
        }
      },
      "florence": {
        "<DENSE_REGION_CAPTION>": {
          "bboxes": [[80, 60, 550, 360]],
          "labels": ["a chocolate product block"]
        }
      }
    }
  ]
}
```

Run after the exact first-party PDF and model results exist:

```bash
python3 tools/netto_booklet_recognition_poc.py \
  --pdf /path/to/source.pdf \
  --pdf-sha256 <exact_sha256> \
  --model-results /path/to/model-results.json \
  --store 5659 \
  --valid-from 2026-11-16 \
  --valid-to 2026-11-21 \
  --publication-url <exact_first_party_url> \
  --output /path/to/review-only.json
```

The command fails closed on wrong SHA, store, validity shape, duplicate/out-of-range pages,
invalid model geometry, malformed result arrays and an existing output path.

## Evaluation

Start with a small representative sample rather than the whole booklet:

1. text-heavy product grid;
2. image-heavy product page;
3. mixed promotional/multi-product page;
4. one difficult page with small, rotated, dense or overlapping content.

Record separately:

- product/brand/title OCR accuracy;
- printed price accuracy;
- package/quantity accuracy;
- product-region localization quality;
- false region count;
- whether OCR-only price-neighborhood candidates are useful;
- whether Florence materially improves region localization;
- runtime, peak RAM and retained model size on the actual execution host.

Where the exact first-party publication includes publisher hotspots, they may be used as
**geometry evaluation evidence** after exact publication/SHA/page alignment is verified. They
must not be treated as Hermes offer identity merely because the rectangles overlap.

## Outcome

The real next-week result should end in exactly one practical decision:

- **GO** — useful primary candidate generator;
- **HYBRID** — useful only as OCR/layout or second-stage assistance;
- **NO-GO** — accuracy or resource cost is not worthwhile.

No production DB write, collector promotion, clickable offer activation, deployment or retained
model/PDF acquisition is part of this source-only PoC.