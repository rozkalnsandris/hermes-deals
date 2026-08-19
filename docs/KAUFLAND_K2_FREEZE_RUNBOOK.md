# Kaufland K2 retained evidence freeze runbook

Status: source preparation only. This runbook does **not** authorize the retained evidence write.

Canonical issue: #701. Store: Kaufland Dortmund-Aplerbeck, exact store ID `1503`.

## Purpose

The K2 retained freeze preserves the first immutable multi-window Kaufland baseline outside the public Git repository. It binds:

- exact reviewed Git revision;
- exact store `1503` binding;
- store page raw HTML;
- store-bound offer overview raw HTML;
- all exact-store K2 leaflet-family raw responses discovered by the merged preflight contract;
- validity, relation, preview/activity state, requested/final URL, redirects, content type, byte count and SHA-256;
- parser-input contract identity;
- create-once bundle identity.

The raw retained location must be owner-side and outside the repository.

## Safety model

`tools/kaufland_k2_evidence_freeze.py` is deliberately local-only:

- it refuses `GITHUB_ACTIONS=true`;
- it requires a clean tracked checkout at the exact `--expected-revision`;
- it refuses a retained root inside the Git repository;
- default execution is PLAN only;
- APPLY additionally requires the exact literal authorization token implemented in source;
- APPLY additionally requires the exact PLAN `bundle_identity_sha256` and recomputes the captured bundle identity before any retained write;
- an absent, malformed or mismatched APPLY bundle identity fails closed before occupancy/write logic;
- common store/overview sources are fetched repeatedly and must remain SHA-identical across the capture transaction;
- each leaflet raw response must match the preflight SHA/byte count/final URL/content type/redirect identity;
- target occupancy is create-once;
- identical existing bundle identity returns `NO_OP`;
- non-identical occupancy returns `EVIDENCE_COLLISION`;
- an interrupted/failed write leaves `INCOMPLETE` and all later runs fail closed until owner inspection;
- retained files are written with exclusive-create semantics and verified again after write.

The implementation follows Python's exclusive-creation (`x` / `O_EXCL`) and `fsync` model; the source code uses `O_EXCL` plus post-write SHA verification.

## Preconditions before any PLAN

1. The freeze-executor PR is merged.
2. Resolve fresh exact `main`; do not reuse a SHA from this runbook.
3. The local checkout is the clean exact reviewed SHA.
4. Select/review an owner-side retained root outside the repository.
5. No production DB/Review/publication/deploy/scheduler/systemd authority is implied.

## PLAN — read-only with respect to retained storage

Replace both placeholders immediately before use:

```bash
python tools/kaufland_k2_evidence_freeze.py \
  --retained-root '<OWNER_RETAINED_ROOT>' \
  --expected-revision '<EXACT_MERGED_MAIN_SHA>'
```

Expected PLAN properties:

- `mode=PLAN`;
- `action=PLAN_CREATE` for an empty target, or `PLAN_NO_OP` for identical existing evidence;
- output includes the exact `bundle_identity_sha256` that must be owner-reviewed and later supplied to APPLY;
- `retained_evidence_write=false`;
- `raw_material_retained=false`;
- `corpus_write=false`;
- all production/Review/publication/deploy/scheduler/systemd write flags false.

A PLAN error, source drift, unexpected family set or non-identical occupancy blocks APPLY.

## APPLY — separate explicit owner authorization required

Do **not** execute this section from a generic `turpini`, merge command or deployment command.

Only after the owner explicitly authorizes the exact reviewed PLAN bundle identity + exact Git revision + retained root, run:

```bash
python tools/kaufland_k2_evidence_freeze.py \
  --retained-root '<OWNER_RETAINED_ROOT>' \
  --expected-revision '<EXACT_MERGED_MAIN_SHA>' \
  --expected-bundle-identity-sha256 '<PLAN_BUNDLE_IDENTITY_SHA256>' \
  --apply \
  --authorization-token 'I_AUTHORIZE_KAUFLAND_K2_RETAINED_FREEZE'
```

The executor captures one internally consistent bundle, recomputes its identity, and requires exact equality with the authorized PLAN identity **before any retained write**. If the source changed after PLAN, APPLY fails closed with `FREEZE_BUNDLE_IDENTITY_MISMATCH` and leaves retained storage unchanged.

For a first successful capture, expected result is `action=CREATE`. An exact replay must return `NO_OP`; it must not rewrite the bundle.

## Post-APPLY verification

After a separately authorized APPLY:

1. record the sanitized result only — no raw source in public GitHub comments/artifacts;
2. verify the returned bundle key and bundle identity SHA-256 exactly match the owner-authorized PLAN;
3. verify manifest family count and exact validity families against the PLAN;
4. independently read/hash retained files and compare to `manifest.json`;
5. verify `INCOMPLETE` is absent;
6. rerun the same exact command and require deterministic `NO_OP`;
7. record in #701 that production DB, Review, publication, deploy, scheduler and systemd writes remained false;
8. only then evaluate #701 acceptance and whether #702 K3 parser work is unblocked.

## Failure handling

- `FREEZE_BUNDLE_IDENTITY_REQUIRED` / `FREEZE_BUNDLE_IDENTITY_INVALID`: stop; APPLY is not sufficiently bound to an exact reviewed PLAN.
- `FREEZE_BUNDLE_IDENTITY_MISMATCH`: stop; the captured source identity differs from the owner-authorized PLAN. Do not write; run a fresh PLAN and obtain a new explicit owner authorization.
- `EVIDENCE_COLLISION`: stop; never overwrite. Inspect the existing retained bundle and source identity.
- `INCOMPLETE_EVIDENCE_PRESENT`: stop; inspect the partial capture manually. Do not delete or repair automatically.
- `EVIDENCE_CHANGED_DURING_FREEZE`: stop; the source changed during the capture transaction. Run a new PLAN against fresh source evidence.
- `GIT_REVISION_MISMATCH` / dirty checkout: stop and restore an exact clean reviewed checkout.
- store-binding/source identity errors: stop fail-closed; never substitute another store or generic Kaufland data.

**Production deploy: NO.**
