# ALDI new immutable weekly baseline — Gate B page/card parity

Issue: #682

## Purpose

Gate A established a distinct weekly ALDI baseline identity after the historical
A3.0 `49 current + 41 preview` evidence was formally recorded as
`IRRECOVERABLE_LEGACY_EVIDENCE`.

Gate B adds the new baseline's deterministic **bidirectional page/card parity
contract**. It is intentionally independent from the historical A3.1 identity
and does not claim completion of issue #56.

## Design choice: explicit bindings, no fuzzy promotion

The historical A3.1 engine supported conservative title/brand/price matching.
The new baseline path is stricter: Gate B does **not** infer card ownership from
text similarity.

Every candidate row names one exact stable card ID, and every card row carries
the exact reverse list of candidate IDs. The two directions must agree
byte-for-byte after canonical normalization.

This keeps the weekly path precision-first:

- a defensible candidate is `auto_candidate` on an `in_scope/candidate` card;
- uncertainty is `review_required` on a `review/review` card with an explicit
  reason;
- unsupported/out-of-scope evidence is `excluded` on an
  `excluded/excluded` card with an explicit reason;
- no review or excluded row can be silently promoted to an automatic candidate.

## Input contract

`tools/aldi_new_baseline_page_card_parity.py` accepts one JSON object with:

- `schema_version=1`, mode `ALDI_NEW_BASELINE_PAGE_CARD_PARITY_V01`, issue
  `682`;
- one Gate A binding:
  - Gate A mode `ALDI_NEW_IMMUTABLE_BASELINE_GATE_A_V01`;
  - Gate A decision `READY_FOR_NEW_BASELINE_ADJUDICATION`;
  - distinct non-A3.0/A3.1 baseline ID;
  - exact baseline fingerprint;
  - exact page-manifest SHA256 and bounded page count;
  - `historical_issue_56_completion_claimed=false`;
- one canonical candidate projection:
  - exact projection SHA256 over the normalized candidate rows;
  - unique candidate ID and payload SHA256;
  - exact page number and stable card ID;
  - route `auto_candidate`, `review_required`, or `excluded`;
  - explicit reason for review/excluded rows;
- one canonical visual card ledger:
  - exact ledger SHA256 over normalized card rows;
  - stable card ID `pNNN:cNNN`;
  - exact page SHA256 and normalized page region;
  - exact scope/route pair;
  - exact reverse candidate-ID list;
  - explicit reason for review/excluded cards.

The bounded limits are 128 pages, 4096 candidate rows and 8192 card rows.

## Bidirectional acceptance

Gate B passes only when:

1. every candidate references an existing card on the same page;
2. candidate route and card scope/route agree exactly;
3. every card's declared candidate list equals the candidates that point back
   to it;
4. every `in_scope/candidate` card has at least one explicit candidate;
5. every review/excluded route has an explicit reason;
6. candidate-projection and card-ledger canonical hashes match their declared
   SHA256 values.

A passing ledger therefore has `unexplained_card_count=0`.

## Output

A valid input produces:

`READY_FOR_NEW_BASELINE_GATE_C`

and an immutable `parity_fingerprint` covering the exact baseline binding,
candidate projection and card ledger.

The result sets:

- `parity_complete=true`;
- `gate_c_continuation_ready=true`;
- `historical_issue_56_completion_claimed=false`;
- `production_eligible=false`;
- `promotion_ready=false`.

The next gate is a **distinct new-baseline Gate C shadow replay** that must prove
zero duplicate candidates and zero immutable-payload drift before any later
weekly-family acceptance.

## Safety boundary

This gate is source-only metadata validation. It authorizes/performs none of:

- network acquisition;
- parser execution;
- source/corpus mutation;
- candidate creation;
- Review/publication writes;
- automatic approval/publication;
- production DB writes;
- production deploy;
- scheduler/retry activation;
- production canary;
- historical corpus reconstruction;
- newer-evidence substitution for historical #56 completion.

Normal project workflow remains:

fresh `main` → focused branch → Draft PR → exact-head CI/manual review → Ready
→ STOP → explicit owner squash merge → exact-main CI → deploy classification.
