# Netto 5659: offline PDF / Publitas page-alignment preflight (#1123)

**Scope:** source-only comparison preparation. No new publisher images are downloaded by this tool; it has no URL, network, DB, collector, or UI interaction. It does not update publication evidence or display overlays.

## Current exact evidence (2026-11-03)

- User-supplied hz45_hasb PDF: 74 pages, SHA256 427206ea8ad9a5e1c54512f380a4f3cf5ab2939dd67bfab051b3232c5e47a5a6.
- Already-retained Netto store 5659 Publitas regionale-hz/hz45_hasb publication: 72 unique page identifiers, 72 one-page spreads, at1600 dimensions 1352x1893, publication JSON SHA256 a72414e732435504d7524a9bb707a069753f600f31638118f9f947e425236c45.
- Existing 38-product receipt SHA256 ca579d8500771cdf58a475a11881146c38675ce128b8ea702020c951564c9edc: 38 product hotspots on only seven pages (44, 45, 46, 47, 66, 67, 69), including nine on page 44. Not verified Hermes eligible offers.
- Publisher page paths are identifiers, not image byte hashes. The 72 image bytes were not acquired in the 2026-11-03 read-only protected-source check, so no real visual alignment has been established.

## Offline local-only ranking

The new tool tools/netto_pdf_publication_alignment.py accepts the SHA-pinned PDF, original publication JSON, and a **complete separate local image manifest with all actual image bytes**. It verifies source SHA256, exact ordered publication page IDs, each local image hash, safe filenames, dimensions and complete image count. Missing/altered inputs fail closed.

Example once separate image acquisition has been authorized and the capture has produced independently verified provenance:

    python3 tools/netto_pdf_publication_alignment.py \
      --pdf /path/to/retained-input.pdf \
      --pdf-sha256 427206ea8ad9a5e1c54512f380a4f3cf5ab2939dd67bfab051b3232c5e47a5a6 \
      --publication /path/to/verified-hz45-hasb-publication.json \
      --publication-sha256 a72414e732435504d7524a9bb707a069753f600f31638118f9f947e425236c45 \
      --image-manifest /path/to/pinned-local-image-manifest.json \
      --image-root /path/to/verified-local-page-images \
      --output /tmp/netto-pdf-alignment-review.json

Manifest (schematic, not real source or production receipt):

    {
      "publication_sha256": "<exact-64-hex-publication-SHA>",
      "pages": [{
        "publication_page_number": 1,
        "publication_page_identifier": "/100989/3490849/pages/<actual-first-party-page-id>",
        "filename": "001.jpg",
        "sha256": "<exact-64-hex-image-SHA>"
      }]
    }

All 72 rows must actually exist in exact publication order. Filenames must be bare local PNG/JPG, not URLs or traversal. Image SHA256 verifies bytes, **not** where the image came from. An independently authorized capture receipt must prove original first-party image provenance.

Tool renders both sources at a fixed grayscale 48x72 thumbnail, ranks each Publitas page against every PDF page by normalized mean-absolute pixel distance, and exports nearest 3 PDF candidates with ambiguity/weak-signal warnings. The method is only a review heuristic: cropping, bleed, compression, or publisher page differences can change rank; a visually similar page does not establish exact content or unique correspondence. Ties/duplicates remain ambiguous. All output has state REVIEW_ONLY, verified_page_alignments=0 and verified_offer_links=0 by construction.

## Acceptance gate before app integration

1. Verify one-to-one source provenance of the **72 original page images**, bound to store 5659, exact publication SHA, date/validity, each publisher page ID and immutable byte hashes. New image acquisition/retention, RPi5 capture, or production changes need **separate explicit LIVE authorization**.
2. Run offline ranking using a complete checked manifest and manually inspect all 72 proposed pairs and both PDF-only pages; specially inspect page 44 and ambiguous cases. Do not assume the extra PDF pages are first or last, or assume a page shift from image rank.
3. Record human-reviewed mapping receipt by separately authorized workflow, with exact source and page image provenance. Until then, no publisher page can be mapped into PDF as verified.
4. Even with verified image alignment, a product-to-Hermes offer link additionally needs a separately proven official SKU bridge. Previously, 38 publisher product details vs 191 eligible HTML SKUs had zero direct matches. Do not promote physical-store coverage from online-only PDF pages.

No frontend or runtime change; retain fullscreen, desktop zoom, mobile pinch/swipe, URL navigation. Synthetic tests exercise safety only, not actual publisher match. Rendering API follows PyMuPDF Page.get_pixmap documentation.
