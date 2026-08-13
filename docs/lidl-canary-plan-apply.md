# Lidl canary lifecycle: PLAN → APPLY → DONE

The Lidl V6.3.1 one-row production canary is a **first-write validation gate**, not a workflow to repeat for every reviewed row.

The first successful canary proved the persistence contract. Future rollout work should reuse the existing persistence core and move to a separately planned bounded rollout/batch gate instead of recreating C0/C1/C2/C3/C4 for another single row.

## Canonical persistence contract

No additional canary framework or wrapper is required.

The canonical implementation already lives in `backend/app/lidl_v631_semantic_persistence.py`:

- `build_lidl_v631_semantic_persistence_plan(...)` is the PLAN primitive;
- `apply_lidl_v631_semantic_persistence_plan(...)` is the APPLY primitive.

Both primitives are already input-driven. They receive the reviewed receipt bytes, exact semantic row, row-binding SHA-256 and frozen source binding as arguments rather than depending on a product-specific canary identity.

The existing tests in `backend/tests/test_lidl_v631_semantic_persistence.py` remain the authoritative contract tests.

## 1. PLAN

PLAN is one read-only validation boundary.

It must:

- bind one exact independently reviewed row and its frozen source evidence;
- compute deterministic SourceSnapshot and OfferCandidate identities;
- detect an exact create, identical no-op or conflict;
- produce deterministic payload and plan fingerprints;
- report expected first-apply and replay deltas;
- perform no production DB, Review, corpus, publication, deploy, source-replacement, systemd or scheduler write.

For a production preflight, the caller must additionally enforce the production transaction as read-only and bind the current source/runtime state. Those are execution-environment guards around the PLAN primitive, not separate operator stages.

A blocked/conflicting plan cannot proceed to APPLY.

## 2. APPLY

APPLY is one separate explicit owner authorization for the exact reviewed row and exact PLAN fingerprint.

The canonical APPLY primitive:

- accepts only the exact authorization scope and stable bindings;
- rejects permission widening;
- permits at most one SourceSnapshot and one OfferCandidate for a one-row canary;
- preserves deterministic identities and the existing uniqueness constraint;
- requires the post-write plan to become `NO_OP_IDENTICAL` before commit;
- rolls back on an exception before successful commit;
- treats an already-identical row as a zero-write no-op;
- keeps Review, publication, deploy, corpus/source replacement, systemd and scheduler authority false.

## 3. DONE

A first canary APPLY that reports the expected exact writes and zero-write identical replay is terminal for that canary.

There is **no mandatory C5/post-C4 verification stage** and no reason to repeat a new C0→C4 chain for the next reviewed row merely because another row is ready.

A new read-only diagnostic is justified only when:

- APPLY reports a mismatch or fails after commit;
- a later incident creates a concrete reason to re-check the persisted row; or
- the owner explicitly asks for a fresh audit.

After the first canary has passed, the next engineering decision is the size and acceptance criteria of a separately authorized bounded rollout/batch gate. That rollout must have its own read-only plan and explicit write authorization, but it should not recreate the first-canary ceremony.

Production deploy remains a separate decision and is never implied by a database canary or later batch write.

## Runtime policy

Do not rebuild an unchanged audit Python environment merely because Git `main` advanced. Runtime identity should be tied to the reviewed Python identity and dependency-lock SHA, while source execution is independently bound to the exact Git SHA.

Do not duplicate credentials, provenance checks or persistence logic across large one-off operator shell scripts. Reuse the canonical persistence core and keep execution-environment guards small and purpose-specific.
