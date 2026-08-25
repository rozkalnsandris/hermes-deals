# Kaufland K3C promo-structure RPi5 bridge

Refs: #702, #741, #749, #758, #769, #772, #774, #775.

Runtime provisioning and verification details are authoritative in `docs/KAUFLAND_K3C_HASH_LOCKED_RUNTIME_RUNBOOK.md`.

## Purpose

This bridge exposes one owner-gated RPi5 execution path for the reviewed read-only Kaufland K3C promo-structure diagnostic. It inspects only the accepted retained K2 packet and exports bounded sanitized structural evidence.

It does **not** add a parser selector, promote `nur` to a public-promo role, fetch Kaufland over the network, write retained evidence, mutate production data, or deploy production.

Bridge contract: `kaufland-k3c-promo-structure-rpi5-bridge-v2`.

Diagnostic contract: `kaufland-k3c-promo-structure-diagnostic-v1`.

## Identity model

Three identities are now distinct and mandatory:

1. **registration SHA** — exact single-parent squash merge that introduces or updates **at least one** reviewed K3C bridge control-plane anchor: the workflow or installer;
2. **execution checkout SHA** — exact clean `main` commit already present on the RPi and explicitly selected for diagnostic execution;
3. **runtime identity SHA-256** — exact hash-locked K3C Python runtime built for the registration SHA and then registered root-owned.

The execution SHA may equal the registration SHA or be a descendant. The bridge never rewinds the primary checkout.

GitHub-hosted authorization also resolves current canonical `main` as an upper-bound/trusted-source witness. An unrelated docs-only descendant does not by itself require source sync, but any trusted K3C/runtime source drift blocks execution.

## Trusted source set

The following files form one reviewed execution boundary:

- `.github/workflows/kaufland-k3c-promo-structure-rpi5.yml`;
- `tools/runner/install-kaufland-k3c-promo-structure-rpi5-bridge.sh`;
- `tools/runner/kaufland_k3c_promo_structure_bridge_validator.py`;
- `backend/app/kaufland_k3c_promo_structure_diagnostic.py`;
- `backend/app/kaufland_real_k2_v2_derivation.py`;
- `backend/app/kaufland_evidence_freeze.py`;
- `backend/app/kaufland_source_card_contract.py`;
- `backend/app/kaufland_source_discovery.py`;
- `tools/runner/build-kaufland-k3c-python-runtime.sh`;
- `tools/runner/kaufland_k3c_python_runtime_contract.py`;
- `backend/locks/manifest.json`;
- `scripts/verify-python-lock-environment.py`;
- `backend/locks/runtime-py311.txt`;
- `backend/locks/runtime-py313.txt`.

A descendant execution checkout is accepted only while every trusted Git blob remains byte-identical to the registration SHA. The hosted authorizer additionally requires the same blobs on current GitHub `main` to remain byte-identical to registration. A changed trusted source therefore requires a new reviewed registration PR.

## GitHub-hosted authorization

The workflow remains `workflow_dispatch` only and accepts exactly:

1. merged K3C bridge registration PR number;
2. exact lowercase 40-hex execution SHA already present as clean RPi `main`.

Before a self-hosted job can start, the hosted authorizer requires:

- repository exactly `rozkalnsandris/hermes-deals`;
- workflow ref exactly `refs/heads/main`;
- allowlisted owner login and immutable numeric owner ID;
- same-repository PR merged into `main`;
- valid single-parent registration merge SHA;
- registration merge changed at least one reviewed K3C bridge control-plane anchor — workflow or installer — relative to its parent;
- ancestry `registration <= execution <= current GitHub main`;
- successful registration CI, either exact merge push CI or exact PR-head PR CI with squash-tree equivalence;
- successful exact execution `main` push CI when execution differs from registration;
- all trusted-source blobs equal between registration, execution and current-main witness.

No arbitrary path, command, module, retained root, shell fragment or ref is accepted from workflow input.

## Self-hosted diagnostic boundary

The RPi job retains:

- labels `self-hosted`, `Linux`, `ARM64`, `hermes-deals-audit`;
- `permissions: {}`;
- no `actions/checkout`;
- one fixed root-owned dispatcher.

Dispatcher interface:

```text
/usr/local/sbin/hermes-deals-kaufland-k3c-promo-structure-dispatch \
  <registration-sha> <execution-checkout-sha> <runner-artifact-dir>
```

The dispatcher does not fetch, switch, reset or mutate the source checkout.

## Runtime build is separate from root registration

The K3C Python runtime is no longer assumed to exist in host `/usr/bin/python3` application packages. Before root registration, an owner-authorized runtime-build step must create and verify a dedicated candidate:

```bash
bash tools/runner/build-kaufland-k3c-python-runtime.sh \
  <exact-registration-merge-sha>
```

This is a separate host/network package-install mutation. It uses only the repository-supported CPython 3.11/3.13 hash locks, `--require-hashes`, binary-only wheels, `pip check` and exact lock-inventory verification. It does not read retained evidence and does not execute the diagnostic.

See `docs/KAUFLAND_K3C_HASH_LOCKED_RUNTIME_RUNBOOK.md` for the full contract and failure semantics.

## Root registration boundary

Root registration remains a separate host mutation and requires separate exact owner authorization. Its current interface is **two arguments**:

```bash
sudo bash tools/runner/install-kaufland-k3c-promo-structure-rpi5-bridge.sh \
  <exact-registration-merge-sha> \
  <exact-runtime-candidate-dir>
```

The runtime candidate must resolve inside the fixed K3C cache allowlist:

`/home/andris/.cache/hermes-deals-kaufland-k3c-python-runtime/candidate-<runtime-identity-sha256>`

Before the first persistent write, the installer:

- verifies canonical clean `main`, origin, non-shallow state and registration ancestry;
- proves the registration SHA is single-parent and changed a bridge anchor;
- proves every trusted source at current HEAD equals registration;
- validates all trusted SHA-256 values;
- proves `github-runner` is not in the Docker group;
- validates the generated dispatcher and sudoers;
- runs the K3C runtime contract as unprivileged `andris` against the exact candidate;
- binds runtime identity, venv tree SHA, installed inventory SHA, Python line, selected lock SHA and Python binary SHA;
- requires candidate basename/identity equality and an unused destination identity.

Persistent registration then copies the exact preverified candidate into a unique root-owned runtime path under:

`/usr/local/libexec/hermes-deals-audits/kaufland-k3c-promo-structure/python-runtimes/`

The installer changes ownership to `root:root`, verifies consumer metadata, and reruns the complete runtime contract as `andris` against the installed copy **before** installing the bridge validator/config/dispatcher/sudoers.

Root registration performs no package installation, no Git fetch/source sync and no diagnostic execution. It checks only that the fixed retained root exists as a safe directory; it does not read the retained packet.

If registration fails after persistent writes begin, preserve evidence and STOP. No automatic retry, rollback, cleanup or alternate mutation path.

## Runtime fail-closed checks before every diagnostic

Before any application import, the dispatcher requires:

- supplied registration SHA equals the root-owned registered identity;
- exact local clean `main` HEAD equals supplied execution SHA;
- canonical origin and non-shallow checkout;
- registration SHA is an ancestor of execution SHA;
- every trusted source hash/blob equals the registered value;
- fixed retained root and runner artifact directory satisfy their allowlists;
- registered runtime path, receipt and Python metadata are root-owned and safe;
- full hash-locked runtime contract passes again as unprivileged `andris`;
- runtime identity/tree/inventory/Python/lock/binary values equal the root-owned config.

A missing runtime blocks as `DIAGNOSTIC_RUNTIME_UNAVAILABLE`. Any runtime identity/tree/inventory/interpreter/lock mismatch blocks as `DIAGNOSTIC_RUNTIME_IDENTITY_FAILED`.

Private runtime-verifier stderr never enters the exported artifact allowlist.

## Fixed diagnostic execution

Only after runtime verification succeeds does the dispatcher use the verified runtime `venv/bin/python` for all eight ordered import probes and the actual diagnostic.

The fixed import-stage reason codes remain:

1. `DIAGNOSTIC_IMPORT_BS4_FAILED`;
2. `DIAGNOSTIC_IMPORT_HTTPX_FAILED`;
3. `DIAGNOSTIC_IMPORT_SOURCE_CARD_CONTRACT_FAILED`;
4. `DIAGNOSTIC_IMPORT_SOURCE_DISCOVERY_FAILED`;
5. `DIAGNOSTIC_IMPORT_EVIDENCE_PREFLIGHT_FAILED`;
6. `DIAGNOSTIC_IMPORT_EVIDENCE_FREEZE_FAILED`;
7. `DIAGNOSTIC_IMPORT_K2_DERIVATION_FAILED`;
8. `DIAGNOSTIC_IMPORT_PROMO_MODULE_FAILED`.

Wrapper/cwd/runuser failures remain generic `DIAGNOSTIC_RUNTIME_IMPORT_FAILED`.

The application Python runs as unprivileged `andris` under a clean environment with `PYTHONDONTWRITEBYTECODE=1`, `PYTHONNOUSERSITE=1` and `PYTHONHASHSEED=0`.

The diagnostic dispatcher itself performs no package installation, venv creation, source mutation, host mutation or network fetch.

## Sanitization and receipt

The existing validator continues to validate the diagnostic under its reviewed v1 sanitizer contract. The outer dispatcher stamps bridge schema `2` and contract `kaufland-k3c-promo-structure-rpi5-bridge-v2` with both registration and execution SHA identities.

Raw diagnostic stdout, diagnostic stderr, import stderr and runtime-contract stderr remain private. Only validated diagnostic JSON, summary JSON and artifact manifest may be copied to the runner artifact directory.

`bridge_execution_status=PASS` means only that the fixed control plane and sanitizer completed. Nested `diagnostic_status=PASS` means deterministic structural inspection completed; `diagnostic_status=BLOCKED` is valid fail-closed semantic/evidence output. Neither status promotes `nur`.

## Required sequence after a future merge

Each mutation starts only after fresh canonical GitHub/runtime preflight and exact owner authorization:

1. source sync through the reviewed **source-sync bridge** to the exact reviewed merge SHA if required;
2. inspect source-sync receipt; failure/ambiguity -> STOP;
3. build the hash-locked K3C runtime candidate as `andris` for that exact merge SHA;
4. inspect exact candidate receipt/path; failure -> STOP, no cleanup/retry;
5. root-register the bridge with the same merge SHA **and exact candidate path**;
6. inspect registration receipt; failure -> STOP, no rollback/retry/cleanup;
7. separately authorize one-shot K3C diagnostic execution binding the merged registration PR and exact execution SHA;
8. review sanitized structural evidence against #702/#749 before any parser or promo-role change.

Source sync, runtime build, root registration and diagnostic execution are distinct live authority boundaries. Merge authorization implies none of them.

## Safety classification

- live Kaufland network fetch by diagnostic: **NO**
- runtime package download/install during separately authorized runtime build: **YES**
- package install during root registration: **NO**
- package install during diagnostic: **NO**
- retained evidence read during source/CI: **NO**
- retained evidence read during later authorized diagnostic: **YES**
- retained evidence write: **NO**
- parser #702 implementation: **NO**
- public-promo promotion: **NO**
- production DB/Review/publication write: **NO**
- scraper/runtime activation: **NO**
- Cloudflare/scheduler/systemd mutation: **NO**
- production deploy: **NO**

**Production deploy: NO.**
