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

The owner authorization identity and the retained bundle identity are intentionally distinct:

- `authorization_identity_sha256` binds the exact reviewed Git revision, store identity, parser-input contract and the immutable exact-store family identities. It intentionally excludes collection timestamp, time-derived `active_at_collection`, skipped non-store leaflet metadata, and common store/overview HTML bytes.
- `bundle_identity_sha256` binds the complete retained capture, including common HTML, full family preflight metadata and skipped-leaflet metadata. It is the immutable identity of what was actually retained, but the bundle identity is not the owner authorization token.

This split prevents harmless context drift from invalidating a reviewed family authorization while preserving full post-capture immutability. Any exact-store family byte/URL/validity/relation/redirect identity change still changes `authorization_identity_sha256` and blocks APPLY.

## Safety model

`tools/kaufland_k2_evidence_freeze.py` is deliberately local-only:

- it refuses `GITHUB_ACTIONS=true`;
- it requires a clean tracked checkout at the exact `--expected-revision`;
- it refuses a retained root inside the Git repository;
- default execution is PLAN only;
- APPLY additionally requires the exact literal authorization token implemented in source;
- APPLY additionally requires the exact PLAN `authorization_identity_sha256` and recomputes it from the captured exact-store family set before any retained write;
- an absent, malformed or mismatched APPLY authorization identity fails closed before occupancy/write logic;
- the legacy `--expected-bundle-identity-sha256` authorization argument is rejected fail-closed and requires a fresh PLAN;
- common store/overview sources are still fetched repeatedly and must remain SHA-identical inside each capture transaction;
- each leaflet raw response must match the preflight SHA/byte count/final URL/content type/redirect identity;
- target occupancy is create-once;
- identical existing full bundle identity returns `NO_OP`;
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
- output includes `authorization_identity_sha256`; this is the exact identity the owner reviews and later supplies to APPLY;
- output also includes `bundle_identity_sha256` as the full capture identity observed during PLAN; it is informational for authorization and may change if only non-authorized context changes before APPLY;
- `retained_evidence_write=false`;
- `raw_material_retained=false`;
- `corpus_write=false`;
- all production/Review/publication/deploy/scheduler/systemd write flags false.

A PLAN error, exact-store family drift, unexpected family set or non-identical retained occupancy blocks APPLY.

## APPLY — separate explicit owner authorization required

Do **not** execute this section from a generic `turpini`, merge command or deployment command.

Only after the owner explicitly authorizes the exact reviewed PLAN authorization identity + exact Git revision + retained root, run:

```bash
python tools/kaufland_k2_evidence_freeze.py \
  --retained-root '<OWNER_RETAINED_ROOT>' \
  --expected-revision '<EXACT_MERGED_MAIN_SHA>' \
  --expected-authorization-identity-sha256 '<PLAN_AUTHORIZATION_IDENTITY_SHA256>' \
  --apply \
  --authorization-token 'I_AUTHORIZE_KAUFLAND_K2_RETAINED_FREEZE'
```

The executor captures one internally consistent bundle, recomputes `authorization_identity_sha256` from the exact-store family set, and requires exact equality with the owner-authorized PLAN identity **before any retained write**. A family byte/URL/validity/relation/redirect change fails closed with `FREEZE_AUTHORIZATION_IDENTITY_MISMATCH` (or an earlier source-consistency error) and leaves retained storage unchanged.

Common store/overview HTML may differ between PLAN and APPLY without invalidating the family authorization, but it must remain internally stable during the APPLY capture transaction and is still included in the final immutable `bundle_identity_sha256`.

For a first successful capture, expected result is `action=CREATE`. An immediate exact replay should return `NO_OP`; it must not rewrite the bundle. If common/context evidence changes before replay, the existing create-once target may correctly return `EVIDENCE_COLLISION` instead of being overwritten.

## Post-APPLY verification

After a separately authorized APPLY:

1. record the sanitized result only — no raw source in public GitHub comments/artifacts;
2. verify the returned `authorization_identity_sha256` exactly matches the owner-authorized PLAN identity;
3. record the returned `bundle_identity_sha256` as the immutable identity of the bundle actually created; it is not required to equal the PLAN bundle identity;
4. verify manifest family count and exact validity families against the PLAN;
5. independently read/hash retained files and compare to `manifest.json`;
6. verify `INCOMPLETE` is absent;
7. rerun the same exact command immediately and require deterministic `NO_OP` when the full capture identity is unchanged;
8. record in #701 that production DB, Review, publication, deploy, scheduler and systemd writes remained false;
9. only then evaluate #701 acceptance and whether #702 K3 parser work is unblocked.

## Failure handling

- `FREEZE_AUTHORIZATION_IDENTITY_REQUIRED` / `FREEZE_AUTHORIZATION_IDENTITY_INVALID`: stop; APPLY is not sufficiently bound to an exact reviewed family authorization.
- `FREEZE_AUTHORIZATION_IDENTITY_MISMATCH`: stop; the captured exact-store family identity differs from the owner-authorized PLAN. Do not write; run a fresh PLAN and obtain a new explicit owner authorization.
- `FREEZE_BUNDLE_AUTHORIZATION_DEPRECATED`: stop; do not reuse the old bundle-identity authorization syntax. Merge the remediation, run a fresh PLAN, and authorize the new `authorization_identity_sha256`.
- `EVIDENCE_COLLISION`: stop; never overwrite. Inspect the existing retained bundle and source identity.
- `INCOMPLETE_EVIDENCE_PRESENT`: stop; inspect the partial capture manually. Do not delete or repair automatically.
- `EVIDENCE_CHANGED_DURING_FREEZE`: stop; the source changed during the capture transaction. Run a new PLAN against fresh source evidence.
- `GIT_REVISION_MISMATCH` / dirty checkout: stop and restore an exact clean reviewed checkout.
- store-binding/source identity errors: stop fail-closed; never substitute another store or generic Kaufland data.

**Production deploy: NO.**
