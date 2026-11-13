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

This representative evidence is now supplemented by a full 80-page read-only
audit. It remains source evidence, not runtime activation.

### Full 80-page HZ46 v2 audit

The exact retained PDF SHA256
`9d6337beb029977cf8c119cbe2d216b4aab5052523c5e49e6bad0b102418f8cf`
was streamed read-only through PyMuPDF 1.28.0 against source head
`c1dc0398fa17f7d1b0c918d527daf68c3ca97bbe`. The in-memory v2 manifest
SHA256 is
`c3052232bc11794363f95e747d8b3b6629c5863bcbd46a32d533bc2d0f64a6f8`
(195481 canonical JSON bytes).

Source-native image enumeration exposed two legitimate non-product image
occurrence classes that must not terminate booklet analysis:

- a fully off-page occurrence on PDF page 62; and
- zero-dimension occurrences whose corresponding PDF image pixel dimension is
  also zero (for example page 72 `0x0` and page 73 zero-width).

Those occurrences are skipped before Review geometry is built. Other malformed
or degenerate image rectangles continue to fail closed.

Full audit totals:

- 411 primary price anchors;
- 316 Review-only product-card candidates across 69/80 pages;
- zero automatic Hermes offer links and zero verified product identities;
- zero proven product boundaries;
- 19 candidates bound to substantial filled PDF regions and 297 conservative
  fallback unions;
- zero duplicate candidate/image ownership IDs;
- zero out-of-page card geometries;
- 11 card pairs with IoU >= 0.15;
- 31 pages accepted every available primary anchor, while 42 pages intentionally
  remained partial/fail-closed.

Pages with zero v2 cards are
`9,17,18,69,70,71,72,73,75,79,80`.

The full audit is **not** a UI-activation acceptance yet. Manual review of the
representative output found remaining product-selection quality issues that the
simple automated suspicious-text regex did not flag:

- page 62 includes discount-copy candidates such as
  `pro Liter gespart -80 -80%` rather than a product title;
- pages 74/76/77 include `Online-Kracher` / online-only material, which must
  not be promoted into the physical-store product-card layer;
- 11 overlapping-card pairs still require page-level ownership review before
  projection.

These findings did not invalidate the off-page / zero-dimension PDF image fix.
They defined the next source-only quality gate while v1 stayed active.

### Product-selection quality follow-up

The follow-up source lane keeps the same Review-only trust boundary and adds
three fail-closed ownership rules:

- promo, loyalty, legal, attribute and discount-copy blocks are not eligible
  product titles; the selector may fall through to a nearby real product title;
- a card is rejected when its local source geometry explicitly says
  `nur online`; mixed pages are not rejected wholesale;
- one native PDF title block cannot belong to multiple price anchors. Material
  fallback-card overlap (IoU >= 0.15) is also rejected unless a single-price
  filled PDF region provides the stronger boundary.

The exact retained HZ46 PDF was re-audited read-only on source head
`70414cff39fd77680efe411b74ede0b567ffa81a`. The deterministic in-memory
v2 manifest SHA256 is
`1e4f0e9b9137b625f7e7b6c4046ba43cc34fae0c5b76c821a12ce48f49b511f3`
(167402 canonical JSON bytes).

Quality-gate totals:

- 411 primary price anchors and 265 Review-only product-card candidates;
- 64/80 pages contain at least one v2 card;
- 19 cards use single-price filled PDF regions; the remainder stay
  conservative fallback geometry;
- zero shared-title ownership after filtering;
- zero remaining card pairs with IoU >= 0.15;
- zero matches for the audited promo/legal/attribute-copy patterns;
- pages 74, 76 and 77 contain zero cards because their candidate context is
  explicitly online-only;
- page 42 intentionally remains fail-closed: both observed price anchors select
  the same Gräf's Adventskalender title block, so the source does not prove
  which price owns that title;
- page 61 now resolves to three product-like physical-store titles
  (Lippenpflegestift, Duschgel and Nivea Dusche) after discount-copy is removed;
- representative page 1 still contains the four expected Review cards
  (Hähnchen, Rheinfels, Rotkäppchen and Meggle).

This gate is **PASS for Review-card product-selection quality**, not product
identity. Automatic Hermes offer links, verified product identities and proven
product boundaries remain zero. Candidate absence is preferred over guessing
when source geometry remains ambiguous.

## Publication-bound v2 projection / UI source lane

The clean product-card evidence is projected onto the already proven 80/80
Publitas page order without weakening the trust boundary. The existing
`tools/netto_pdf_review_projection.py` remains backward-compatible with the
accepted v1 price-group format and additionally accepts
`hermes.netto.pdf_product_card_review_markers.v2`.

For v2 it requires:

- the same exact PDF, publication, image-manifest and alignment identities;
- `marker_basis=observed_pdf_product_card_candidate`;
- `product_boundary_proven=false` for every candidate and zero proven
  boundaries at manifest level;
- non-empty native card, price-region and image-region provenance;
- zero Hermes offer links and zero verified product identities.

The exact retained PDF plus the existing alignment/image receipts were
reprocessed entirely in memory. No retained Review file was written by this
source lane. Deterministic pretty-JSON receipts are:

- v2 marker SHA256
  `4a3a1e21e506d87f6b57f59d9d11f3fc925f82d864d94265044877be4a80e008`
  (252137 bytes, 265 candidates);
- v2 publication projection SHA256
  `2dcfc6c1e2e3bd8f32f37ff6cc014d9f9f1308a73c430c9df35f369cd005be83`
  (273650 bytes, 80 pages / 265 candidates).

The runtime Review layer is source-pinned to those v2 receipts and rejects the
old v1 projection once this source is deployed. Each projected candidate keeps
the full Review-only product-card rectangle, so the existing overlay button
covers the card region rather than the old price-group rectangle. The Jinja
dialog now labels these as `PDF · PRODUKTA KARTĪTES REVIEW` and still states
that card boundary, product identity, printed price and Hermes Deals
relationship are unverified.

This source change does **not** materialize those retained JSON receipts and
does not activate them in production. Until a separate LIVE rollout places the
exact SHA-pinned files and deploys the reviewed source, the currently deployed
v1 layer remains unchanged.

## Next gate

After source review/merge, the next #1069 gate is a bounded LIVE rollout:
materialize the exact v2 marker/projection receipts from the already verified
inputs, verify their SHA256 values, place only the projection at the approved
`netto-html/review-layers` runtime location, deploy the exact merged source,
then perform read-only page-count/hotspot-count and representative desktop/mobile
visual click canaries. No product -> Hermes offer bridge is part of that gate.
