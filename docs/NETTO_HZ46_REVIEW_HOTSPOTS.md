# Netto HZ46 PDF Review hotspot projection

Scope: #1069 continuation after the 80×80 HZ46 page-order proof. This is a
Review-only path; it does not create Hermes product identity, an offer link,
price history, basket action, or promotion evidence.

## Geometry boundary

Publitas REST API v2 documents interactive hotspot coordinates as fractions of
the **spread** size: `top`, `left`, `width`, and `height` are 0–1.
Publitas also documents PDF annotation rectangles separately in PDF user-space
units. The Hermes native scan is neither of those publisher hotspot contracts:
it is PyMuPDF page-local geometry from the retained PDF, normalized to the
individual PDF page. Therefore native markers must remain a distinct
`REVIEW_ONLY` layer and must not be relabeled as Publitas product hotspots.

References:
- https://developers.publitas.com/docs/rest-v2
- https://pymupdf.readthedocs.io/en/latest/page.html

## HZ46 evidence already proven

- PDF SHA256: `9d6337beb029977cf8c119cbe2d216b4aab5052523c5e49e6bad0b102418f8cf`
- Publitas publication SHA256: `68184db39b6cb9878d6eab2e804ab767310390135e5f12772762329c661ac087`
- 80 retained first-party `at1600` page images; manifest SHA256
  `a23db82f42f2fc2ccc81802aab65b8454979d29c64967077eada59523e87764c`
- offline 80×80 alignment Review SHA256
  `0b7fe988e655597480235d927b20e9b14fa920525655e27400a5f4a333c28b93`
- best match and reverse-best match are same ordinal for all 80 pages, with
  zero mismatches.
- retained native marker manifest: 686 Review candidates on 77/80 pages; pages
  69–71 have zero candidates; SHA256
  `344ee5f838d922cb0db42c85cb2a497459c81e2233fcea6c0db3c4a5c567b709`.
- retained page-scoped projection SHA256
  `24d1b980c06bbdbb0c58cfe8f00cb4153022f0053684ce5a8e565034e0ea570c`;
  it contains zero automatic offer links and zero verified product identities.

## Source implementation

`tools/netto_pdf_review_projection.py` accepts a retained native marker
manifest, the exact alignment Review, and the exact image manifest. It fails
closed unless every page pair is same-ordinal one-to-one and every marker is
still Review-only with no product/offer identity. It emits a deterministic
publication-page projection. Native analyzer group IDs such as `g001` are
page-local and repeat on different PDF pages, so the projection namespaces them
as stable `pNNN-gNNN` candidate IDs while retaining the original value as
`source_candidate_id`. Duplicate source IDs within the same page still fail
closed.

`app.netto_booklet_review_layer` reads only an exact SHA-pinned projection
from `netto-html/review-layers/`. Runtime eligibility is bound to the selected
store, slug, exact publication SHA256, validity window, and retained projection
provenance. Collector snapshot IDs and manifest SHA256 values are observations
that can rotate while the exact publication bytes remain unchanged, so they are
not overlay eligibility keys.

The publisher-only layer follows the same runtime publication boundary. Its
retained product receipt still verifies the original snapshot/manifest strings
as capture provenance; those historical values are evidence about the retained
capture, not a requirement that every later collector observation reuse the same
snapshot ID.

The 13 November 2026 UI canary proved this distinction: snapshot
`962b80c9-a0bc-4553-8aa8-adf15857573b` produced all 686 Review candidates and
13 publisher hotspots, while later snapshot
`31bf2cc9-6d47-45b0-8d3d-63d4fc1cb0e6` referenced the same HZ46 publication
SHA256 but both overlays were hidden by the old snapshot-bound gate.

The UI uses the same image transform for publisher and Review overlays, but
Review buttons are visually distinct and the dialog explicitly says the
product, price, and Hermes relationship are unverified. Jinja escaping and
JavaScript `textContent` remain the text boundary.

## Next gate

After source review/merge, deploy the merged source under a separate LIVE
authorization, re-verify the exact runtime projection SHA, and repeat the
read-only HZ46 UI canary. No DB, collector, offer mapping, product identity, or
Review/publication write is implied by this source fix.
