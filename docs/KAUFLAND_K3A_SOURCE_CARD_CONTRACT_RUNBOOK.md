# Kaufland K3A source-card evidence contract runbook

Refs: #699, #701, #702, #747.

## Purpose

This runbook defines the **source-card evidence gate that must pass before the Kaufland K3 parser is implemented**.

K3A is not a parser and does not decide Kaufland DOM semantics. It defines a deterministic, fail-closed receipt that can later prove that one exact retained HTML card owns the exact evidence used for:

- campaign/family binding;
- public promotional price (`promo`);
- regular/reference price (`reference`);
- Kaufland Card XTRA conditional price (`xtra`).

The contract implementation is `backend/app/kaufland_source_card_contract.py` with version:

`kaufland-k3-source-card-v1`

Synthetic fixtures prove only the mechanics of this contract. They do **not** prove that real Kaufland HTML has a particular selector, price label, hierarchy, article identifier or card ownership rule.

## Accepted upstream K2 boundary

K3A starts from the accepted immutable K2 evidence established by #701:

| Field | Accepted value |
| --- | --- |
| Store | Kaufland Dortmund-Aplerbeck / `1503` |
| K2 bundle identity | `afdd992c547165259e760e05f41687793c56abc0af9869c8aa70f39d6f41dbbf` |
| Frozen retained Git revision | `c451fb9027e87b62685557ad3c2c66701e912d57` |
| K2 parser-input contract | `kaufland-k2-v1` |
| Family count | `4` |
| Artifact count | `6` |
| Family-manifest SHA-256 | `1e3dbe576df47bdd9f762915986247fac66de20c3fa2cc5d61891c22e5975184` |

Accepted K2 family identities:

1. `current_main` — `2026-08-13..2026-08-19` — `DE_de_KDZ1_1503_D33` — `a9baae4b5f702f59cbc3d9eba98eb12bdd31d91aaac5e49e2ac83ecb7fbb1db1`
2. `current_short` — `2026-08-17..2026-08-19` — `DE_de_KDZ2_1503_D34-MoMi` — `f8da4ff71615141aaf97ade1b91c3b63259a41b2436e09f65c5b4e4db6898e69`
3. `preview_main` — `2026-08-20..2026-08-26` — `DE_de_KDZ1_1503_D34` — `20f1b8f998e361399b9e1fec74f700712e1a62d7048fb92e40b5e9bbe8241c9a`
4. `preview_overlap` — `2026-08-20..2026-09-02` — `DE_de_leaflet2_1503_D34-EL-Schule` — `ab338f5fd1aca216380a1cbd0a0a7fea6f86a70a9bf656b1ed99d29dbcc4a6e3`

The accepted K2 replay is `APPLY / NO_OP` with unchanged retained evidence. K3A must not reinterpret the K2 bundle or silently substitute a different retained revision, store or parser-input contract.

## Current FAST batch boundary

The #747 FAST source batch is deliberately below the retained/runtime boundary:

- no retained-root read;
- no raw retailer-material read or write;
- no live Kaufland network request;
- no K2 replay;
- no parser implementation;
- no DB/Review/publication write;
- no production deploy;
- no scheduler/systemd/host mutation.

The current PR can therefore prove the receipt schema, canonical identity, deterministic behavior and fail-closed rules, but it **cannot** claim `K3A REAL_K2_EVIDENCE_PASS`.

## Receipt identity

A valid receipt binds all of the following into one canonical SHA-256 identity:

### Upstream identity

- exact K2 bundle identity;
- frozen K2 Git revision;
- exact upstream parser-input contract `kaufland-k2-v1`;
- exact store `1503`.

### Campaign/family identity

- one accepted K2 family relation;
- exact family source identifier;
- exact family identity SHA-256;
- a bounded card-local family-binding locator;
- SHA-256 of the exact bounded family-binding evidence fragment;
- the exact owning card locator + card-fragment SHA-256;
- family-binding owner match count exactly `1`;
- binding method exactly `explicit_card_local_source_evidence`.

Page-level proximity, publication timing or “looks like this week” is insufficient. If the card cannot be tied to a K2 family from defensible card-local evidence, the receipt must not be created.

### Source artifact identity

K3A structured-card receipts are allowed only from the retained K2 `offer-overview` HTML artifact:

- artifact role exactly `offer-overview`;
- exact artifact SHA-256;
- exact byte count;
- retained content type beginning with `text/html`.

The store page and retained leaflet bytes remain provenance/evidence inputs, not substitutes for the structured offer-card HTML source.

### Card ownership

Each receipt binds:

- one sanitized deterministic `card_locator`;
- SHA-256 of the exact bounded card fragment used for evidence;
- `card_owner_match_count == 1`.

Zero owners or multiple owners fail closed. A later derivation procedure must prove that the locator resolves uniquely in the exact bound retained artifact; writing a locator string into the receipt is not itself proof.

### Price-role evidence

Every observation carries:

- role: exactly one of `promo`, `reference`, `xtra`;
- canonical positive cent-precision Decimal amount;
- role locator;
- value locator;
- role-evidence fragment SHA-256;
- value-evidence fragment SHA-256;
- the exact owning card locator + card-fragment SHA;
- owner match count exactly `1`;
- assignment basis exactly `explicit_source_role_evidence`.

The contract sorts observations by role before hashing, so construction order does not change receipt identity.

## Fail-closed rules

The contract rejects at least these classes:

| Reason code | Meaning |
| --- | --- |
| `STORE_BINDING_MISMATCH` | receipt is not exact store `1503` |
| `UPSTREAM_CONTRACT_MISMATCH` | not bound to `kaufland-k2-v1` |
| `UNSUPPORTED_FAMILY_RELATION` | family is outside the accepted four-family K2 baseline |
| `FAMILY_BINDING_NOT_EXPLICIT` | family/campaign was inferred rather than proven card-locally |
| `WRONG_SOURCE_ARTIFACT_ROLE` | structured evidence came from something other than `offer-overview` |
| `WRONG_SOURCE_CONTENT_TYPE` | artifact is not retained HTML |
| `AMBIGUOUS_CARD_OWNERSHIP` | card anchor resolves to zero/multiple cards |
| `AMBIGUOUS_FAMILY_OWNERSHIP` | family-binding evidence has zero/multiple card owners |
| `FAMILY_EVIDENCE_OUTSIDE_CARD` | family-binding evidence owner differs from receipt card |
| `AMBIGUOUS_PRICE_OWNERSHIP` | price evidence has zero/multiple card owners |
| `PRICE_EVIDENCE_OUTSIDE_CARD` | price evidence owner differs from receipt card |
| `DUPLICATE_PRICE_ROLE` | one card has multiple observations claiming the same role |
| `PRICE_EVIDENCE_CROSS_BOUND` | one evidence locator/fragment is reused across different roles |
| `PRICE_ROLE_NOT_EXPLICIT` | role came from numeric ordering or another inference |
| `INVALID_PRICE_AMOUNT` | amount is float-like, non-canonical, non-positive, non-finite or sub-cent |
| `RECEIPT_IDENTITY_MISMATCH` | receipt payload was modified after canonical identity creation |

Important semantic consequences:

- XTRA evidence can never satisfy the public `promo` role.
- A larger number is never automatically a `reference` price.
- Same numeric value in two roles is allowed only when **different explicit source evidence** proves each role.
- Nearby sibling/ancestor text cannot be imported from outside the proved card owner.
- Duplicate or overlapping anchors do not silently collapse.
- `articleID`/`kloffer-articleID` may be recorded later as evidence, but K3A does not promote it to global or timeless identity. #704 remains the identity gate.

## Synthetic mechanics gate

Focused tests may use invented locators and invented fragment hashes to establish:

1. semantically identical input with different construction ordering has the same canonical receipt identity;
2. changing immutable bundle/artifact/family/card/role evidence changes identity;
3. ambiguous card ownership fails closed;
4. role evidence cannot cross-bind between `promo`, `reference` and `xtra`;
5. numeric inference cannot create a `reference` role;
6. receipt tampering is detected;
7. no float money semantics are accepted.

Passing those tests means only:

`K3A_CONTRACT_MECHANICS_PASS`

It does **not** mean:

`K3A_REAL_K2_EVIDENCE_PASS`

and does not unblock `backend/app/parsers/kaufland.py`.

## Future offline real-K2 derivation gate — NOT AUTHORIZED BY #747

Interaction with the owner retained evidence is a separate STRICT/read boundary and needs a fresh explicit owner authorization. When authorized later, derive a sanitized receipt without network access and without retained/raw mutation.

Required sequence:

1. Fresh-check GitHub rules, exact reviewed K3A contract revision and #701/#702/#747 state.
2. Bind one read-only owner retained root outside the repository and the exact accepted K2 bundle key/identity.
3. Reuse the existing retained-bundle verifier to prove the manifest, artifact counts and all retained artifact hashes/byte counts before looking at card semantics.
4. Read only the exact retained `offer-overview` artifact. Do not refetch Kaufland and do not rewrite the retained tree.
5. Independently resolve bounded card candidates from the exact bytes. Record a deterministic locator and exact bounded card-fragment SHA-256.
6. Require the proposed card locator to match exactly one card. Zero/multiple matches are evidence failure.
7. For a proposed family binding, record the exact card-local locator and fragment hash that proves the family/validity relationship. Do not infer campaign ownership from a page-level date or nearest section unless that ownership rule is independently proven.
8. For each claimed price role, record the exact card-local role locator, value locator and bounded fragment hashes. Prove that each locator belongs to the same unique card.
9. Require explicit source evidence for each role. Never classify `reference` because a number is larger and never classify `xtra` merely because a lower price is nearby.
10. Build the receipt twice from the same observations in deliberately different construction order and require byte-identical canonical JSON semantics / identical `receipt_identity_sha256`.
11. Emit only the sanitized receipt/receipt hashes needed for review. Do not upload uncontrolled raw retailer HTML.
12. Preserve ambiguity as a deterministic failure receipt; do not tune the contract to force coverage.
13. STOP. No parser implementation is authorized by the derivation run itself.

If any read/derivation execution begins and an error or ambiguity appears, preserve the evidence and STOP. Do not retry, clean up, switch to live network discovery or take an alternate mutation path without new authorization.

## Minimum real evidence required before #702 parser work

`K3A_REAL_K2_EVIDENCE_PASS` requires reviewed receipts/observations from the accepted K2 HTML proving, at minimum:

- one source card with defensible public `promo` role;
- one defensible explicit `reference` role when present in the retained source;
- one defensible explicit XTRA role;
- public promo and XTRA remain distinct on dual-price evidence;
- exact same-card ownership for every accepted role;
- exact family/campaign ownership rather than page-level guessing;
- at least one deliberately ambiguous/duplicate ownership case demonstrating fail-closed behavior;
- reproducible second derivation of the same sanitized receipts with identical identities.

If the accepted K2 HTML does not contain enough evidence for one of these items, record the exact missing-evidence result and keep #702 blocked. Do not invent a selector or infer a role to satisfy the checklist.

## #702 gate

Until the real offline K2 derivation gate above passes:

- do **not** create `backend/app/parsers/kaufland.py`;
- do **not** claim Kaufland promo/reference/XTRA parsing semantics are accepted;
- do **not** claim card ownership is solved;
- do **not** use synthetic K3A fixtures as retailer truth.

After `K3A_REAL_K2_EVIDENCE_PASS`, #702 may start as a separate source-level parser batch using only the proven source-card semantics.

## Production classification

Production DB write: **NO**  
Review/publication write: **NO**  
Retained/raw mutation: **NO**  
Network: **NO** for K3A offline derivation  
Production deploy: **NO**
