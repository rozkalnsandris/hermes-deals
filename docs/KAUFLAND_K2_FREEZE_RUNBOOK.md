# Kaufland K2 retained evidence freeze runbook

Status: source preparation only. This runbook does **not** authorize a retained evidence write or replay.

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

This split prevents harmless context drift from invalidating a reviewed family authorization while preserving full post-capture immutability. Any exact-store family byte/URL/validity/relation/redirect identity change still changes `authorization_identity_sha256` and blocks CREATE APPLY.

A deterministic replay of an already-retained bundle has a separate authorization boundary. `replay_authorization_identity_sha256` binds the **fixed replay executor revision**, resolved retained root, exact store `1503`, retained bundle key and identity, frozen retained Git revision, parser-input contract, and retained artifact/family counts. It does not depend on the current Kaufland publication state.

## Safety model

`tools/kaufland_k2_evidence_freeze.py` is deliberately local-only:

- it refuses `GITHUB_ACTIONS=true`;
- it requires a clean tracked checkout at the exact `--expected-revision`;
- it refuses a retained root inside the Git repository;
- default execution is PLAN only;
- APPLY additionally requires the exact literal authorization token implemented in source;
- normal CREATE APPLY additionally requires the exact PLAN `authorization_identity_sha256` and recomputes it from the captured exact-store family set before any retained write;
- an absent, malformed or mismatched CREATE APPLY authorization identity fails closed before occupancy/write logic;
- the legacy `--expected-bundle-identity-sha256` authorization argument is rejected fail-closed and requires a fresh PLAN;
- normal absent-target CREATE/PLAN keeps the existing live discovery/preflight/capture behavior;
- common store/overview sources are fetched repeatedly and must remain SHA-identical inside each live capture transaction;
- each live leaflet raw response must match the preflight SHA/byte count/final URL/content type/redirect identity;
- target occupancy is create-once;
- any `NO_OP`, including the normal live path, independently re-reads and hashes every retained artifact against `manifest.json` before success;
- retained verification rejects a symlink/non-directory target, symlinked manifest/artifacts, `INCOMPLETE`, manifest identity mismatch, missing/extra files or directories, corrupt artifact bytes, wrong store/revision/parser contract, or any bundle identity mismatch;
- existing-bundle replay is retained-first and runs before any `httpx.Client` construction or live Kaufland discovery;
- exact existing-bundle replay returns `PLAN_NO_OP` or `APPLY / NO_OP` without a retained write and without network access;
- non-identical occupancy returns `EVIDENCE_COLLISION` rather than overwrite;
- an interrupted/failed CREATE leaves `INCOMPLETE` and all later runs fail closed until owner inspection;
- retained CREATE files are written with exclusive-create semantics and verified again after write.

The implementation follows Python's exclusive-creation (`x` / `O_EXCL`) and `fsync` model; the source code uses `O_EXCL` plus post-write SHA verification.

## Preconditions before any PLAN

1. The relevant executor/remediation PR is merged.
2. Resolve fresh exact `main`; do not reuse a SHA from this runbook.
3. The local checkout is the clean exact reviewed executor SHA.
4. Select/review an owner-side retained root outside the repository.
5. No production DB/Review/publication/deploy/scheduler/systemd authority is implied.
6. For replay, independently identify the immutable retained bundle key, bundle identity, frozen retained Git revision and parser-input contract from accepted retained evidence. Do not substitute current live source state.

## Normal PLAN — live CREATE path

Use this path only for absent-target capture planning or when intentionally validating current live source behavior.

Replace both placeholders immediately before use:

```bash
python tools/kaufland_k2_evidence_freeze.py \
  --retained-root '<OWNER_RETAINED_ROOT>' \
  --expected-revision '<EXACT_MERGED_MAIN_SHA>'
```

Expected normal PLAN properties:

- `mode=PLAN`;
- `action=PLAN_CREATE` for an empty target, or `PLAN_NO_OP` only if the newly captured full bundle exactly matches an existing retained bundle;
- output includes `authorization_identity_sha256`; this is the exact identity the owner reviews and later supplies for a CREATE APPLY;
- output also includes `bundle_identity_sha256` as the full capture identity observed during PLAN; it is informational for CREATE authorization and may change if only non-authorized context changes before APPLY;
- `retained_evidence_write=false`;
- `raw_material_retained=false`;
- `corpus_write=false`;
- all production/Review/publication/deploy/scheduler/systemd write flags false.

A PLAN error, exact-store family drift, unexpected family set or non-identical retained occupancy blocks CREATE APPLY.

## Existing-bundle replay PLAN — offline retained-first path

Use this path for deterministic replay acceptance of an already-retained immutable bundle. It deliberately does **not** call live Kaufland discovery/preflight/capture.

```bash
python tools/kaufland_k2_evidence_freeze.py \
  --retained-root '<OWNER_RETAINED_ROOT>' \
  --expected-revision '<EXACT_FIXED_REPLAY_EXECUTOR_SHA>' \
  --replay-existing-bundle-key '<EXACT_RETAINED_BUNDLE_KEY>' \
  --expected-retained-bundle-identity-sha256 '<EXACT_RETAINED_BUNDLE_IDENTITY_SHA256>' \
  --expected-retained-git-revision '<EXACT_FROZEN_RETAINED_GIT_SHA>' \
  --expected-retained-parser-input-contract-version '<EXACT_RETAINED_PARSER_CONTRACT>'
```

Expected replay PLAN properties:

- `mode=PLAN`;
- `action=PLAN_NO_OP`;
- output `bundle_identity_sha256` exactly equals the accepted retained identity;
- output includes `replay_authorization_identity_sha256`, which binds the fixed executor revision and exact retained bundle/root contract for later owner authorization;
- every retained artifact is re-hashed and byte-counted against `manifest.json`;
- retained file/directory structure is exact with no symlinks or `INCOMPLETE` marker;
- no `httpx.Client` or live Kaufland request occurs;
- every write flag is false.

Any retained integrity/identity mismatch blocks replay APPLY. Do not fall back to a live capture to make historical replay pass.

## CREATE APPLY — separate explicit owner authorization required

Do **not** execute this section from a generic `turpini`, merge command or deployment command.

Only after the owner explicitly authorizes the exact reviewed normal PLAN authorization identity + exact Git revision + retained root, run:

```bash
python tools/kaufland_k2_evidence_freeze.py \
  --retained-root '<OWNER_RETAINED_ROOT>' \
  --expected-revision '<EXACT_MERGED_MAIN_SHA>' \
  --expected-authorization-identity-sha256 '<PLAN_AUTHORIZATION_IDENTITY_SHA256>' \
  --apply \
  --authorization-token 'I_AUTHORIZE_KAUFLAND_K2_RETAINED_FREEZE'
```

The executor captures one internally consistent bundle, recomputes `authorization_identity_sha256` from the exact-store family set, and requires exact equality with the owner-authorized PLAN identity **before any retained write**. A family byte/URL/validity/relation/redirect change fails closed with `FREEZE_AUTHORIZATION_IDENTITY_MISMATCH` (or an earlier source-consistency error) and leaves retained storage unchanged.

Common store/overview HTML may differ between normal PLAN and CREATE APPLY without invalidating the family authorization, but it must remain internally stable during the APPLY capture transaction and is still included in the final immutable `bundle_identity_sha256`.

For a first successful capture, expected result is `action=CREATE`.

## Existing-bundle replay APPLY — separately authorized, offline and read-only

After the replay PLAN above, owner authorization must bind the exact `replay_authorization_identity_sha256`, fixed executor revision, retained root and immutable retained bundle packet. The old CREATE authorization or any authorization bound to the frozen historical code revision is not transferable to a fixed replay executor revision.

```bash
python tools/kaufland_k2_evidence_freeze.py \
  --retained-root '<OWNER_RETAINED_ROOT>' \
  --expected-revision '<EXACT_FIXED_REPLAY_EXECUTOR_SHA>' \
  --replay-existing-bundle-key '<EXACT_RETAINED_BUNDLE_KEY>' \
  --expected-retained-bundle-identity-sha256 '<EXACT_RETAINED_BUNDLE_IDENTITY_SHA256>' \
  --expected-retained-git-revision '<EXACT_FROZEN_RETAINED_GIT_SHA>' \
  --expected-retained-parser-input-contract-version '<EXACT_RETAINED_PARSER_CONTRACT>' \
  --expected-replay-authorization-identity-sha256 '<PLAN_REPLAY_AUTHORIZATION_IDENTITY_SHA256>' \
  --apply \
  --authorization-token 'I_AUTHORIZE_KAUFLAND_K2_RETAINED_FREEZE'
```

Required result:

- `mode=APPLY`;
- `action=NO_OP`;
- exact retained bundle identity/key/counts;
- exact replay authorization identity;
- no retained write or metadata mutation;
- no live network access;
- all production/Review/publication/deploy/scheduler/systemd flags false.

Replay APPLY never calls `apply_freeze()` and never creates/replaces/deletes retained evidence. Its only success path is a verified immutable `NO_OP`.

## Post-APPLY verification

After a separately authorized CREATE APPLY:

1. record the sanitized result only — no raw source in public GitHub comments/artifacts;
2. verify the returned `authorization_identity_sha256` exactly matches the owner-authorized PLAN identity;
3. record the returned `bundle_identity_sha256` as the immutable identity of the bundle actually created; it is not required to equal the PLAN bundle identity;
4. verify manifest family count and exact validity families against the PLAN;
5. independently read/hash retained files and compare to `manifest.json`;
6. verify `INCOMPLETE` is absent;
7. perform replay only under a separate replay PLAN + explicit owner replay authorization using the retained-first path above;
8. for replay, snapshot retained structure/content hashes/inode/size/mode/mtime/ctime before and after and require exact equality;
9. record in #701 that production DB, Review, publication, deploy, scheduler and systemd writes remained false;
10. only then evaluate #701 acceptance and whether #702 K3 parser work is unblocked.

## Failure handling

- `FREEZE_AUTHORIZATION_IDENTITY_REQUIRED` / `FREEZE_AUTHORIZATION_IDENTITY_INVALID`: stop; CREATE APPLY is not sufficiently bound to an exact reviewed family authorization.
- `FREEZE_AUTHORIZATION_IDENTITY_MISMATCH`: stop; the captured exact-store family identity differs from the owner-authorized CREATE PLAN. Do not write; run a fresh normal PLAN and obtain a new explicit owner authorization.
- `FREEZE_BUNDLE_AUTHORIZATION_DEPRECATED`: stop; do not reuse the old bundle-identity authorization syntax.
- `REPLAY_ARGUMENTS_INCOMPLETE`: stop; replay target identity is not fully specified.
- `REPLAY_BUNDLE_IDENTITY_INVALID`: stop; the expected retained bundle identity is malformed.
- `REPLAY_AUTHORIZATION_AMBIGUOUS`: stop; do not mix live CREATE authorization with retained replay authorization.
- `REPLAY_AUTHORIZATION_IDENTITY_REQUIRED` / `REPLAY_AUTHORIZATION_IDENTITY_INVALID`: stop; replay APPLY is not bound to an exact owner-reviewed replay PLAN.
- `REPLAY_AUTHORIZATION_IDENTITY_MISMATCH`: stop; fixed executor/root/retained bundle packet differs from the owner-authorized replay PLAN. Do not invoke any alternate replay path.
- `RETAINED_ARTIFACT_MISMATCH`: stop; retained bytes no longer match the immutable manifest. Do not repair/delete/overwrite automatically.
- `EVIDENCE_COLLISION`: stop; never overwrite. For replay this includes wrong target/store/revision/parser identity, malformed manifest, symlink nodes, or missing/extra retained structure.
- `INCOMPLETE_EVIDENCE_PRESENT`: stop; inspect the partial capture manually. Do not delete or repair automatically.
- `EVIDENCE_CHANGED_DURING_FREEZE`: stop; the live source changed during a normal capture transaction. Run a new normal PLAN against fresh source evidence; this error is not a reason to weaken historical replay identity.
- `GIT_REVISION_MISMATCH` / dirty checkout: stop and restore an exact clean reviewed checkout.
- store-binding/source identity errors on the normal live path: stop fail-closed; never substitute another store or generic Kaufland data.

**Production deploy: NO.**
