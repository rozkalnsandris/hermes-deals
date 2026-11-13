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
- prior in-memory native scan: 686 Review candidates on 77/80 pages; pages
  69–71 had zero candidates. That scan deliberately produced no output file.

## Source implementation

`tools/netto_pdf_review_projection.py` accepts a retained native marker
manifest, the exact alignment Review, and the exact image manifest. It fails
closed unless every page pair is same-ordinal one-to-one and every marker is
still Review-only with no product/offer identity. It emits a deterministic
publication-page projection.

`app.netto_booklet_review_layer` reads only an exact SHA-pinned projection
from `netto-html/review-layers/`. The HZ46 trust entry intentionally has
`review_markers_sha256=None` and `projection_sha256=None` until a separate
owner-authorized retained projection is created. Therefore this source change
cannot activate Review hotspots by itself.

When enabled later, the UI uses the same image transform as the existing 13
publisher-only HZ46 hotspots, but Review buttons are visually distinct and the
dialog explicitly says the product, price, and Hermes relationship are
unverified. Jinja escaping and JavaScript `textContent` remain the text
boundary.

## Next gate

Create the exact 80-page native marker manifest and deterministic projection
under a separately authorized LIVE retained-evidence write. Verify their SHA256
values, then pin those two hashes in the source branch and rerun CI. No DB,
collector, deploy, offer mapping, or Review/publication mutation is part of that
gate.
