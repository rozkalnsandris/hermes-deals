# Kaufland K3C REAL-K2 v2 read-only derivation runbook

Refs: #699, #701, #702, #747, #749, #750, #751, #752.

## Purpose

K3C provides one reviewed repo-native command for deterministic, fail-closed inspection of the accepted immutable Kaufland K2 retained packet.

It is deliberately **not** the Kaufland parser. It does not create `backend/app/parsers/kaufland.py`, write database/Review/publication state, collect live Kaufland data, mutate retained evidence, or deploy anything.

The implementation is:

`backend/app/kaufland_real_k2_v2_derivation.py`

Current derivation contract:

`kaufland-k3c-real-k2-v2-derivation-v1`

The semantic receipt contract remains:

`kaufland-k3-source-card-v2`

## FAST-LANE v2.2 classification

FAST-LANE v2.2 makes read-only checkpoints, preflight, evidence refresh, candidate verification and reconciliation automation steps rather than separate owner gates.

Therefore a later execution of this harness is **not** a Composite Live mutation merely because it reads already-retained evidence. The live gate remains required for retained mutation, runtime/replay executor invocation, production DB write/migration, deploy, scheduler/systemd/host/container mutation, secrets/credentials, Cloudflare mutation, or other live authority changes.

This #752 source PR itself performs no owner-retained read. It only reviews the code/tests/runbook that a later read-only execution may use.

Merge of this source PR never authorizes #702 parser implementation or any live mutation.

## Exact accepted K2 boundary

| Field | Accepted value |
| --- | --- |
| Store | `1503` / Kaufland Dortmund-Aplerbeck |
| Bundle key | `kaufland/1503/k2/2026-08-13_2026-09-02` |
| Bundle identity | `afdd992c547165259e760e05f41687793c56abc0af9869c8aa70f39d6f41dbbf` |
| Frozen K2 revision | `c451fb9027e87b62685557ad3c2c66701e912d57` |
| K2 parser-input contract | `kaufland-k2-v1` |
| Artifact count | `6` |
| Family count | `4` |
| `offer-overview` relative path | `common/offer-overview.bin` |
| `offer-overview` SHA-256 | `b95e735a707c9da023876ef280c6cbccfa1d7bf25d1638926eea035c27625e34` |
| `offer-overview` bytes | `4440080` |
| `offer-overview` content type | `text/html; charset=UTF-8` |
| BeautifulSoup | `4.15.0` |
| HTML backend | `html.parser` |

The K2 verifier must return exact `NO_OP` with the expected bundle identity/counts before semantic inspection.

## Retained target scope

The harness receives only an explicit retained root:

```bash
python -m app.kaufland_real_k2_v2_derivation \
  --retained-root /home/andris/hermes-deals-retained-evidence
```

It derives the exact target from the pinned bundle key. It does not enumerate sibling retained packets for semantics.

Target-scoped fingerprinting recursively hashes only that exact target. A sibling-packet change must not alter the target fingerprint.

## Network boundary

The harness imports no collector and makes no HTTP request.

During execution it additionally installs a process-local socket guard over:

- `socket.socket.connect`;
- `socket.socket.connect_ex`;
- `socket.create_connection`;
- `socket.getaddrinfo`.

Any attempted network use fails closed as `NETWORK_FORBIDDEN`.

This is defense in depth, not permission to add network-capable code later.

## Exact verification order

The run is deterministic and read-only:

1. verify exact BeautifulSoup version;
2. calculate exact target-scoped fingerprint;
3. call existing `verify_retained_bundle()` with the pinned K2 bundle/revision/contract/identity;
4. require `NO_OP`, 6 artifacts and 4 families;
5. re-read the verified manifest;
6. require exactly one common `offer-overview` record with the pinned relative path/SHA/bytes/content type;
7. require the artifact path to be a regular non-symlink file;
8. independently read/hash/count the overview bytes;
9. decode strict UTF-8;
10. derive a bounded sanitized projection;
11. derive the same projection again with changed construction order;
12. require byte/semantic equality;
13. run `verify_retained_bundle()` again;
14. recalculate the exact target fingerprint;
15. require before/after verifier equality and fingerprint equality;
16. emit only sanitized JSON;
17. STOP.

Any failure returns a bounded `BLOCKED` payload with a stable reason code and no raw exception text.

## Source-card ownership boundary

K3C must not invent a retailer card CSS selector.

For each exact `kloffer-articleID` link, the harness walks upward only a bounded number of ancestors and selects the **smallest** DOM scope that:

- contains exactly one distinct source article ID; and
- contains at least one price-role clue (`k-price-tag__old-price`, `k-price-tag--xtra`, or the observed text marker `nur`).

If a candidate ancestor contains more than one distinct article ID, that ownership path fails closed.

`articleID` is used only as source-local ownership evidence. It is not promoted to global/timeless product identity; #704 remains the identity gate.

## Price-role policy

Precision overrides completeness.

### Reference

`reference` may be emitted only from an exact same-scope element carrying:

`k-price-tag__old-price`

The element must contain exactly one canonical price amount.

A larger unlabelled number is never a reference price.

### XTRA

`xtra` may be emitted only from an exact same-scope element carrying:

`k-price-tag--xtra`

The element must contain exactly one canonical price amount.

XTRA never satisfies public promo.

### Public promo — intentionally still blocked

The previous REAL-K2 sanitized evidence observed text `nur`, but that result explicitly classified it only as a **promo-like marker clue**, not accepted retailer role semantics.

Therefore K3C must **not** convert `nur` alone into a `promo` receipt.

Instead the harness records only bounded sanitized promo-marker observations:

- owning bounded card locator;
- marker kind `text:nur`;
- marker locator;
- marker fragment SHA-256;
- canonical amount count;
- booleans for the known generic/XTRA/old-price classes.

It emits:

`promo_role_policy=BLOCKED_UNTIL_EXPLICIT_SOURCE_ROLE_EVIDENCE`

and `promo_receipt_count=0`.

A future reviewed source change may promote a public-promo selector only after sanitized real-K2 evidence defensibly proves an explicit role rule. No numeric order, nearby text, page-level context, or guessed class semantics may be used.

Because promo remains unproven, the current K3C evidence gate is expected to remain `BLOCKED`. That is a valid precision-oriented result.

## Family association

Family association remains separate from semantic price receipts.

For each valid semantic receipt:

- scan only the exact bounded owner scope for one of the four accepted K2 source identifiers;
- zero matches -> deterministic `UNBOUND / FAMILY_BINDING_MISSING`;
- multiple accepted matches -> deterministic `UNBOUND / FAMILY_BINDING_AMBIGUOUS`;
- one exact accepted identifier -> `BOUND` through the existing v2 family-association contract.

No page-level dates, nearest section, campaign order, current week, preview timing or default family may create `BOUND`.

An UNBOUND association carries no family/current/preview/validity semantics.

## Deliberate ambiguity probe

The sanitized result includes one intentionally broad structural selector count.

If that selector resolves to more than one owner candidate, the probe records:

`AMBIGUOUS_CARD_OWNERSHIP`

This proves the broad ownership strategy is rejected; it is not used to create semantic receipts.

## Determinism

The harness derives twice:

- normal card/role construction order;
- reversed card/role construction order.

Before comparison it canonicalizes:

- semantic receipts by receipt identity;
- family associations by association identity;
- promo-marker observations by sanitized locator/hash tuple;
- blocker counts by reason code.

Any output difference is `DERIVATION_NONDETERMINISTIC`.

## Sanitization

Allowed output is bounded structured metadata only.

Never emit:

- full retained HTML;
- full product/card HTML;
- product title/brand text;
- cookies;
- credentials;
- filesystem exception text;
- uncontrolled raw attributes;
- binaries.

Receipt locators, evidence hashes, accepted K2 identifiers and bounded counts are allowed provenance.

## Expected result interpretation

### `BLOCKED`

`BLOCKED` is normal when real source evidence is insufficient.

For the corrected K3C v1 harness, public promo is intentionally unproven, so a real run should remain BLOCKED even if reference/XTRA semantic receipts are established.

Useful BLOCKED evidence may include:

- candidate scope count;
- reference/XTRA receipt counts;
- promo marker observations;
- BOUND/UNBOUND family counts;
- ambiguity-probe result;
- blocker counts;
- deterministic second derivation;
- unchanged target fingerprint.

Do not turn BLOCKED into PASS by weakening role or ownership rules.

### Future `PASS`

PASS is not available until a later reviewed source change adds defensible explicit public-promo role evidence and the real retained packet proves all required K3 role gates.

That later source change must be separately reviewed through normal FAST source workflow.

## #702 parser gate

#702 remains separate.

K3C source merge does not authorize parser implementation.

Before #702 may consume a role:

- `reference` must have reviewed real-K2 same-card evidence;
- `xtra` must have reviewed real-K2 same-card evidence;
- `promo` must have reviewed real-K2 explicit public-promo evidence;
- family validity/current/preview semantics require a reviewed `BOUND` family association.

UNBOUND provides no campaign validity.

If real K2 evidence remains insufficient, keep the affected semantics blocked or route them to Review later. Never guess to satisfy parser acceptance.

## Failure handling

Read-only derivation itself is not a mutation gate under FAST-LANE v2.2.

If the harness observes identity drift, ambiguity, nondeterminism, unexpected bytes, unexpected parser version or any other contract failure:

- preserve the sanitized result;
- STOP semantic promotion;
- do not alter retained evidence;
- do not fall back to live Kaufland network;
- do not start #702 parser implementation from the failed assumption.

If a later operation crosses into a Composite Live mutation category, the separate v2.2 live authorization and post-mutation STOP rules apply.

## Production classification

Network: **NO**  
Retained evidence read: **YES only when the later read-only harness is executed**  
Retained evidence write: **NO**  
Runtime/replay executor: **NO**  
Parser implementation: **NO**  
Production DB/Review/publication write: **NO**  
Scheduler/systemd/host/container mutation: **NO**  
Secrets/Cloudflare mutation: **NO**  
Production deploy: **NO**
