# ALDI new immutable weekly baseline — Gate C deterministic replay

Issue: #682

## Purpose

Gate A established a distinct immutable weekly ALDI baseline identity after the
historical A3.0 `49 current + 41 preview` evidence was formally recorded as
`IRRECOVERABLE_LEGACY_EVIDENCE`.

Gate B established deterministic bidirectional page/card parity for that new
identity, with explicit candidate↔card bindings and zero unexplained in-scope
cards.

Gate C proves that the **same immutable Gate B identity can be replayed
deterministically and read-only** before any weekly shadow-cycle gate is
allowed to begin.

This is a new-baseline contract. It does not reuse the historical A3.1 Gate C
identity or its frozen A2.1/49+41 constants.

## Input contract

`tools/aldi_new_baseline_gate_c_replay.py` accepts one JSON object with:

- `schema_version=1`;
- mode `ALDI_NEW_BASELINE_GATE_C_REPLAY_V01`;
- issue `682`;
- one exact Gate B binding:
  - mode `ALDI_NEW_BASELINE_PAGE_CARD_PARITY_V01`;
  - decision `READY_FOR_NEW_BASELINE_GATE_C`;
  - distinct non-A3.0/A3.1 baseline ID;
  - exact baseline fingerprint;
  - exact parity fingerprint;
  - exact candidate-projection SHA256;
  - exact card-ledger SHA256;
  - exact candidate/card counts;
  - `unexplained_card_count=0`;
  - `historical_issue_56_completion_claimed=false`;
  - `production_eligible=false`;
- exactly two replay observations, ordered `replay-01`, `replay-02`.

Each replay observation must be classified `offline_shadow_replay` and bind the
same canonical Gate B replay-input identity. Both observations must reproduce:

- the exact Gate B candidate projection;
- the exact Gate B card ledger;
- the exact candidate and card counts;
- one identical semantic-output SHA256;
- zero unexplained cards;
- zero duplicate candidates;
- zero state writes;
- zero candidate writes;
- zero Review writes;
- zero database writes.

Any difference fails closed.

## Determinism and idempotency

The canonical replay identity covers:

- the exact Gate B identity;
- the canonical replay-input SHA256;
- the semantic-output SHA256;
- both normalized replay observations.

With no prior Gate C result, valid evidence returns:

`READY_FOR_TWO_CONSECUTIVE_WEEKLY_SHADOW_CYCLES`

This means only that deterministic read-only replay, duplicate freedom and
idempotency have been proven for the immutable baseline identity.

If the same exact Gate C result is supplied again through `--prior`, the
decision becomes:

`NO_OP`

A repeated `NO_OP` remains `NO_OP` and preserves the same replay identity.

Prior evidence is rejected if it differs byte-for-byte after normalizing its
decision back to the READY form, if the replay identity changed, or if prior
evidence claims production eligibility, promotion readiness, weekly shadow
completion, or historical issue #56 completion.

## Next gate

Gate C deliberately does **not** claim that the required weekly shadow evidence
already exists.

Its successful next step is:

`two_consecutive_weekly_shadow_cycles`

That later gate must use two distinct weekly campaigns and remain bound to the
exact Gate C replay identity. It must continue to require:

- zero unexplained cards;
- ambiguity routed to Review or explicit exclusion;
- duplicate-free replay;
- no production canary authority until the two-cycle acceptance is separately
  satisfied and owner-approved.

## Safety boundary

The implementation validates metadata only. It does not perform:

- network acquisition;
- parser execution;
- source/corpus writes;
- candidate creation;
- Review/publication writes;
- production database writes;
- automatic approval/publication;
- production deployment;
- scheduler/retry activation;
- production canary;
- historical corpus reconstruction;
- weekly shadow-cycle execution.

All of those authorities remain `false` in the result safety contract.

Normal project workflow remains:

fresh `main` → fresh branch → focused change → Draft PR → exact-head CI +
manual diff/review → Ready → STOP → explicit owner squash merge → exact-main
CI → deploy classification.
