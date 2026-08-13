# Lidl one-row canary: PLAN → APPLY → DONE

This is the operator workflow for a reviewed Lidl V6.3.1 one-row production canary.

The safety checks remain strict, but C0/C1/C2/C3 are not separate operator ceremonies once the exact reviewed source/receipt/semantic row already exists. They are validation concerns inside PLAN.

## 1. PLAN

PLAN is one read-only operation.

It must:

- bind the exact current Git commit and clean source state;
- bind the reviewed receipt, semantic row and frozen source hashes;
- use PostgreSQL `REPEATABLE READ, READ ONLY`;
- compute deterministic SourceSnapshot and OfferCandidate identities;
- detect exact-key conflicts or an already-identical no-op;
- emit plan and payload fingerprints;
- emit the exact APPLY authorization payload;
- require expected replay delta `0/0`;
- perform no production DB, Review, corpus, publication, deploy, source-replacement, systemd or scheduler write.

A blocked/conflicting PLAN cannot be authorized for APPLY.

## 2. APPLY

APPLY is a separate explicit owner authorization for one exact PLAN fingerprint.

The existing reviewed semantic persistence primitive remains authoritative for database mutation. It:

- accepts only the exact one-row authorization contract;
- permits at most one SourceSnapshot and one OfferCandidate write;
- uses deterministic identities and the existing uniqueness contract;
- requires the post-write plan to become `NO_OP_IDENTICAL` before commit;
- rolls back on an exception before successful commit;
- accepts a pre-existing identical canary as a zero-write no-op;
- keeps Review, publication, deploy, corpus/source replacement, systemd and scheduler authority false.

The reusable CLI verifies observed total-row deltas against the apply result after commit.

## 3. DONE

`APPLY_PASS` or `APPLY_NO_OP_IDENTICAL` with zero replay writes is terminal for the canary.

There is no mandatory C5/post-C4 verification ceremony. A new diagnostic/read-only audit is justified only if APPLY reports a mismatch, a later incident creates a concrete reason to re-check, or the owner explicitly requests an audit.

Production deploy is a separate decision and is never implied by a canary DB write.

## Runtime policy

Do not rebuild an unchanged audit Python environment merely because Git `main` advanced. Reusable audit runtime identity should be tied to the reviewed Python identity and dependency lock SHA; source execution remains independently bound to the exact Git SHA.

Do not duplicate credentials, provenance and source validation across one-off operator shell scripts. The long-term interface is the repo-owned PLAN/APPLY entrypoint and the reviewed persistence primitive.
