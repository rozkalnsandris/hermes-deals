# Netto HZ47 — five-page PDF-native text/price pilot (#1185)

Status: **source-only experimental diagnostic, REVIEW_ONLY, unpromotable**.
This replaces neither #1181/#1182 nor HZ46 product-card Review; no runtime
overlay, offer/PDF publication activation, database, collector or host mutation
is authorized or implemented by this source branch.

## Immutable scope

- Exact user-provided source file: hz47_hasb.pdf; 72 PDF pages and 39,976,532
  bytes; SHA256 c8551dd197ac3050e11a9419a73b174803e5b8684890404b10b77520d3e7436a.
- Pilot pages: 1, 21, 34, 49 and 57 **only**.
- Optional label hints: the still-unmerged #1182 geometry draft, which contains
  261 unverified product-card rectangles across 49 pages. Its rectangles are
  **not** clickable targets or product-identity evidence.
- The PDF is user-supplied, not independently verified as publisher-PDF bytes.
  Previous 72-page visual ordinal ranking does not prove specific price
  ownership, a selected-store publication binding, or exact rendered overlay
  eligibility. Fail closed until independent image/page/store provenance exists.

## Extractor and local diagnostic

The offline source-only tool is tools/netto_hz47_text_price_pilot.py.
It uses PyMuPDF native word coordinates; there is no OCR or speculative
product/price matching by default. It recognizes PDF word-shaped decimal,
split-major/cents (including 2 49*) and dash-price patterns as **unverified
candidates**, not authoritative retail prices. Flags cover nearby UVP, APP,
PAYBACK, unit-price, deposit and bundle terms. Missed/multiline/ambiguous
labels or split prices require manual review; a text-shaped price is not
evidence that it belongs to the nearest title.

The source PDF and optional draft are SHA/shape guarded; local output declares
zero verified identities/offer links and publication_ready=false. Output page
records preserve original word coordinates, word-set SHA256 and normalized,
positive top-left rectangles. Rendering writes new offline page PNGs plus
their SHA256, a review_only.json report and standalone pageXX.html previews.
Output must be a **nonexistent scratch directory**; the tool does not overwrite
previous results. It never writes to a retailer snapshot or runtime source.

Local-only command when the exact authorized PDF is present:

    python tools/netto_hz47_text_price_pilot.py /path/to/hz47_hasb.pdf --draft /path/to/hz47_manual_pdf_geometry_draft_v1.json --output-dir /tmp/hz47-pilot-unique

Without --draft the extractor produces price-shaped anchors only, without
title candidates. All target regions start noninteractive. Optional explicit
source-local pairing requires a PDF-hash-matched JSON review with schema
hermes.netto.hz47.source_local_link_review.v1, reviewed_against_source=true,
exact label and headline-price anchor IDs, and substantive human rationale.
A pair is rejected if it overlaps another text anchor or has conflicting
APP/PAYBACK/UVP/unit/deposit/bundle flags. Invalid later pair review cannot
partially activate earlier pairs. Even accepted pairs only open the **same
unverified source candidate** in an offline dialog: no Hermes offer/product,
price, discount, shopping-list or validity relationship is asserted.

The HTML is a visual diagnostic, not the live reader. It preserves native
PDF coordinates on its *own* rendered PDF image. It does not establish a
publisher-image transform, 44px mobile tappability, zoom/gesture correctness,
or production UI behavior. The real five pages and exact first-party publisher
images must be reviewed together before any live hotspot path is developed.

## Evidence, tests and missing acceptance

- Existing synthetic fixture tests are in
  backend/tests/test_netto_hz47_text_price_pilot.py. Local isolated tests:
  **9 passed** for split price, invalid geometry, UVP rejection, duplicate
  and overlapping targets, atomic review, source-only candidate association
  and safe HTML escaping. CI after the final PR head is authoritative.
- The original PDF bytes were **not available to this source workspace** for
  the actual five-page extraction. There are **no verified counts** of visible
  eligible groups, correct native titles, owned headline prices, both-anchor
  associations, false positives, manual corrections, or phone usability.
- Required next proof: read exact PDF bytes on an authorized source surface;
  verify per-page rendered source/publisher identities; annotate all five
  pages at full resolution; report eligible groups, matched labels/prices,
  ambiguity and error counts against #1182's card method. Require explicit
  reviewer decisions for conditional APP/PAYBACK, variants and multiple
  prices, and keep ambiguous words/candidates disabled.
- Test both linked anchor types with desktop keyboard and mobile touch, pan,
  pinch, double-click, swipe, zoom and fullscreen on exact page images before
  declaring the five-page pilot accepted.
- **Only a separate owner decision** may extend to all 72 pages, replace
  #1182, merge, or authorize LIVE runtime/deploy/retained Review writes.

No unverified source-only data may be relabeled as a validated product, offer,
price, selected-store publication, or full booklet coverage.
