# Lidl #906 — product-observation provenance and conflict review (source design)

## Status and explicit authority

**DESIGN ONLY, NOT AN IMPLEMENTED PARSER OR GATE.** The owner approved `INDEPENDENT-MULTI-CAMPAIGN-PROCESSING` with source design, isolated campaign identities, provenance and conflict quarantine. The same approval explicitly excludes automatic flyer selection, automatic deduplication, MERGE, LIVE, DB and publication. Source work in this document does not expand those permissions.

The merged `backend/app/lidl_parallel_campaign_isolation.py` supplies logical campaign namespaces and pairwise **source-level** conflict quarantine. This design specifies the **next, separately implementable product-observation boundary**, without invoking a parser, creating an offer or modifying the live Gate A/B code.

The owner-authorized one-shot first-party capture on 2026-11-21 for selected store `DE06664` verified two distinct 2026-11-23..28 campaign sources *in memory*. The official API advertised 43 page entries for `36518f/ar/10` and 36 for `cde58d/ar/21`. The API also advertised overlapping region codes `7` and `21`. These counts are **API page-list counts**, not independently measured PDF page counts or product counts. The source bytes were **not persisted**; only sanitized metadata and hashes were reported. The actual 2026-11 flyer product records, names, prices, page coordinates and identity relationships were **not** validated by that capture.

No first-party source evidence establishes a unique authoritative weekly-grocery program. Parent `Gate A = BLOCKED / UNRESOLVED`, not WAIT_SOURCE, remains mandatory.

## Evidence boundary: a product occurrence is not a canonical product

An implementation may eventually consume independently verified `FlyerEvidence` plus the output of `plan_parallel_campaign_isolation()`. It must use the same validated `(flyer_identifier, route_region)` identity and exact `campaign_namespace_sha256`. It may never accept a bare product name, store-region code, human campaign label or a synthetic item list as provenance.

Define two separate concepts:

1. **Source-bound occurrence:** One observed appearance in one exact flyer revision, page and source location. It represents where a product-like candidate *might* appear, not proof of retail eligibility, product identity or a correct offer.
2. **Canonical product / comparable offer:** A future separately reviewed identity decision that may connect multiple occurrences. No canonical product or cross-campaign offer is created at this stage.

Proposed minimum occurrence evidence (all fields require validation by future code, not just presence in user input):

| Field | Required evidence / invariant |
|---|---|
| `store_external_id`, `target`, `flyer_identifier`, `route_region` | Exact validated selected-store campaign lane; no store binding inferred from numeric region alone. |
| `campaign_namespace_sha256`, `source_provenance_sha256` | Must equal the recomputed logical namespace and inspected source provenance; never imported from a different campaign. |
| `official_flyer_id`, `raw_sha256`, `pdf_sha256` | Must match the same verified `FlyerEvidence` and its current source revision. |
| `page_number` | Positive integer bound to an actual numbered page in that flyer JSON; validate number uniqueness and page-list completeness before relying on coverage counts. |
| `source_carrier` | Explicit enum: `FLYER_PRODUCTS`, `PAGE_LINK_PRODUCT_DETAILS`, `PAGE_TEXT`, or `PDF_VISUAL`; no inferred default. |
| `source_locator` | JSON Pointer into the *same* exact raw bytes for structured fields, or page-bound PDF coordinates with verified dimensions/coordinate basis for visual candidates. Unverifiable locators remain REVIEW_ONLY. |
| `extractor_version`, `extractor_sha256`, `observation_evidence_sha256` | Binds an extracted claim to a particular transformation and source excerpt/crop; a synthetic fixture hash is not authentic source evidence. |
| `observed_title`, `observed_price`, `currency`, `package`, `price_basis` | Optional **claims**, never filled by guessing. Record field-level evidence pointers and parsing confidence; missing/contradictory values stay unresolved. |
| `channel`, `scope`, `validity` | Explicitly evidenced or REVIEW_REQUIRED. Physical-store food, drinks and household consumables are target scope; online-only, clothing and electronics must not be promoted. |
| `observation_state` | One of `EVIDENCE_MISSING`, `REVIEW_REQUIRED`, `SOURCE_BOUND`, `REJECTED`; `SOURCE_BOUND` is not production-approved. |

The future occurrence key should be a versioned digest over canonical campaign namespace, source revision, page number, locator kind and identity, and extractor/evidence fingerprints. This is **occurrence identity**, not global product identity. It must not reuse a key from `lidl_corpus_import.source_offer_id` or a DB `OfferCandidate`: those belong to a separately authorized corpus/import path. A revised source hash, changed geometry or changed extractor version must not silently overwrite existing provenance.

## Existing code that informs, but does not authorize, implementation

- `backend/app/lidl_api_inspector.py` explores optional `flyer.products` and `pages[].links[].productDetails`, plus page `keyWords` and `altText`. These are **schema possibilities**; they have not been verified to carry complete, correct structured product+price data for both 2026-11-23..28 flyers. Do not infer coverage from a nonempty collection or a sample.
- `backend/app/lidl_page_schema_inspector.py` finds price-like tokens and grocery-like terms in page fields. A keyword match or price token is **not** an offer/price anchor, product identity, or authoritative grocery campaign selection.
- `backend/app/lidl_corpus_import.py` already has retained-source/scan validation, row identity, per-page fields, physical-store scope checks and Review boundaries. It also has DB/SourceSnapshot/OfferCandidate write paths: **do not call or connect those from a source-only review plan**. Future adapters must preserve exact source provenance without granting this importer additional authority.
- `backend/app/lidl_parallel_campaign_isolation.py` quarantines overlapping advertised regions/date ranges, repeated official UUIDs and reused PDF hashes **at campaign level**. Such overlaps alone do not establish any shared products.

## Conflict quarantine, not deduplication

A proposed product-level reviewer would compare only individually source-bound occurrences, preserving both originals. All comparison outcomes are *advisory*:

- `POTENTIAL_CROSS_CAMPAIGN_DUPLICATE`: two independently source-bound occurrences have corroborated matching identifiers or comparable content. A matching title+price, matching unverified API `productId`, or shared PDF region cannot itself authorize product equivalence.
- `PRICE_OR_PACKAGE_CONTRADICTION`: independently evidenced claims may refer to one product but disagree on price, quantity, price basis, app/coupon conditions or validity. Both remain visible, unresolved and unmodified.
- `MISSING_OR_AMBIGUOUS_ANCHOR`: missing, duplicated, unstable or mismatched page/text/geometry pointer; quarantine that occurrence without substituting a nearby price or product.
- `UNVERIFIED_CROSS_CAMPAIGN_IDENTITY`: apparently matching rows whose source identity or field-level evidence cannot be established. Absence of a detected match must **not** mean proven distinctness.

The review record must store **two independent occurrence references** (never merge source fields), the particular evidence references, reason codes, review state and any separately authorized human decision. No winner, selected flyer, canonical product mapping, automatic deduplication, write eligibility or publication authorization can be derived from this data. If one source lane is invalid, do not promote another as its replacement. Any future human approval must be scope- and revision-bound; it cannot implicitly authorize a new capture or live import.

## Coverage must stay campaign-specific

For each independently verified campaign track at minimum:

- official flyer UUID, route, validity, exact JSON/PDF SHA-256, source namespace and source acquisition/inspection provenance;
- advertised page-list count, uniquely validated page numbers, pages examined, pages with candidate anchors, pages with confirmed source-bound occurrences, pages requiring manual review, and pages for which evidence is unavailable;
- candidate count, source-bound count, ambiguous/contradictory count, rejected count, and unresolved price/title/geometry counts, with explicitly versioned extraction rules;
- scope states (physical-store in-scope, review, excluded, unknown) **only when supported by evidence**.

Do not sum the 43 and 36 advertised pages into a single 79-page *unique* flyer, use empty `products` or `links` as proof that a page has no offers, assume all images/text were scanned, or declare complete coverage based on candidate count alone. An unexamined page stays **UNKNOWN**. Coverage/acceptance must require a reviewed denominator and separate source-lane completeness; joining campaigns must not hide missing evidence.

## Acceptance matrix for a later implementation

A future source-only implementation PR should include focused synthetic/frozen-evidence tests proving:

1. Same text/price on different campaign namespaces yields **two** occurrences and only an advisory possible-match review; no canonical product or shared `source_offer_id`.
2. Swapped slug/region, UUID, source hash, page number, locator, coordinate dimensions, extractor fingerprint or source revision is rejected/quarantined without cross-lane fallback.
3. One missing or failed page does not produce an inferred product, fabricated price or complete-coverage claim; unaffected pages keep their own status.
4. Price variants (app-only, coupon, variable-weight example), multiple prices on one page, mixed package units, and separate validity windows are not silently flattened.
5. Duplicate/ambiguous structured IDs, name-only matches, same-price-different-package, and multi-campaign duplicates produce explicit review records rather than automatic equality.
6. Source order, link order, review order, page scan order or parallel execution order cannot choose a campaign, resolve an ambiguity, or change deterministic identifiers.
7. Unsafe/off-source URLs, raw HTML/JS, forged authority flags and arbitrary external payloads cannot become accepted evidence or filesystem/network destinations.
8. The report contains no raw source bytes, secrets, signed source URLs, production offer records or authority-granting flags. `origin_attested=false`; `Gate A=BLOCKED` in every case.

Tests using synthetic items or cached metadata do **not** establish live Lidl item coverage. Tests against **real** raw JSON/PDF require independently authorized access and retained byte provenance; this design does not authorize them.

## Separate, sequenced owner gates

1. **SOURCE scope**: implement a pure per-occurrence source-bound review planner and tests only after reviewing a genuine input schema. No live parser/collector wiring; obtain explicit new source scope if it expands beyond the approved architecture.
2. **Read-only source observation**: re-acquire or independently inspect actual per-campaign item structures only with fresh exact-LIVE authorization. Previously captured bytes were discarded after the authorized in-memory run; never claim they are retained, and do not invent products/prices from summaries.
3. **Source review and MERGE**: exact-head CI, review and owner MERGE authorization for any new source PR. Merge itself is not LIVE.
4. **Applicability, retention and publication**: resolve first-party store/date/program rules or approve a separately bounded multi-campaign operation with owner authority. Gate A remains BLOCKED until a separately reviewed change and fresh LIVE authorization. Immutable corpus, Gate B, DB/Review, production publication, services/deploy each have their own owner gates.

**Current result:** no product-level parser or stored observations exist from this design. It specifies how to obtain a defensible next piece of evidence without weakening provenance, deduplication or production boundaries.
