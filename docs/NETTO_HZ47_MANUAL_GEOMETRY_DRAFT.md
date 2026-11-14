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
- 262 **tentative** normalized `left/top/width/height` proposals on 49 pages.
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

## Next acceptance checks (not done)

1. Inspect all 72 original full-resolution pages and every proposed region,
   correcting misplaced boundaries and omissions. Record per-page
   `reviewed` counts, excluded scope and unresolved ambiguities without
   guessing. Check Tuesday/Wednesday/Thursday/Friday start-date conditions.
2. Verify the **actual running** HZ47 selected-store-5659 booklet page count,
   immutable page image receipts and exact per-page visual alignment. The
   owner's statement that the booklet is auto-installed is not byte-level
   proof of these boundaries.
3. Produce a new complete, immutable, separately hash-pinned
   `REVIEW_ONLY` projection and source tests. No SKU links or verified
   product prices without independent authority.
4. Merge only after exact-head PR/CI/reviews. A separate owner LIVE
   authorization must precede RPi5 retained-Review placement, activation
   or runtime visual-click canaries.

**This draft must never be installed as the clickable runtime overlay.**
