# Kaufland K3C promo-structure RPi5 bridge

Refs: #702, #749, #758, #760, #761.

## Purpose

This bridge exposes one owner-gated RPi5 execution path for the reviewed read-only Kaufland K3C promo-structure diagnostic. It exists only to inspect the accepted retained K2 packet and export bounded sanitized structural evidence.

It does **not** add a parser selector, promote `nur` to a public-promo role, fetch Kaufland over the network, write retained evidence, mutate production data, or deploy production.

Bridge contract:

`kaufland-k3c-promo-structure-rpi5-bridge-v2`

The diagnostic contract remains:

`kaufland-k3c-promo-structure-diagnostic-v1`

## Why v2 exists

The v1 bridge used one SHA for both the reviewed bridge revision and the RPi checkout HEAD. After #760 the primary RPi checkout correctly moved forward to newer `main`, so v1 would require a rewind to the old #758 merge before registration or execution. A later unrelated PR also could not safely substitute for #758 merely because it was a reachable merged-main SHA.

v2 is explicitly non-rewind. It separates the reviewed bridge-control-plane revision from the exact checkout used for later execution.

## Identity model

Two SHA identities are mandatory:

1. **registration SHA** — the exact squash merge that introduces or updates the v2 K3C bridge workflow **and** installer;
2. **execution checkout SHA** — the exact current `main` commit present on the RPi when a diagnostic is run.

The execution checkout SHA may equal the registration SHA or be a descendant of it. The bridge must **never rewind** the primary checkout.

The selected registration PR is not an arbitrary selector. Its merge commit must be single-parent and both of these blobs must differ from its parent:

- `.github/workflows/kaufland-k3c-promo-structure-rpi5.yml`;
- `tools/runner/install-kaufland-k3c-promo-structure-rpi5-bridge.sh`.

That rule prevents an unrelated later merged PR from being treated as the bridge revision.

## Trusted source set

The following files are trusted as one reviewed execution boundary:

- `.github/workflows/kaufland-k3c-promo-structure-rpi5.yml`;
- `tools/runner/install-kaufland-k3c-promo-structure-rpi5-bridge.sh`;
- `tools/runner/kaufland_k3c_promo_structure_bridge_validator.py`;
- `backend/app/kaufland_k3c_promo_structure_diagnostic.py`;
- `backend/app/kaufland_real_k2_v2_derivation.py`;
- `backend/app/kaufland_evidence_freeze.py`;
- `backend/app/kaufland_source_card_contract.py`;
- `backend/app/kaufland_source_discovery.py`.

A descendant checkout is acceptable only while every trusted Git blob remains byte-identical to the registration SHA. Any trusted-source drift blocks registration or execution. A changed K3C control plane therefore requires a new reviewed registration PR; it is never inherited silently.

## GitHub-hosted authorization

The workflow remains `workflow_dispatch` only and accepts one input: the merged K3C bridge **registration PR number**.

Before a self-hosted job can start, the GitHub-hosted authorizer requires:

1. repository exactly `rozkalnsandris/hermes-deals`;
2. workflow ref exactly `refs/heads/main`;
3. actor login `rozkalnsandris` and numeric owner ID `277435981`;
4. a positive same-repository PR merged into `main`;
5. a valid single-parent registration merge SHA;
6. proof that the registration commit changes both the K3C workflow and installer relative to its parent;
7. current GitHub `main` resolved independently as the execution checkout SHA;
8. registration SHA is an ancestor of or identical to execution SHA;
9. registration revision CI is successful — exact merge-SHA push CI, or exact PR-head pull-request CI with squash-tree equivalence;
10. **exact execution-main push CI** is successful;
11. every trusted-source blob is identical between registration and execution SHAs.

No path, shell fragment, command, retained root, Python module, or diagnostic option is accepted from the workflow event.

## Self-hosted boundary

The RPi job retains:

- labels `self-hosted`, `Linux`, `ARM64`, `hermes-deals-audit`;
- `permissions: {}`;
- no `actions/checkout`;
- one fixed root-owned dispatcher only.

The dispatcher interface is exactly:

```text
/usr/local/sbin/hermes-deals-kaufland-k3c-promo-structure-dispatch \
  <registration-sha> <execution-checkout-sha> <runner-artifact-dir>
```

The runner supplies only the two hosted-authorized SHAs and its private fixed-shape artifact directory.

## Root registration boundary

The installer is inert source until separately owner-authorized on RPi5. Registration is a **host mutation**. Source merge does not authorize it.

After the v2 registration PR is merged and the RPi source checkout has separately reached that merge or a later approved descendant through the dedicated source-sync bridge, the registration command is:

```bash
sudo bash tools/runner/install-kaufland-k3c-promo-structure-rpi5-bridge.sh \
  <exact-v2-registration-merge-sha>
```

The installer requires the primary checkout `/home/andris/hermes-deals` to be:

- the canonical non-symlink path owned by `andris`;
- a non-shallow Git worktree;
- branch `main`;
- completely clean including untracked files;
- bound to the canonical Hermes Deals GitHub origin;
- at the registration SHA or a descendant of it.

Before persistent writes, the installer also:

- proves the registration merge is single-parent;
- proves the registration merge changed both bridge-control-plane files;
- proves every trusted source blob at current HEAD equals its registration-SHA blob;
- computes and validates trusted SHA-256 identities;
- checks `github-runner` is not in the Docker group;
- validates generated shell and sudoers configuration.

Only after those gates does persistent registration begin. It installs:

- one root-owned validator;
- one root-owned config;
- one fixed root-owned dispatcher;
- one sudoers rule allowing `github-runner` to invoke that dispatcher only.

The config records the registration SHA, the checkout SHA present at registration, and all trusted source hashes separately.

Registration performs no Git fetch, checkout, reset, switch, pull or source sync; it does not execute the diagnostic and does not read the retained packet beyond checking that the fixed retained root exists as a safe directory.

If registration fails after persistent writes begin, preserve the staging path/evidence and STOP. No retry, rollback, cleanup, or alternate mutation path is authorized automatically.

## Runtime fail-closed checks

Before every diagnostic run, the dispatcher requires:

- its supplied registration SHA equals the root-owned registered identity;
- exact local clean `main` HEAD equals the supplied execution checkout SHA;
- canonical origin and non-shallow checkout;
- registration SHA is an ancestor of execution SHA;
- every trusted current source SHA-256 equals the registered value;
- every trusted Git blob at execution SHA equals the registration-SHA blob;
- fixed retained root exists and is not a symlink;
- runner artifact directory matches the exact private allowlist and metadata contract.

Any mismatch blocks before the diagnostic.

## Fixed diagnostic execution

The dispatcher hardcodes:

- source checkout `/home/andris/hermes-deals`;
- retained root `/home/andris/hermes-deals-retained-evidence`;
- module `app.kaufland_k3c_promo_structure_diagnostic`.

The diagnostic runs as unprivileged `andris` with a clean environment, `PYTHONDONTWRITEBYTECODE=1`, `PYTHONNOUSERSITE=1`, and `PYTHONHASHSEED=0`.

The diagnostic continues to enforce exact retained bundle identity, K2 verifier `NO_OP`, BeautifulSoup `4.15.0`, `html.parser`, process-local network guard, target fingerprint invariance, deterministic second derivation, and all no-write/no-deploy flags.

The source checkout must remain on the exact execution checkout SHA and clean after execution.

## Sanitization and v2 receipt

The existing reviewed validator continues to validate the diagnostic payload under its v1 sanitizer contract. Only after that validation succeeds does the dispatcher stamp the outer bridge envelope to v2.

The v2 sanitized diagnostic/summary must include both:

- `registered_commit_sha` — the exact bridge registration SHA;
- `execution_checkout_sha` — the exact current-main checkout used by the diagnostic.

The outer receipt uses bridge schema version `2` and contract `kaufland-k3c-promo-structure-rpi5-bridge-v2`.

Raw diagnostic stdout and private stderr stay in the private staging directory and are removed before successful export. The validator still rejects extra diagnostic fields, amount-value injection, promo promotion, unsafe exit/status pairings, identity drift and bound violations.

Only the validated diagnostic JSON, summary JSON, and artifact manifest may reach the runner artifact directory. The manifest also binds registration and execution SHAs.

## PASS / BLOCKED semantics

`bridge_execution_status=PASS` means only that the fixed control plane and sanitization contract completed successfully.

The nested diagnostic may be:

- `diagnostic_status=PASS` — deterministic read-only structural inspection completed;
- `diagnostic_status=BLOCKED` — the diagnostic reached an expected fail-closed semantic/evidence condition.

A validated semantic BLOCKED remains evidence. It never promotes `nur` or creates public-promo semantics.

Infrastructure, source identity, ancestry, CI, trusted-source, registration or sanitization failures are bridge BLOCKED.

## Required sequence after a future v2 merge

Each step begins with fresh canonical GitHub/runtime evidence.

1. Verify current GitHub `main`, the exact v2 registration PR/merge SHA, CI, reviews and trusted-source state.
2. If RPi source is behind, obtain separate owner authorization to use the **source-sync bridge** to fast-forward the primary checkout to the exact approved registration SHA or later approved descendant. No rewind.
3. Obtain separate owner authorization for K3C **root registration** with the exact v2 registration merge SHA.
4. Inspect the registration receipt. On failure/ambiguity, preserve evidence and STOP; no automatic retry.
5. Before retained evidence is read, obtain the separately required owner authorization for K3C **diagnostic execution**.
6. Dispatch the K3C workflow using the exact v2 registration PR number. The workflow independently binds exact current `main` as execution SHA.
7. Review the sanitized structural artifact before any public-promo acceptance or #702 parser change.

Source-sync registration, K3C root registration and diagnostic execution remain distinct authority boundaries. Merge authorization never implies any of them.

## Safety classification

- live Kaufland network fetch: **NO**
- retained evidence read during source/CI: **NO**
- retained evidence read during later authorized diagnostic: **YES**
- retained evidence write: **NO**
- parser #702 implementation: **NO**
- public-promo promotion: **NO**
- production DB write: **NO**
- Review/publication write: **NO**
- production deploy: **NO**
- scraper/runtime activation: **NO**
- Cloudflare mutation: **NO**
- scheduler/systemd change by diagnostic: **NO**
- source checkout mutation during this source batch: **NO**
- root registration during this source batch: **NO**
- diagnostic execution during this source batch: **NO**

**Production deploy: NO.**
