# Phase 2B9 — Lidl multi-PSM OCR price coverage audit

Phase 2B8 proved that the hardened TSV parser removes the worst shipping/installment/package false positives, but the real RPi5 sample still exposed two blockers before any Lidl DB write:

- only 6 credible price zones were found across 8 sample pages; grocery page 2 had no sale-price zone even though the flyer visibly contains several offers;
- every surviving zone had a geometric text pairing, but several pairings were clearly not product names (for example a URL fragment or a package-size line).

Phase 2B9 therefore does **not** persist Lidl offers and does not add more pairing heuristics yet. It first measures whether Tesseract page segmentation is the main source of missing prices.

For the same eight representative pages the OCR worker runs PSM 6, 11 and 12. Each pass uses the existing conservative price classifier. Credible zones are then merged only when the normalized price token and visual location agree. The report records per-PSM yields, ensemble gain over the existing PSM 11 baseline, multi-mode support for each price, and total OCR time.

Decision gate:

- meaningful ensemble gain -> keep Tesseract and move to product-label refinement;
- little/no gain -> stop iterating page segmentation and test image preprocessing / price-anchored region OCR instead.

No Playwright and no Lidl PostgreSQL write are enabled in this phase.
