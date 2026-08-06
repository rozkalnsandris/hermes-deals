# ALDI weekly automation Gate C shadow replay preflight

Issue: #208  
Parent roadmap: #165  
Gate B merge: `1a547eb6a440114ec488e22a825655746eca730f`

## Purpose

Gate C prevents the weekly ALDI replay path from claiming candidate/card parity before all required immutable inputs exist.

Gate B already proves the exact 41-page rollover partition:

- 39 byte-identical carry-forward parity pages;
- current page 3 requires fresh shadow extraction;
- current page 41 is non-offer informational evidence and must remain excluded.

That page proof is not the same as completed offer/card parity. The old A3.1 template begins with an empty `cards` list, and no empty template may be treated as a completed visual ledger.

Gate C is therefore a Python-only preflight and deterministic work-package builder. It does not execute the parser or create candidates.

## Exact Gate B binding

The repository includes the exact Gate B result:

```text
config/aldi-weekly-gate-b-replay-plan-31105044968.json
```

Required identities:

```text
Gate B plan SHA256:
3188821faa36a6d9fb598fde521a59993e6cb11678a8160e4afead4ba4fcfdd4

Replay fingerprint:
1e5dc0d2ae192d26d5880c798a275945090af04ded286c6a06f9a7233a2bbffd

Current manifest SHA256:
82816ac5ecbba08a2025406cdf3854e67f47ecd8cf2eed54fdc147da0838457a
```

The preflight validates the complete file SHA, schema, artifact binding, 41 page rows, canonical current-manifest hash, exact 39/1/1 partition, moved mappings, page 3 and page 41 dispositions, frozen legacy A3.1 identity and the complete read-only safety contract.

A minimal object containing only the fingerprint is rejected.

## Required replay inputs

### A2.1 adjudicated projection

Required SHA256:

```text
64699b7ede52dcaa5b85f3306426f3b90399dd037209621a38bacd166161d5ea
```

Required contract:

- 519 unique `(source_page, source_offer_id)` rows;
- 346 `auto_candidate`;
- 54 `review_required`;
- 119 `blocked_out_of_scope`.

Malformed JSONL, duplicates, unknown statuses or count drift fail closed.

The corresponding frozen archive identity is recorded as:

```text
fa16df4db701e90f38bea0387a278750415ba03628f1fe1cc34ffb2833f2985d
```

### Completed legacy A3.1 parity bundle

Gate C requires one canonical JSON bundle with:

```text
mode=ALDI_A31_COMPLETED_PARITY_BUNDLE_V01
```

It must contain:

- the complete A3.1 summary;
- all 400 target offer-to-card mapping rows;
- reverse card coverage;
- an empty blocker list;
- exact mapping and reverse hashes;
- zero blocked candidates;
- zero unexplained cards;
- zero automatic approvals/publications;
- no DB, deploy or collector action.

The preflight derives carried card bindings only for the 39 proven old-preview pages. Old preview pages 37 and 41 cannot enter the carry-forward work package.

An empty card-ledger template is not a completed parity bundle.

### Current page 3 fresh-extraction ledger

Required page SHA256:

```text
ad297cdd2f3dc728f0114fcb8a06c6d2c6131f4b342173b134d9e99bd092ae7c
```

Required mode:

```text
ALDI_WEEKLY_PAGE3_FRESH_SHADOW_EXTRACTION_V01
```

Every page-3 candidate must:

- use a stable `current:p003:cNNN` card identity;
- remain `review_required`;
- include at least one Review reason;
- remain non-production-eligible;
- forbid automatic approval and publication.

The ledger records evidence only. Candidate creation, DB writes and Review writes must all be false.

## Decisions

### `WAIT_FOR_VISUAL_LEDGER`

Returned when the exact Gate B plan passes but one or more replay inputs are absent.

The current controlled repository-only invocation intentionally returns:

```text
missing_inputs=[
  a21_adjudicated_projection,
  completed_legacy_a31_parity_bundle,
  page3_fresh_shadow_extraction_ledger
]
```

This is an honest waiting state. It must never be rendered as zero offers or a parity PASS.

### `READY_FOR_SHADOW_REPLAY`

Returned only when:

- the exact A2.1 projection passes;
- the completed A3.1 parity bundle passes;
- the page-3 extraction ledger passes;
- all input identities produce one deterministic work package and replay identity.

This status authorizes only a later offline shadow replay and duplicate/immutability audit. It does not authorize production.

### `NO_OP`

Returned only when a complete prior `READY_FOR_SHADOW_REPLAY` result has the exact same replay identity and complete safety contract.

A waiting, partial or fingerprint-only prior result is rejected.

## Work package

The deterministic work package contains exactly 41 current pages:

- 39 `carry_forward_parity`;
- one `fresh_shadow_extraction` page: page 3;
- one `exclude_non_offer_informational` page: page 41.

When a completed legacy bundle is supplied, old preview card IDs are translated to stable new-current card IDs according to the exact Gate B page mapping. Page 3 candidates are inserted only from the exact Review-only page-3 ledger.

The current missing-input work package SHA256 is:

```text
1b8b672dc35f2d8d9ad7df76a507bcd43777520ecca092a7c3b82e0d390c962a
```

## Controlled invocation

Repository-only preflight:

```bash
python3 tools/aldi_weekly_gate_c_shadow_replay_preflight.py \
  --gate-b-plan config/aldi-weekly-gate-b-replay-plan-31105044968.json \
  --output /tmp/aldi-gate-c-preflight.json
```

A controlled complete-input invocation later uses:

```bash
python3 tools/aldi_weekly_gate_c_shadow_replay_preflight.py \
  --gate-b-plan config/aldi-weekly-gate-b-replay-plan-31105044968.json \
  --a21-projection /exact/path/a21-adjudicated-projection.jsonl \
  --legacy-parity-bundle /exact/path/completed-a31-parity-bundle.json \
  --page3-ledger /exact/path/page3-fresh-shadow-extraction.json \
  --output /exact/create-only/path/aldi-gate-c-preflight.json
```

The output is create-only. Repeating identical bytes returns `unchanged`; differing existing output fails closed.

## Safety

Gate C performs no:

- network acquisition;
- parser execution;
- source or corpus mutation;
- candidate creation;
- production database or Review write;
- approval or publication;
- deployment or restart;
- scheduler, retry or systemd action;
- production canary;
- B15M2 V08 action.

The strict 41/41 automatic-promotion gate remains unchanged and blocked.
