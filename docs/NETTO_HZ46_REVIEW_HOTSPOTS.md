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

## Accepted v1 UI proof

The v1 price-group layer is intentionally not the final product-card UX. Its
purpose was to prove the retained PDF → publication-page projection → browser
click chain without inventing product identity. On 2026-11-13 the live canary
confirmed all 686 Review-only v1 markers render, and candidate `p001-g002`
opened the expected unverified Hähnchen-Brustfilet dialog. That acceptance is
recorded on #1069.

## Product-card Review v2 source lane

V2 keeps price geometry only as an anchor and derives a larger Review-only card
from source-native PDF structure. PyMuPDF documents positional word extraction
through `Page.get_text("words")`, drawing geometry through
`Page.get_drawings()`, and image geometry through page image information.
Those spatial APIs are used instead of assuming PDF text extraction order is the
visual product order.

References:
- https://pymupdf.readthedocs.io/en/latest/textpage.html
- https://pymupdf.readthedocs.io/en/latest/page.html
- https://pymupdf.readthedocs.io/en/latest/app1.html

The v2 rules are deliberately conservative:

- a prominent price-like token is only an anchor; calendar-looking values are
  excluded when their source text block contains weekday/year/multiple-date
  context;
- a candidate also requires substantive product text and a substantive embedded
  image; isolated prices, `KW` labels, legal disclaimers and note-only text do
  not become cards;
- substantial filled PDF rectangles are treated as hard card containers only
  when the rectangle contains exactly one primary price anchor. In that case the
  clickable Review rectangle is the PDF card rectangle itself;
- otherwise v2 falls back to a bounded price + image + local-text union and may
  reject the candidate when ownership remains ambiguous;
- every output remains `REVIEW_ONLY`, with
  `product_boundary_proven=false`, no verified product identity and no Hermes
  offer link.

The exporter is
`tools/netto_pdf_product_card_review_export.py` and writes the separate
`hermes.netto.pdf_product_card_review_markers.v2` evidence format. It does not
overwrite the accepted v1 marker manifest.

### Representative HZ46 evidence

Read-only evidence used the exact retained HZ46 PDF plus the retained native
word/image/price geometry for pages 1, 4, 20, 40 and 60. PDF filled rectangles
were independently cross-checked with `mutool trace`; this was evidence only,
not a second production parser.

| PDF page | Primary price anchors | V2 Review cards | Notes |
| --- | ---: | ---: | --- |
| 1 | 4 | 4 | Four separate filled product cards. Hähnchen 7.99, Rheinfels 4.49, Rotkäppchen/Sekt 2.99 and Meggle Butter 0.99 remain in the correct card. |
| 4 | 7 | 7 | The one large filled region contains multiple prices, so it is not trusted as a hard card; bounded fallback produced seven product-like Review cards. |
| 20 | 7 | 5 | Two ambiguous anchors fail closed; five plant product cards remain. |
| 40 | 4 | 3 | Legal/disclaimer text is not accepted as a product title; three product cards remain. |
| 60 | 6 | 3 | Dense Energy Drink layout remains conservative: three candidates are accepted and three stay unclickable rather than being guessed. |

The older v1 analyzer had examples where validity dates such as `12.11` and
`14.11` were price-like groups. The retained v2 native sample does not expose
those date tokens as primary anchors, so the contextual date exclusion is
covered by a focused regression test rather than reported as an actual v2 page
count.

This is representative geometry evidence, not full 80-page v2 coverage and not
runtime activation.

## Next gate

After source review/merge, generate a fresh v2 marker manifest from the exact
retained HZ46 PDF in an approved read-only PyMuPDF execution environment and
audit the full 80 pages before any projection or UI activation. V1 stays active
until that separate evidence gate passes. No DB, collector, offer mapping,
product identity, Review/publication write or LIVE activation is authorized by
this source lane.
