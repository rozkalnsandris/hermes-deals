# Phase 2B5R — Lidl page-schema deep scan

The v0.2.7 PDF experiment proved that Lidl's current public v4 flyer JSON may advertise a `pdfUrl` whose backing object returns HTTP 404. PDF availability is therefore diagnostic information, not a hard dependency.

This phase returns to the stable v0.2.6 baseline and deep-scans the already proven public flyer JSON:

- loads the saved current flyer payload;
- inventories all page-level and nested fields across the full flyer;
- measures `keyWords`, `altText`, grocery coverage and price-like tokens;
- checks structured `productDetails` coverage;
- probes PDF and first-page image assets without downloading the full flyer;
- treats PDF 404 as non-fatal;
- does not use Playwright, OCR, or write Lidl offers to the database.

The output determines whether the next collector can rely on hidden/nested JSON price fields or needs image-based price extraction for grocery pages.
