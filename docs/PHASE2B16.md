# Phase 2B16 — Lidl strict persistence shadow gate

Phase 2B15 reduced the 69 full-grocery OCR candidates to 18 precision-ready, 25 review, and 26 obvious noise rows. The real sample still showed that the broad `precision_ready` bucket was too optimistic for persistence: nearby unit-price math could disagree, alcohol pages could expose volume/unit-price numbers as sale prices, generic labels could repeat with several prices, and a mathematically verified price could still be paired to a packaging descriptor such as `Abtropfgewicht`.

Phase 2B16 adds a second, deliberately conservative **shadow persistence gate**. It reuses the existing Phase 2B14 dry-run report; no new OCR, retailer fetch, or database write is performed.

The strict gate:

- keeps clean `math_verified` product labels as the strongest persistence candidates;
- routes math corrections and unresolved conflicts to review;
- routes semantic candidates to review when nearby unit-price math disagrees;
- keeps sub-euro semantic-only values review-only because they are frequently package volume/measurement artifacts;
- keeps alcohol semantic-only rows review-only until stronger product/price evidence exists;
- rejects explicit non-food cues that leaked into grocery pages through generic metadata such as `Wasser`;
- routes packaging descriptors such as `Abtropfgewicht` to name review even when the price math is valid;
- downgrades the same OCR label appearing with several prices on one page;
- requires dual-PSM + high semantic score + strong metadata product evidence for a semantic-only row to become strict-ready;
- preserves `db_write_eligible=false` for every row.

The goal is not recall. The goal is to identify a small, defensible subset that can be mapped into the `OfferCandidate` contract in the next dry-run phase without yet persisting Lidl offers.
