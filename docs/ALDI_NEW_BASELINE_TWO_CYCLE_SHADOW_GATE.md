# ALDI new immutable weekly baseline — two-cycle shadow acceptance

Issue: #682

## Purpose

Gate A created a distinct immutable ALDI baseline identity after the historical
A3.0 `49 current + 41 preview` evidence was formally recorded as
`IRRECOVERABLE_LEGACY_EVIDENCE`.

Gate B proved explicit candidate↔card parity for that new baseline.

Gate C proved deterministic exact-input replay, duplicate freedom, immutable
payload stability and `NO_OP` semantics for the new baseline identity.

This gate defines the acceptance evidence for the next requirement in #682:
**two consecutive real weekly shadow families**. It validates evidence only. It
does not run acquisition, parsing, shadow cycles, schedulers or production
canaries.

## Gate C binding

Input must bind one successful result from
`ALDI_NEW_BASELINE_GATE_C_REPLAY_V01` with:

- issue `682`;
- decision `READY_FOR_TWO_CONSECUTIVE_WEEKLY_SHADOW_CYCLES` or the exact
  idempotent `NO_OP`;
- exact Gate C replay identity;
- deterministic replay, duplicate-free, idempotency and no-mutation proofs;
- a distinct non-A3.0/A3.1 baseline ID;
- `historical_issue_56_completion_claimed=false`;
- `production_eligible=false`;
- `promotion_ready=false`;
- `weekly_shadow_cycles_complete=false`.

## Two real weekly cycles

Exactly two ordered rows are required: `cycle-01`, then `cycle-02`.

Each row must be classified:

- `evidence_class=real_weekly_shadow`;
- `execution_origin=rpi5_shadow`;
- `source_state=available`.

Each cycle binds:

- one distinct ISO week and campaign ID;
- one official ALDI Nord HTTPS source URL;
- exact source, page-manifest, candidate-projection, card-ledger, semantic-output
  and evidence-artifact SHA256 values;
- exact parser implementation SHA256;
- exact parity-contract SHA256;
- one distinct real run ID and UTC observation timestamp;
- candidate/card/Review-route/exclusion counts;
- immutable shadow-state SHA256 before and after the exact replay.

The two rows must be consecutive ISO weeks. Campaign IDs, run IDs, source
identities, page manifests and evidence artifacts must be distinct.

The parser implementation and parity contract must remain identical across both
cycles. If either changes, the two-cycle acceptance window restarts instead of
combining incomparable evidence.

## Replay/no-op acceptance

The first materialization of a real shadow family may create isolated shadow
state. The acceptance criterion is the exact replay:

- `replay_new_candidate_count=0`;
- `replay_duplicate_candidate_count=0`;
- `immutable_payload_drift_count=0`;
- `shadow_state_sha256_before_replay == shadow_state_sha256_after_replay`;
- `review_pending_count=0`;
- `unexplained_card_count=0`.

This gate does not require every ambiguous row to become an automatic
candidate. Ambiguity may remain explicitly routed to Review or excluded, but a
cycle cannot pass while Review evidence is still pending.

Production DB, Review, publication and source mutation counts must all remain
zero.

## Required failure-state observability

The input must also bind one immutable evidence SHA256 for every required state:

- `not_published_yet → WAIT`;
- `source_unavailable → WAIT`;
- `stale → BLOCKED`;
- `evidence_mismatch → BLOCKED`;
- `parser_failed → BLOCKED`;
- `review_pending → WAIT`.

This prevents unavailable or failed source states from being misrepresented as
a valid zero-offer weekly cycle.

## Successful decision

Only the complete exact evidence set returns:

`READY_FOR_PRODUCTION_CANARY_PLAN`

This means the two-cycle shadow acceptance is complete and a **separate,
bounded production-canary plan may be prepared later**.

It does not authorize canary application, production DB writes, publication,
deployment or scheduler activation.

Re-evaluating the exact same accepted evidence through `--prior` returns
`NO_OP` and preserves the acceptance fingerprint.

## Safety boundary

The validator grants no authority for:

- network acquisition;
- parser execution;
- source/corpus mutation;
- candidate creation;
- Review/publication writes;
- production database writes;
- automatic approval/publication;
- production deployment;
- scheduler/retry activation;
- production canary preparation or application;
- historical corpus reconstruction;
- weekly shadow-cycle execution.

Normal workflow remains:

fresh `main` → fresh branch → focused change → Draft PR → exact-head CI +
manual diff/review → Ready → STOP → explicit owner squash merge → exact-main
CI → deploy classification.
