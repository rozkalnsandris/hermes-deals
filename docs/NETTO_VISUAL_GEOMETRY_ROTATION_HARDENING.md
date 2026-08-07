# Netto visual geometry rotation hardening

Issue: #95

## Purpose

PyMuPDF text spans and drawing coordinates are reported in the unrotated page coordinate space. `Page.rect` reflects page rotation, so its width and height can be swapped for 90° or 270° pages. Separator thresholds must therefore use unrotated page dimensions as well.

The shadow parser now uses `Page.cropbox.width` and `Page.cropbox.height` when recording geometry dimensions and keeps `Page.rotation` only as metadata. The parser identity is bumped to `netto-visual-geometry-shadow-v3-unrotated-page-space` so future exact-SHA replay evidence cannot be confused with the earlier coordinate-space behavior.

## Regression

Focused tests create real PyMuPDF pages with dimensions 200 × 400 points, rotate them to both 90° and 270°, draw a 30-point horizontal separator in unrotated coordinates, save and reopen the PDF, then require:

- reported geometry dimensions remain 200 × 400;
- rotation metadata remains 90° or 270°;
- the 30-point horizontal separator survives the 11% width threshold that belongs to the unrotated 200-point width.

Using rotated `Page.rect` dimensions would incorrectly treat the page width as 400 points and reject this separator.

## Safety

This change remains shadow-only. It does not activate a production parser, write PostgreSQL or Review state, approve or publish offers, deploy production, change collectors or schedulers, or touch B15M2 V08.

The next #95 acceptance step remains the exact 17-page / 100-cell shadow replay against the immutable N10/N12/N13 evidence chain, followed by the required independent reproducible review.
