# Netto PDF price-marker Review export (#1123)

`tools/netto_pdf_review_export.py` reuses the existing
`netto_visual_geometry_shadow` PyMuPDF span/price-group
analyzer without a competing product identity parser. Example:

```bash
python3 tools/netto_pdf_review_export.py input.pdf /tmp/netto-review.json --expected-pages 74
```

Output has source PDF SHA256, exact PDF page count, normalized observed
price-group marker rectangles, tentative PDF text, and review reasons.
These rectangles are **price-label anchors only**, never guessed
complete product-card outlines. All rows are `REVIEW_ONLY` with
no product IDs, store claims, Hermes prices, SKU links or promo state.

This source tool is offline; it does not acquire/publish source, write
the application DB, run a collector, render host UI or mutate LIVE
state. Local JSON output cannot be placed into production retained
source or served by the installed app without a separately authorized
and verified flow.

**Known blocker:** user-supplied `hz45_hasb` PDF has **74 pages**;
the installed selected-store Publitas publication has **72 pages**.
Do not transfer page numbers or geometry between those sources without
per-page image identity, publication/date/store provenance, immutable
source binding and independent product-ID eligibility evidence.

Publisher editor hotspots are not exhaustive PDF product annotations;
even PDF price anchors may be ambiguous or promotional savings, so
display only as manual Review locations. Online-only items (including
the supplied page 44) must not become physical-store coverage proof.

Web/product actions must remain guarded by existing canonical Python
business logic. Preserve frontend fullscreen/pinch/swipe/zoom.
PyMuPDF: https://pymupdf.readthedocs.io/en/latest/page.html
Publitas: https://developers.publitas.com/docs/rest-v1.html
