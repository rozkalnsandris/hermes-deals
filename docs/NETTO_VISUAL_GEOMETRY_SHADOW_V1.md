# Netto visual geometry shadow v1

Issue: #95

## Purpose

This is a shadow-only, vector-first ownership prototype for the confirmed Netto visual card-boundary and price-selection defects.

It does **not** replace the production HTML parser, activate a collector path, write Review/DB state, approve offers, publish offers, or deploy production.

## Evidence and scope

The authoritative N10 ledger remains the regression contract for the nine `card_binding_or_primary_price_correction_required` cells across:

- `hz31_hasb_4`: pages 14 and 18;
- `hz32_hasb`: pages 1, 37 and 38.

The parser contains no product, cell, campaign or page-specific correction override.

RPi5 N13 capability evidence established that all five affected pages are suitable for a vector-first PyMuPDF geometry path. The later N14 V05 real replay found all nine expected prices while preserving zero unsafe cross-bindings; ownership refinement remains shadow-only.

## Algorithm

1. Extract text spans and vector drawing primitives with PyMuPDF.
2. Keep sufficiently long horizontal/vertical separators and card-sized rectangles as ownership barriers.
3. Reconstruct full decimal prices and Netto split-price typography. A large major span such as `6.` plus an adjacent smaller `99` cents span becomes one `6.99` price anchor.
4. A sufficiently large unmatched major span such as `1.` can represent a whole-euro `1.00` offer price. Small unmatched numeric fragments are not promoted.
5. Compute typography thresholds from ordinary non-price text rather than price glyphs. This prevents large price text from raising the parser's own detection threshold.
6. Remove all reconstructed price-component spans from title candidates.
7. Type member, regular and unit-price evidence separately from nearby explicit labels. A member price never replaces a missing normal price.
8. Cluster nearby price anchors only when no separator lies between them.
9. Assign non-price text to the nearest price group only when the best assignment is separated from the runner-up by a deterministic margin.
10. Exclude promotional/footer labels from title candidates.
11. A group is an automatic **shadow** candidate only when it has one normal price, a title candidate and no nearby ambiguous text ownership.
12. Every ambiguous group fails closed to Review.

## Safety boundary

The module always returns:

- `shadow_only=true`;
- `production_eligible=false`;
- `promotion_ready=false`.

No automatic approval, publication, DB write, collector activation or production deployment is authorized by this implementation.

## Validation strategy

Focused tests cover:

- exact authoritative N10 nine-case card/price repair count and page set;
- separator blocking of neighboring-card cross-binding;
- deterministic normal/member price separation;
- multiple-normal-price fail-closed behavior;
- promotional-title rejection;
- split major+cents reconstruction;
- whole-euro reconstruction;
- removal of price components from title candidates;
- deterministic output;
- fixed shadow-only safety flags.

Before any production integration, the implementation still requires the full 100-cell shadow replay and an independent second review required by issue #95.
