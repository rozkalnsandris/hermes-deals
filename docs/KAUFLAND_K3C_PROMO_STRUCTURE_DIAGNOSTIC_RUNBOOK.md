# Kaufland K3C public-promo structural diagnostic

Refs: #699, #702, #749, #756.

## Purpose

This source-only diagnostic is the next precision gate after the corrected K3C REAL-K2 owner/locator run.

Accepted post-#756 evidence proves product-tile ownership, reference-role evidence and XTRA-role evidence, but it does **not** prove the public promo role. The current K3C harness intentionally keeps `promo_receipt_count=0` and treats `nur` only as a promo-like marker.

This diagnostic answers one narrower question without promoting any role:

> Within the exact reviewed `k-product-tile` owner card, what deterministic DOM relationship exists between a `nur` marker and leaf-most canonical amount carriers that are outside explicit XTRA and old-price branches?

It emits bounded sanitized structural metadata only. It never emits product text, product IDs, raw HTML, raw hrefs, cookies, credentials or retained binaries.

Implementation:

`backend/app/kaufland_k3c_promo_structure_diagnostic.py`

Contract:

`kaufland-k3c-promo-structure-diagnostic-v1`

## Safety classification

- network/live collection: **NO**
- retained evidence read: **YES only when the diagnostic is later executed**
- retained evidence write: **NO**
- runtime/replay executor: **NO**
- #702 parser implementation: **NO**
- public promo promotion: **NO**
- production DB/Review/publication write: **NO**
- deploy: **NO**
- scheduler/systemd/host/container/secrets/Cloudflare mutation: **NO**

Under FAST-LANE v2.2, the later retained read/evidence refresh is a read-only automation checkpoint, not Composite Live mutation. A host checkout synchronization remains a separate host mutation if it is needed.

## Exact retained boundary

The diagnostic reuses the existing reviewed K3C gates from
`app.kaufland_real_k2_v2_derivation`:

- store `1503`;
- canonical bundle key `kaufland/1503/k2/2026-08-13_2026-09_02`;
- bundle identity `afdd992c547165259e760e05f41687793c56abc0af9869c8aa70f39d6f41dbbf`;
- frozen K2 revision `c451fb9027e87b62685557ad3c2c66701e912d57`;
- exact `offer-overview` identity;
- BeautifulSoup `4.15.0`;
- parser backend `html.parser`;
- exact K2 verifier `NO_OP`;
- target-scoped before/after fingerprint invariance;
- process-local network guard;
- deterministic second derivation.

No sibling retained packet is scanned for semantics.

## Structural candidate rule

For every `nur` text marker:

1. resolve its immediate parent;
2. resolve the nearest exact reviewed `<a class="k-product-tile" href tabindex>` owner;
3. if no exact owner exists, record an orphan marker and do not invent ownership;
4. inside the exact owner only, enumerate leaf-most elements containing exactly one canonical amount;
5. exclude any candidate whose ancestry reaches `k-price-tag--xtra` or `k-price-tag__old-price`;
6. do **not** rank candidates by amount, proximity, order or value;
7. record only the deterministic structural relationship from marker parent to each remaining candidate.

A candidate is diagnostic evidence only. It is **not** a public-promo receipt.

## Sanitized output

Per sampled marker, output may include:

- marker tag and deterministic rawpath;
- marker fragment SHA-256;
- `k-price*` structural class tokens only;
- marker canonical-amount count;
- exact owner-card locator and fragment SHA-256;
- public-amount candidate count;
- bounded candidate structural samples.

Per candidate sample, output may include:

- candidate tag and rawpath;
- candidate fragment SHA-256;
- `k-price*` structural class tokens only;
- whether exact generic `k-price-tag` is present;
- the marker/candidate lowest-common-ancestor relation;
- bounded upward step counts;
- LCA tag/rawpath and `k-price*` class tokens.

The candidate amount value itself is never emitted.

The diagnostic also emits bounded aggregate structural signatures with counts. If signatures or samples exceed output bounds, the output says they were truncated. Truncation never authorizes promo promotion.

## Role boundary

The diagnostic always emits:

- `evidence_only=true`;
- `promo_role_promoted=false`;
- `promo_role_policy=BLOCKED_UNTIL_EXPLICIT_SOURCE_ROLE_EVIDENCE`.

A successful diagnostic process returns `status=PASS` only to mean that the read-only structural inspection completed deterministically with unchanged retained evidence. It does **not** mean the public promo role is accepted.

A later source change may promote public promo only if reviewed REAL-K2 output proves a stable explicit role rule that is independent of numeric ordering and does not collide with XTRA/reference semantics.

## Command

From the backend environment on a checkout containing the reviewed diagnostic source:

```bash
python -m app.kaufland_k3c_promo_structure_diagnostic \
  --retained-root /home/andris/hermes-deals-retained-evidence
```

Expected successful execution properties:

- process exit `0`;
- top-level `status=PASS`;
- `evidence_only=true`;
- `promo_role_promoted=false`;
- exact K2 verifier `NO_OP`;
- unchanged before/after retained target fingerprint;
- deterministic second derivation;
- no network or write flags.

Identity drift, parser-version drift, retained drift, non-determinism or unsafe filesystem state must return bounded `BLOCKED`/exit `20`.

## Acceptance for the source batch

Before Ready:

- focused synthetic tests pass;
- full current repository CI passes on the exact PR head;
- exact diff is limited to diagnostic source/tests/runbook;
- no `backend/app/parsers/kaufland.py`;
- no retained evidence read by CI/source batch;
- no live Kaufland network;
- no DB/Review/publication/deploy/runtime/host mutation;
- Draft PR -> CI/review -> Ready -> STOP.

After merge, the next evidence step is the read-only command above against the already accepted retained packet. The resulting sanitized structural evidence must be reviewed before any public-promo selector is promoted or #702 consumes promo semantics.

Production deploy: **NO**.
