# ALDI new immutable weekly baseline — Gate A

Issue: #682

## Purpose

The historical A3.0 `49 current + 41 preview` evidence required by #56 is formally
recorded as `IRRECOVERABLE_LEGACY_EVIDENCE`. Weekly ALDI work must therefore use
a **new immutable baseline identity**, not rebuild, relabel, or substitute the
missing historical corpus.

This Gate A is intentionally only a source/evidence contract. It does not
perform acquisition, parsing, candidate creation, Review writes, database
writes, deployment, scheduler changes, or a production canary.

## Input contract

`tools/aldi_new_immutable_baseline_gate.py` validates one JSON object containing:

- `schema_version=1`, mode `ALDI_NEW_IMMUTABLE_BASELINE_GATE_A_V01`, issue `682`;
- retailer `ALDI Nord` and a distinct `baseline_id` that cannot reuse A3.0/A3.1;
- historical lineage bound to issue #56 and
  `IRRECOVERABLE_LEGACY_EVIDENCE`, with both historical-completion and
  newer-evidence-substitution claims set to `false`;
- one bounded campaign identity (`campaign_id`, `region`, `store_scope`,
  ISO validity window of at most 14 days);
- 1..8 HTTPS source artifacts labelled `official_aldi_nord`, each with exact
  SHA256 and byte size;
- one contiguous immutable page manifest with exact per-page path, SHA256,
  byte size and image format plus a canonical manifest SHA;
- exact parser contract and implementation identities with SHA256;
- immutable acquisition run/artifact provenance and `source_state=available`.

The gate accepts metadata only. It does not fetch any URL or open page-image
bytes.

## Decision

A valid input produces:

`READY_FOR_NEW_BASELINE_ADJUDICATION`

This means only that one distinct weekly source/page/parser/provenance identity
is sufficiently bound to begin a **new** bidirectional page/card adjudication
gate.

It explicitly does **not** mean:

- historical #56 completion;
- page/card parity complete;
- Gate C continuation ready;
- production eligibility or promotion readiness.

The next gate must build a new page/card ledger, account for every in-scope or
Review card, route ambiguity to Review or explicit exclusion, and reach zero
unexplained cards before a distinct Gate C continuation can be considered.

## Determinism and fail-closed behavior

The canonical baseline fingerprint covers:

- baseline ID and retailer;
- campaign identity and validity;
- all exact source artifact identities;
- page-manifest identity and page count;
- parser contract/implementation identity;
- acquisition provenance;
- the permanent historical non-completion lineage.

The same input produces the same fingerprint. Reversed or overly broad campaign
windows, HTTP sources, source/hash drift, malformed or non-contiguous page
manifests, parser hash drift, stale/non-available source state, legacy identity
reuse, or any attempt to claim/substitute historical completion fails closed.

## Safety boundary

All live authorities remain false:

- network acquisition;
- parser execution;
- source/corpus writes;
- candidate creation;
- Review/publication writes;
- production database writes;
- automatic approval/publication;
- production deploy;
- scheduler/retry activation;
- production canary;
- historical corpus reconstruction;
- newer-evidence substitution.

Normal project workflow still applies:
fresh `main` → branch → Draft PR → exact-head CI/manual review → Ready → STOP →
explicit owner squash merge → exact-main CI → separate deploy classification.
