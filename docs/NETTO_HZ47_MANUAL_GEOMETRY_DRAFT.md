# Netto HZ47: user-supplied PDF manual geometry — DRAFT (#1181)

**Source**: user-provided `hz47_hasb.pdf`, SHA256
`c8551dd197ac3050e11a9419a73b174803e5b8684890404b10b77520d3e7436a`,
72 pages (16–21 November 2026, with some later-starting page offers).
The PDF is **not** a verified official publisher snapshot or verified
store-5659 publication. The original 39,976,532-byte PDF and rendered JPEG
bytes are **not in GitHub**.

**Source-only artifact**: `evidence/netto/hz47_manual_pdf_geometry_draft_v1.json`

- 72 contiguous PDF page records, each bound to the SHA256 of its
  user-uploaded-PDF derived page JPEG (1352×1893).
- 261 **tentative** normalized `left/top/width/height` proposals on 49 pages.
  23 pages have zero proposals with **unconfirmed scope exclusion** notes.
- Proposals were manually interpreted from page contact sheets and
  page previews. **No page has passed exhaustive full-resolution, per-card
  boundary/price-ownership visual adjudication**.
- The labels are source-observed hypotheses, *not* verified product identity.
  Printed price, promotion validity, app/PAYBACK eligibility and grouping
  are not verified by this artifact. There are zero Hermes offer links.
- This is **not** the existing HZ46 PDF Review projection format, nor a
  replacement for original publisher hotspots. No server reader, UI, runtime
  corpus, DB, collector, scheduler or publication configuration was changed.
- The approved source boundary in `AGENTS.md` and `docs/BOOKLETS_UI.md`
  is preserved: a PDF-local box must not be rendered on a different Publitas
  page until exact immutable publication/image identity, 72-page order and
  source/store/validity mapping are independently verified.

## Source-only pixel correction checkpoint (2026-11-14)

- Visually inspected full-resolution PDF renderings for pages **1, 13, 28, 30, 31, 35, 56, 57, 60 and 62**. Removed page-1 Adventskranz: decorative, outside food/drinks/household-consumables scope.
- Corrected **41 provisional rectangles across nine pages** to keep visible labels, packages and price tags with their own card rather than adjacent cards. Notably: p28 tea-card price ownership; p31 distinct Faber/Weingold and four spirits; p57 right-hand Felix Soup versus two left-hand reis-fit variants; p60/p62 Friday-start hero image plus caption; and p56 two-row grid.
- New count **261** tentative candidates across 49 pages. This is a bounded spot-check, **not** 72/72 exhaustive card acceptance. All per-page `full_resolution_pixel_review_completed=false`, prices remain unverified, and the overlay is still non-promotable.
- Focused source-only local validation: 19 passed. Exact-head GitHub CI, installation identity, retailer-store proof, every remaining card/scope review and a separate future LIVE gate remain outstanding.

## PDF-to-Publitas independent six-page spot check (2026-11-14)

- Public official Publitas JSON at `https://api.publitas.com/v1/groups/regionale-hz/publications/hz47_hasb.json` declares exactly 72 ordered spreads; official `at1600` size 1352×1893. Existing RPi5 read-only evidence separately confirmed selected-store `5659`, validity **16–21 November**, 72 unique page IDs and exact local publication metadata SHA256 `689b6d833f806664bcc59780ebc666780751e4cb388aa65933a98cbd468563b2`.
- Visually compared **PDF page and official publisher image** for pages **1, 5, 34, 36, 57, 72** via the live first-party `view.publitas.com` images; appearance and page content match for these six cases. Examples of corresponding page IDs: p1 `54c86da9-44b7-4144-ae82-99199a3ece81`, p36 `5ef0c5f5-0858-4648-9b3a-f0807493dd64`, p72 `0d2348f4-5cee-4bb6-837b-3a66f25e18d7`.
- **This is a six-page visual spot check, not 72/72 byte/pixel alignment proof.** The user PDF is still not independently shown to equal the publisher PDF; do not set `publication_identity_proven`, `publisher_page_alignment_proven`, or `store_5659_binding_proven` in the user-PDF draft. Do not activate on the 72 publication images.
- Bounded local PDF text/geometry QA on all **261** draft candidates: **257** contain a PDF-native decimal-price-like token inside their original rectangle; **4** needed investigation. Full-resolution p5 visual inspection exposed the tomato price `1.49*` just outside the old rectangle. Expanded p5 Tomaten from `top=0.06,height=0.39` to `top=0.06,height=0.43`; PDF text then includes the observed current/UVP price region. **258/261** now have at least one decimal-price-like token inside the box, with remaining exceptions p34 (Käse-Laugen Breze, Roggenmischbrot: price labels extend beyond candidate rectangles) and p42 (OSRAM batteries printed `1.–`, a format intentionally unmatched by the decimal-price heuristic).
- Five small rectangle intersections remain on p2/p3 (max tentative IoU ~0.021); these and all print-price ownership still require review. A price-like token is **not** a verified offer price (may be UVP, APP, PAYBACK, saving, or unrelated nearby text). This audit does **not** increase product boundary proof counts, verified offer identity or page-level completion.

## HZ47 source-only eleven-coordinate QA correction (2026-11-14)

- Exact original user PDF SHA256 `c8551dd197ac3050e11a9419a73b174803e5b8684890404b10b77520d3e7436a`; prior authorized Lenovo read-only scan compared all 72 rendered PDF pages against the 72 first-party `at600` publisher images. Bidirectional **72/72 ordinal-best matching**, no ambiguous margins; grayscale 48×68 MAE median **4.559**, max **7.123**. This proves robust page-level visual correspondence but **not identical source bytes** or each candidate's geometry.
- Earlier 11 proposed geometry corrections were validated against full-resolution source-page imagery, PDF-native text, and all 261 rectangles. A faulty local QA script expected 13 changes when the last two refinements targeted **existing** candidates `hz47-p03-c01` and `hz47-p30-c04`; corrected assertion expects **11 unique IDs**. Final p3 Lindt ends before orange/apple products (`top=0.035,height=0.515`); p30 Hell Energy Drink ends before Coca-Cola (`top=0.50,height=0.22`).
- Other 9 corrections cover pages 2, 5 and 34, including separated Weihenstephan, Tomaten/Zespri Kiwi, and Backstube product columns. **261 proposals across 49 pages** remain; **0 intersecting candidate rectangles** in the local draft after corrections.
- PDF text heuristic finds price-shaped text in **260/261** rectangles; p4 Kanzi Apfel text has a split `2 49*` token, not a verified price. This is **not** price ownership validation. All 72 pages remain `full_resolution_pixel_review_completed=false`; review/offer/identity/promotability flags remain fail-closed. No RPi5 publication/DB/collector/deploy writes.

## Six HZ47 price-label region corrections (2026-11-14)

- Local QA proposal `netto_hz47_candidate_rectangles_proposed_v4_REVIEW_ONLY.json`, SHA256 `5f385f38978504ea0d49d380c0aa4d25ba60dfdcc451d3dc2b144091847f03fb`; source Git blob `436f737f0876a7e1aacbc80e706e87e3455b7554`. Compared **exactly six** amended rectangles against the current PR evidence, with no other candidate/page/metadata changes.
- Pages **9** (`hz47-p09-c03`, `c04`), **11** (`hz47-p11-c02`, `c03`) and **21** (`hz47-p21-c05`, `c07`): updated positions separate adjacent meat, deli and beverage products and include visible headline price regions where identified. Example visible text `2.49`, `2.89`, `1.29`, `7.49`, `14.99` remains **unverified printed-price evidence**, not an offer-price or SKU assignment; APP prices/deposit/multiple products may share cards.
- **72 pages, 261 candidates, 49 candidate-bearing pages, zero intersecting rectangles** in source draft. Each candidate and page remains `REVIEW_ONLY` / `DRAFT_NEEDS_FULL_RESOLUTION_PIXEL_REVIEW` / `full_resolution_pixel_review_completed=false`. Publisher source URL, PDF source identity and offer links are not promoted or inferred.
- Diff is limited to source JSON, focused guard tests and this handoff; **no UI, API, DB, collector, schedule, deploy or runtime changes**. Completion still requires full-resolution card-by-card acceptance and separately authorized LIVE gates.

## HZ47 twenty-title visual QA (v5) — 2026-11-15

- Reviewed **20** draft cards flagged by PDF title-text heuristics against the user-uploaded PDF's visual content. These are **source label/region plausibility checks only**, not full-card pixel approval or confirmed retailer product/price identities. QA report `netto_hz47_20_titles_visual_QA_v5_READ_ONLY.json`, SHA256 `196a869e7065a03cb590148b25b06f27de6a7688370f050ee2d411d3d3b19716` (local, not committed).
- Precisely **four** proposed rectangle changes against baseline geometry blob `d11174e3f4f98a1072954fc64ed29f1db84815e8` and prior PR HEAD `967876f44839be530c28fea285b86e2ddd92f032`: p21 `hz47-p21-c06` and `c08` include Freixenet headings; p49 `hz47-p49-c02` includes `13.99*` text while neighboring salmon `c06` begins below it.
- Read-only PDF word evidence: p21 Freixenet at normalized y≈0.5047 / 0.7454; p49 `13.99*` extends to y≈0.5391. Overlay previews were inspected at 1352×1893 for p21/p49. Proposed JSON `netto_hz47_visual_boundary_proposal_v5_REVIEW_ONLY.json`, SHA256 `9b88246d542620d082bd371ac98671ac93059496be0b159d2c312c95f0d62f42` (local, not committed).
- **72 pages, 261 candidates, zero overlapping rectangles** after source-only adjustments. Conditional APP/PAYBACK/bundle and standard prices require individual evidence. No verified identity, price, product boundary, or validity; all pages `full_resolution_pixel_review_completed=false`, `publication_ready=false`, `REVIEW_ONLY`, zero offer links. No runtime activation, collector, deploy or DB changes.

## Next acceptance checks (not done)

1. Inspect all 72 original full-resolution pages and every proposed region,
   correcting misplaced boundaries and omissions. Record per-page
   `reviewed` counts, excluded scope and unresolved ambiguities without
   guessing. Check Tuesday/Wednesday/Thursday/Friday start-date conditions.
2. Preserve the verified RPi5 selected-store-5659 72-page publication identity
   and independently matched PDF↔publisher ordinal proof; still check every
   candidate against the publisher image at full resolution before display.
   Visual matching is not PDF-byte or offer/product-boundary identity.
3. Produce a new complete, immutable, separately hash-pinned
   `REVIEW_ONLY` projection and source tests. No SKU links or verified
   product prices without independent authority.
4. Merge only after exact-head PR/CI/reviews. A separate owner LIVE
   authorization must precede RPi5 retained-Review placement, activation
   or runtime visual-click canaries.

**This draft must never be installed as the clickable runtime overlay.**
