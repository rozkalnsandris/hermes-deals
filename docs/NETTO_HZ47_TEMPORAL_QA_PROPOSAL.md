# Netto HZ47: temporal source-only QA proposal

- Source PDF SHA256: `c8551dd197ac3050e11a9419a73b174803e5b8684890404b10b77520d3e7436a`.
- PR #1182 source HEAD when evidence was generated: `c0e61edd2ee417ad98c9f742582536febcb2381a`.
- 72 pages; 261 unverified card candidates. Page headings are *context*, not independently verified offer validity.
- 199 candidates on date-range pages; 2 on single-day Tuesday/Wednesday pages; 56 permanent assortment; 3 November catalog; 1 checkout-only.
- For candidates on pages 48–53, Thursday 19 Nov is the printed page start; pages 60 and 62 print Friday 20 Nov. Exact product-level terms have **not** been validated.
- Do not convert permanent catalog, November catalog, checkout area, app-only or PAYBACK terms into normal weekly price offers.
- All `must_not_claim_active_offer=true`; all source identities, prices and product boundaries remain unverified; `deployment_allowed=false`.
- The 72/72 page visual alignment from previous immutable publisher scan corroborates page order but does not verify each clickable region, price ownership or candidate-specific validity.
- This is an offline source proposal only. Do not install in Hermes Deals. GitHub merge and RPi5 LIVE activation are separately gated.

## Source-only geometry pin reconciliation (2026-11-15)

- The **original** temporal QA receipt remains immutable: `summary.source_commit_checked=c0e61edd2ee417ad98c9f742582536febcb2381a`, `summary.source_data_blob=d11174e3f4f98a1072954fc64ed29f1db84815e8`. Those values describe the historical evidence generation, not the currently checked-out geometry.
- At PR #1182 HEAD `41f870d0df87651280908ec5251c67b2b6b1575f`, the geometry blob became `8dd3d26675a6e22ba407865c417cf99903627358`. An exact pre/post source comparison established **only four rectangle edits** (`hz47-p21-c06`, `hz47-p21-c08`, `hz47-p49-c02`, `hz47-p49-c06`). All 72 page records and 261 candidate identities, unverified labels, page hashes and flags were unchanged.
- The temporal test now checks the **current** geometry Git blob separately from the **historical** source-data pin. It continues to enforce all page-image/candidate labels, fail-closed offer state and provisional date-only context. The temporal evidence JSON itself is **not edited** during reconciliation.
- This remains offline `REVIEW_ONLY` evidence, **not** verified product prices, candidate validity, mappings or production activation. Merge/LIVE remain separately gated.
