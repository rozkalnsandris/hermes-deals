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
from `netto-html/review-layers/`. The HZ46 trust entry now pins the exact
retained marker/projection SHA256 values above. This source pinning does not
copy or activate host evidence: runtime placement of the exact projection under
that directory remains a separate LIVE gate.

When enabled later, the UI uses the same image transform as the existing 13
publisher-only HZ46 hotspots, but Review buttons are visually distinct and the
dialog explicitly says the product, price, and Hermes relationship are
unverified. Jinja escaping and JavaScript `textContent` remain the text
boundary.

## Next gate

After source review/merge, place only the exact SHA-pinned retained projection
into the approved runtime `netto-html/review-layers/` location under a separate
LIVE authorization, then perform read-only UI acceptance. No DB, collector,
offer mapping, product identity, or Review/publication write is implied by the
source pinning.
