# Kaufland K3 source-card evidence contract runbook

Refs: #699, #701, #702, #747, #749.

## Purpose

This runbook defines the source-card evidence boundary that must be satisfied before Kaufland K3 parser work can rely on retained HTML semantics.

The contract implementation is:

`backend/app/kaufland_source_card_contract.py`

Current contract version:

`kaufland-k3-source-card-v2`

Version 2 exists because the first authorized real-K2 derivation proved that the retained common `offer-overview` can expose card-local price markers while not proving a unique card-local campaign/family association. The contract therefore separates:

1. **source-card semantic evidence** — price roles and exact card ownership;
2. **campaign/family association evidence** — a separate optional layer that is either explicitly `BOUND` or explicitly `UNBOUND`.

Synthetic fixtures prove contract mechanics only. They do not prove retailer DOM semantics.

## Accepted upstream K2 boundary

| Field | Accepted value |
| --- | --- |
| Store | Kaufland Dortmund-Aplerbeck / `1503` |
| K2 bundle identity | `afdd992c547165259e760e05f41687793c56abc0af9869c8aa70f39d6f41dbbf` |
| Frozen retained Git revision | `c451fb9027e87b62685557ad3c2c66701e912d57` |
| K2 parser-input contract | `kaufland-k2-v1` |
| Family count | `4` |
| Artifact count | `6` |
| Family-manifest SHA-256 | `1e3dbe576df47bdd9f762915986247fac66de20c3fa2cc5d61891c22e5975184` |

Accepted K2 families remain:

1. `current_main` — `DE_de_KDZ1_1503_D33` — `a9baae4b5f702f59cbc3d9eba98eb12bdd31d91aaac5e49e2ac83ecb7fbb1db1`
2. `current_short` — `DE_de_KDZ2_1503_D34-MoMi` — `f8da4ff71615141aaf97ade1b91c3b63259a41b2436e09f65c5b4e4db6898e69`
3. `preview_main` — `DE_de_KDZ1_1503_D34` — `20f1b8f998e361399b9e1fec74f700712e1a62d7048fb92e40b5e9bbe8241c9a`
4. `preview_overlap` — `DE_de_leaflet2_1503_D34-EL-Schule` — `ab338f5fd1aca216380a1cbd0a0a7fea6f86a70a9bf656b1ed99d29dbcc4a6e3`

The accepted K2 replay remains `APPLY / NO_OP`. K3 must never substitute another store, retained revision, bundle identity or upstream parser-input contract.

## Real-K2 K3A result that motivated v2

One separately authorized offline retained-evidence derivation was executed against the accepted K2 packet. The authorization was consumed and **must not be retried** without new explicit owner authorization.

Sanitized result:

- retained verifier before and after: exact `NO_OP`;
- bundle: `afdd992c547165259e760e05f41687793c56abc0af9869c8aa70f39d6f41dbbf`;
- `artifact_count=6`, `family_count=4`;
- `offer-overview`:
  - SHA-256 `b95e735a707c9da023876ef280c6cbccfa1d7bf25d1638926eea035c27625e34`;
  - `4,440,080` bytes;
  - `text/html; charset=UTF-8`;
- candidate card count: `1212`;
- deliberate coarse ownership locator matched `1099` candidates and correctly failed as `AMBIGUOUS_CARD_OWNERSHIP`;
- second derivation was deterministic;
- observed source markers included:
  - promo-like text `nur`;
  - old-price marker `k-price-tag__old-price`;
  - XTRA structure `k-price-tag--xtra`;
  - `Mit Kaufland Card XTRA **`;
- `valid_receipt_count=0`;
- `promo_receipt_count=0`;
- `reference_receipt_count=0`;
- `xtra_receipt_count=0`;
- sampled cards had `family_match_count=0` / `FAMILY_BINDING_MISSING`;
- target-scoped retained fingerprint was byte-for-byte unchanged before and after.

Result:

`K3A_REAL_K2_EVIDENCE_BLOCKED=PASS`

This is a valid fail-closed result. It proves neither that the observed markers are accepted price-role semantics nor that a campaign family can be inferred from the common overview.

## Why v1 was insufficient

`kaufland-k3-source-card-v1` required one receipt to contain both:

- card-local price-role semantics; and
- one exact card-local K2 family binding.

The real-K2 run showed that those are separate provenance questions. A common `offer-overview` card may expose price-role evidence while the same card does not expose a defensible family binding.

The repair is **not** to weaken the family rule. The repair is to stop making family evidence a prerequisite for representing independent card semantics.

## Layer 1 — source-card semantic receipt

`SourceCardSemanticReceipt` binds only the evidence needed to establish source-card semantics.

It must contain:

### Upstream identity

- exact K2 bundle identity;
- frozen K2 Git revision;
- upstream contract `kaufland-k2-v1`;
- exact store `1503`.

### Source artifact identity

Only retained `offer-overview` HTML is accepted:

- role exactly `offer-overview`;
- exact source artifact SHA-256;
- positive byte count;
- content type beginning with `text/html`.

### Exact card ownership

- one sanitized deterministic `card_locator`;
- exact bounded `card_fragment_sha256`;
- `card_owner_match_count == 1`.

Zero or multiple card owners fail as `AMBIGUOUS_CARD_OWNERSHIP`.

### Price evidence

Every accepted price observation carries:

- role exactly `promo`, `reference` or `xtra`;
- canonical positive cent-precision Decimal amount;
- role locator;
- value locator;
- role evidence SHA-256;
- value evidence SHA-256;
- exact owning card locator and card fragment SHA;
- owner match count exactly `1`;
- assignment basis exactly `explicit_source_role_evidence`.

The semantic receipt deliberately has **no**:

- family relation;
- family source identifier;
- family identity;
- campaign validity dates;
- active/current/preview status.

A valid semantic receipt therefore cannot imply a campaign family.

## Layer 2 — family association receipt

`FamilyAssociationReceipt` binds one exact semantic receipt/card to a separate campaign-family decision.

It has exactly two statuses:

- `BOUND`;
- `UNBOUND`.

### BOUND

`BOUND` requires all of the following:

- one accepted K2 family relation;
- exact family source identifier;
- exact family identity SHA-256;
- explicit family-binding locator;
- family-binding evidence SHA-256;
- exact owning semantic card locator and card fragment SHA;
- owner match count exactly `1`;
- binding method exactly `explicit_card_local_source_evidence`;
- no blocker reason.

Page-level dates, nearby sections, publication timing, default-week logic and “closest family” logic are not accepted evidence.

### UNBOUND

`UNBOUND` is a first-class deterministic result.

Allowed blocker reasons:

- `FAMILY_BINDING_MISSING`;
- `FAMILY_BINDING_AMBIGUOUS`;
- `FAMILY_BINDING_NOT_CARD_LOCAL`.

An UNBOUND receipt must carry `None` for all:

- family relation;
- family source identifier;
- family identity;
- family evidence locator/hash;
- family owner locator/hash/count;
- family binding method.

The association schema has no validity/current/preview fields. Therefore an UNBOUND card cannot be promoted to active/current/preview semantics by this contract.

## Determinism

Price observations are canonicalized in `promo`, `reference`, `xtra` order before semantic receipt hashing.

Semantic receipt identity binds:

- exact upstream K2 identity;
- exact retained source artifact identity;
- exact card identity;
- every explicit price-role evidence locator/hash/value.

Family association identity separately binds:

- exact semantic receipt identity;
- exact semantic card identity;
- `BOUND` versus `UNBOUND`;
- exact blocker reason for UNBOUND; or
- exact family/evidence/ownership fields for BOUND.

Construction order must not alter identity. Evidence mutation must alter identity or fail validation.

## Fail-closed rules

| Reason code | Meaning |
| --- | --- |
| `STORE_BINDING_MISMATCH` | not exact store `1503` |
| `UPSTREAM_CONTRACT_MISMATCH` | not exact `kaufland-k2-v1` |
| `WRONG_SOURCE_ARTIFACT_ROLE` | card evidence is not from `offer-overview` |
| `WRONG_SOURCE_CONTENT_TYPE` | source artifact is not retained HTML |
| `AMBIGUOUS_CARD_OWNERSHIP` | card locator resolves to zero/multiple cards |
| `AMBIGUOUS_PRICE_OWNERSHIP` | price evidence does not have one card owner |
| `PRICE_EVIDENCE_OUTSIDE_CARD` | price evidence belongs to another card |
| `DUPLICATE_PRICE_ROLE` | multiple observations claim the same role |
| `PRICE_EVIDENCE_CROSS_BOUND` | locator/hash reused across different roles |
| `PRICE_ROLE_NOT_EXPLICIT` | role came from numeric/order inference |
| `INVALID_PRICE_AMOUNT` | amount is not canonical positive cent-precision Decimal evidence |
| `UNSUPPORTED_FAMILY_RELATION` | proposed BOUND family is outside accepted K2 baseline |
| `AMBIGUOUS_FAMILY_OWNERSHIP` | family evidence has zero/multiple card owners |
| `FAMILY_EVIDENCE_OUTSIDE_CARD` | family evidence belongs to another card |
| `FAMILY_BINDING_NOT_EXPLICIT` | family came from inferred/page-level context |
| `INVALID_UNBOUND_FAMILY_REASON` | UNBOUND uses an unsupported blocker reason |
| `UNBOUND_FAMILY_CARRIES_SEMANTICS` | UNBOUND was contaminated with family/evidence fields |
| `FAMILY_ASSOCIATION_SOURCE_CARD_MISMATCH` | association points at another semantic receipt/card |
| `RECEIPT_IDENTITY_MISMATCH` | semantic receipt was tampered |
| `FAMILY_ASSOCIATION_IDENTITY_MISMATCH` | family association was tampered |

Semantic consequences remain strict:

- XTRA cannot satisfy `promo`.
- A larger number is never automatically `reference`.
- Same numeric amount in two roles is acceptable only if distinct explicit evidence proves both roles.
- Nearby or page-level context cannot be imported into card ownership.
- `articleID` is evidence only; #704 remains the durable identity gate.

## #749 FAST source-only gate

This batch may prove only:

- v2 contract mechanics;
- deterministic semantic receipt identity;
- explicit price-role same-card ownership rules;
- BOUND family ownership rules;
- first-class UNBOUND family state;
- absence of family/validity/current/preview semantics from UNBOUND;
- receipt tamper detection.

This batch must not:

- read retained evidence again;
- retry the consumed derivation;
- make live Kaufland requests;
- run replay/runtime;
- create `backend/app/parsers/kaufland.py`;
- write DB/Review/publication state;
- deploy;
- mutate scheduler/systemd/host/Cloudflare state.

## Future real-K2 v2 evidence gate — separately authorized

A later owner authorization is required before reading the retained packet again.

When separately authorized, the next derivation should:

1. independently verify the exact accepted K2 packet before semantic inspection;
2. read only the exact retained `offer-overview` HTML;
3. resolve exact card owners;
4. derive **semantic receipts without requiring a family association**;
5. prove explicit `promo`, `reference`, `xtra` roles only from card-local evidence;
6. deliberately preserve ambiguous roles/owners as blockers;
7. independently attempt family association for each semantic receipt;
8. emit `BOUND` only with explicit card-local family evidence;
9. otherwise emit deterministic `UNBOUND` with a stable blocker reason;
10. derive the same sanitized result twice in changed construction order and require identical identities;
11. verify retained evidence remained unchanged;
12. STOP.

The future run must not treat a successful semantic receipt as permission to invent campaign validity.

## #702 parser gate

#702 remains separate.

This #749 source-only contract PR does **not** authorize parser implementation and does not itself establish real retailer role semantics.

Before parser work can consume a price role, a later reviewed real-K2 v2 semantic receipt must prove that role and same-card ownership.

Before parser work can consume campaign validity/current/preview semantics for a card, that card must have a reviewed `BOUND` family association. An `UNBOUND` association provides **no** validity/current/preview semantics.

If real K2 evidence remains insufficient, keep the affected semantics blocked. Do not infer values to satisfy #702 acceptance.

## Production classification

Network: **NO**  
Retained evidence read/write: **NO** in #749  
Runtime/replay: **NO**  
Parser implementation: **NO**  
Production DB write: **NO**  
Review/publication write: **NO**  
Scheduler/systemd/host mutation: **NO**  
Production deploy: **NO**
