# Netto HZ47 — automatic click-to-magnify, not card recognition (#1185)

**Owner direction change (2026-11-15):** The previous label+headline-price
matching approach is too expensive to review on every weekly booklet.
The user wants **zero weekly per-product annotation or mapping**. Therefore
the five-page pilot now magnifies the clicked **original source image location**
regardless of whether it is a product name, price, or adjacent visual area.
The same text and price can both be enlarged, but neither is paired with an
invented product identity. This deliberately **does not** create a product
detail panel; it is an honestly labeled, enlarged source fragment.

No OCR, PDF text extraction, card rectangles, product name detection,
product/price associations or manual mapping are required for the magnifier.
Clicking blank background also enlarges that location, not a product.
This is an intentional UX tradeoff, rather than an attempt to find all text
areas. It preserves the original page artwork.

## Scope and source identity

- Original user-supplied PDF hz47_hasb.pdf: **72 pages**, **39,976,532**
  bytes, SHA256
  c8551dd197ac3050e11a9419a73b174803e5b8684890404b10b77520d3e7436a.
- Five-page pilot: **1, 21, 34, 49, 57**.
- Tool: tools/netto_hz47_click_to_magnify_pilot.py.
- Optional pure-PDF offline diagnostic; not integrated with FastAPI,
  HTMX, existing booklet viewer, collector, source retention, DB, scheduler,
  deployment, or HZ46.
- The image is a deterministic render of the same user-provided PDF; it is
  **not proven identical to the live first-party Publitas image**. Publisher
  page/store identity gates remain unchanged for future integration.

Example source-only local invocation, only with exact PDF bytes already
present and authorized on the execution surface:

    python tools/netto_hz47_click_to_magnify_pilot.py /path/to/hz47_hasb.pdf --output-dir /tmp/hz47-magnify-new

Tool verifies immutable PDF SHA, 72 pages, unrotated expected geometry,
and a nonexistent output directory. It writes five deterministic 2× PNG
page renders, five offline HTML previews and a review_only.json manifest,
all local to the new scratch directory. Each image digest and ordinal are
recorded. Source hash mismatch fails before output creation.

The offline HTML click surface covers the complete **original page image**,
not a guessed card. Mouse or touch at any position opens an enlarged
fragment centered on that position, clamped to the page boundary, using
the exact same local original page pixels. Keyboard Enter opens the
page center; Escape/close works, focus returns to the page. Movement beyond
10 pixels and multi-pointer gestures are meant to suppress opening, so
swiping/panning cannot become a product action. No browser OCR, network fetch,
canvas CORS dependency, product price state, SKU, basket action, offer identity
or database writes.

## Local real-PDF and browser evidence

- Exact uploaded PDF hash and page count verified locally.
- Real 2× PDF page images successfully rendered for all five requested pages.
- In a local isolated Chromium/Playwright test (1440×900 desktop and
  412×892 phone viewport), all **10/10 page×viewport combinations** opened
  and closed an enlarged image from a click; keyboard Enter and Escape
  also passed. Testing used in-memory image data (not file:// navigation).
  One failed initial file:// browser navigation was attributable to the
  browser administrator denying local file navigation; no source change
  or production mutation occurred.
- This is a **smoke test**, not completed two-finger pinch/swipe/zoom or
  existing live booklet keyboard/fullscreen acceptance.
- New synthetic GitHub tests prove fixed page scope, HTML image safety,
  no product association, and PDF mismatch handling. Exact-head CI is
  required after this branch is changed.

## Acceptance and rollout boundaries

1. Compare offline original page image dimensions and visual placement
   against the exact selected-store Publitas source for pages 1, 21, 34,
   49, 57. Current PDF and publisher are not byte-proven equivalent.
2. Check actual mobile swipe/pan/pinch/double-tap and fullscreen behavior
   against the **existing** viewer; avoid hijacking confirmed publisher
   hotspot interactions and never make an image click claim that an offer
   was verified. Test desktop keyboard focus and back/forward/page selection.
3. If accepted, port the **smallest presentational magnifier** to the
   image of the already source-verified viewer. Prefer existing Jinja +
   minimal Vanilla JS/CSS and the existing high-res image URL. No weekly
   PDF or OCR processing is required merely to magnify already-present
   verified publisher image pixels.
4. Separately decide whether this image-only magnifier is sufficient, or
   whether a **verified publisher hotspot / offer match** is needed for
   actual product details. Never activate or claim verified offers/price
   comparison from magnification alone.
5. Owner decides full **72-page** implementation after successful UI
   acceptance. The five-page pilot is not a 72-page coverage assertion.

**All draft output is REVIEW_ONLY**. This does not alter or close issue
#1181, Draft PR #1182, or their unverified 261 candidate rectangles.
Old manual label/price pairing code is intentionally retired from Draft
PR #1186; this pilot never requires manual weekly annotations.

No merge or LIVE/production/DB/collector/deploy mutation is authorized
by this source-only work.
