# Kaufland K3C promo-structure RPi5 bridge

Refs: #702, #749, #756, #757.

## Purpose

This bridge exposes exactly one owner-gated RPi5 execution path for the already reviewed read-only Kaufland K3C promo-structure diagnostic.

It does **not** add a parser selector, promote `nur` to a public-promo role, fetch Kaufland over the network, or write retained evidence. Its only purpose is to run the reviewed structural diagnostic against the accepted retained K2 packet and export bounded sanitized evidence through GitHub Actions.

Bridge contract:

`kaufland-k3c-promo-structure-rpi5-bridge-v1`

Diagnostic contract:

`kaufland-k3c-promo-structure-diagnostic-v1`

## Source components

- `.github/workflows/kaufland-k3c-promo-structure-rpi5.yml`
- `tools/runner/install-kaufland-k3c-promo-structure-rpi5-bridge.sh`
- `tools/runner/kaufland_k3c_promo_structure_bridge_validator.py`
- `backend/tests/test_kaufland_k3c_promo_structure_rpi5_bridge.py`

The diagnostic implementation remains:

- `backend/app/kaufland_k3c_promo_structure_diagnostic.py`

## Authorization model

The workflow is `workflow_dispatch` only.

The GitHub-hosted authorization job requires:

1. exact repository `rozkalnsandris/hermes-deals`;
2. workflow execution from `main`;
3. actor login `rozkalnsandris` **and** numeric owner ID `277435981`;
4. a positive merged PR number supplied only as a source-identity selector;
5. that PR must be a same-repository PR merged into `main`;
6. its merge SHA must be reachable from current `main`;
7. either successful exact merge-SHA push CI, or successful exact PR-head CI with tree identity equal to the squash-merge tree.

No path, command, retained root, Python module, shell fragment, or diagnostic option is accepted from the workflow event.

The self-hosted job has `permissions: {}` and performs no repository checkout. It receives only the authorized 40-character merge SHA and a runner-created private artifact directory, then invokes one fixed root-owned dispatcher:

```text
/usr/local/sbin/hermes-deals-kaufland-k3c-promo-structure-dispatch
```

The dispatcher itself accepts exactly:

```text
<registered-commit-sha> <runner-artifact-dir>
```

and validates both against the root-owned registration and the exact runner-temp path contract.

## Root registration boundary

The installer source is inert until separately executed on RPi5 after merge.

Registration is a **host mutation** and therefore requires separate explicit owner authorization. Merge does not authorize it.

The installer command, after the RPi source checkout has separately been synchronized to the exact merged bridge SHA, is:

```bash
sudo bash tools/runner/install-kaufland-k3c-promo-structure-rpi5-bridge.sh \
  <exact-merged-bridge-sha>
```

The installer requires `/home/andris/hermes-deals` to be:

- branch `main`;
- exact requested HEAD;
- clean including untracked files;
- bound to the exact Hermes Deals GitHub origin.

It installs only:

- one root-owned validator;
- one root-owned bridge config;
- one fixed root-owned dispatcher;
- one sudoers rule permitting `github-runner` to invoke that dispatcher only.

It records exact SHA-256 identities for the validator and the critical reviewed Kaufland diagnostic/helper source files. The dispatcher rechecks those hashes and the exact clean source checkout before every diagnostic run.

Registration does **not** execute the diagnostic and does not read the retained K2 packet beyond checking that the fixed retained root exists as a non-symlink directory.

A checkout synchronized only to an earlier source commit is not sufficient to register or run this bridge. Runtime and registration are intentionally bound to the exact merged bridge SHA that contains the reviewed bridge source.

## Fixed retained and runtime boundary

The dispatcher hardcodes:

- source checkout: `/home/andris/hermes-deals`;
- retained root: `/home/andris/hermes-deals-retained-evidence`;
- backend module: `app.kaufland_k3c_promo_structure_diagnostic`.

It runs the diagnostic as unprivileged user `andris` with:

- a clean environment;
- `PYTHONDONTWRITEBYTECODE=1` so importing the source cannot create `__pycache__` files in the checkout;
- `PYTHONHASHSEED=0`;
- the fixed retained-root argument only.

The source checkout HEAD/status are checked before and after execution. Any change fails closed.

The diagnostic itself continues to enforce:

- exact retained bundle identity;
- exact K2 verifier `NO_OP`;
- exact BeautifulSoup `4.15.0`;
- `html.parser`;
- process-local network guard;
- target fingerprint invariance;
- deterministic second derivation;
- no retained write and no live/runtime mutation flags.

## Sanitization boundary

Raw diagnostic stdout and private stderr remain only in the private RPi staging directory and are deleted before successful export. Raw stderr is never uploaded.

The root-owned validator accepts only the exact reviewed PASS or BLOCKED diagnostic schemas.

For PASS it additionally requires:

- `evidence_only=true`;
- `promo_role_promoted=false`;
- every write/deploy/runtime flag false;
- K2 verifier action `NO_OP` with exact accepted bundle identity and counts;
- unchanged target fingerprints;
- deterministic second derivation;
- exact projection/result identities;
- the exact structural projection field set;
- bounded marker/signature/candidate samples;
- only `rawpath:/...` locators;
- only `k-price*` structural classes;
- no unreviewed candidate field such as a price amount.

Any extra field, amount-value injection, identity mismatch, unsafe status/exit pairing, promotion claim, or output-bound violation is rejected fail-closed.

Only these files may be copied into the GitHub runner artifact directory:

- `kaufland-k3c-promo-structure-diagnostic.json` when validated diagnostic evidence exists;
- `kaufland-k3c-promo-structure-summary.json`;
- `artifact-manifest.json`.

## PASS and BLOCKED semantics

`bridge_execution_status=PASS` means only that the fixed dispatcher completed and the diagnostic output passed the sanitization contract.

The nested diagnostic may independently be:

- `diagnostic_status=PASS` — deterministic read-only structural inspection completed;
- `diagnostic_status=BLOCKED` — the reviewed diagnostic itself reached a bounded fail-closed evidence condition, for example parser-version or retained-identity drift.

A validated diagnostic `BLOCKED` remains useful evidence and does **not** become a bridge infrastructure failure. It never promotes public-promo semantics.

Dispatcher/registration/source/sanitizer failures are reported as bridge `BLOCKED` and the workflow fails closed.

## Required sequence after source merge

Each current state must be freshly rechecked before mutation or execution.

1. Verify exact current GitHub `main`, merged bridge SHA, CI and review state.
2. Obtain separate owner authorization for any RPi source checkout synchronization needed to reach that exact bridge SHA.
3. Obtain separate owner authorization for root registration/installer execution.
4. Verify registration receipt; if it fails or is ambiguous, preserve evidence and STOP without retry/rollback/alternate mutation.
5. Run the manual owner-gated workflow for the exact merged bridge PR only when the read-only diagnostic execution is authorized.
6. Review the sanitized structural artifact before any change to public-promo semantics or #702 parser behavior.

No automatic retry is part of this bridge.

## Safety classification

- live Kaufland network fetch: **NO**
- retained evidence read during source/CI: **NO**
- retained evidence read during later authorized diagnostic: **YES**
- retained evidence write: **NO**
- parser #702 implementation: **NO**
- public-promo promotion: **NO**
- production DB write: **NO**
- Review write: **NO**
- publication write: **NO**
- production deploy: **NO**
- scraper/runtime activation: **NO**
- Cloudflare mutation: **NO**
- scheduler/systemd change by diagnostic: **NO**
- source checkout sync during this source batch: **NO**
- root registration during this source batch: **NO**

**Production deploy: NO.**
