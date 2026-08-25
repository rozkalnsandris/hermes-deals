# Kaufland K3C hash-locked Python runtime

Refs: #702, #741, #749, #769, #772, #774, #775.

## Purpose

The K3C retained-evidence diagnostic must not depend on unverified application packages from the RPi system interpreter or user site-packages. The runtime is therefore provisioned as a dedicated K3C venv from repository hash locks, verified independently, registered as a root-owned immutable runtime, and only then consumed by the diagnostic dispatcher.

This runbook does **not** authorize any live action. Runtime build, root registration, source sync and diagnostic execution remain owner-authorized live boundaries. Merge authorization does not authorize them.

The runtime contract is:

`kaufland-k3c-hash-locked-python-runtime-v1`

## Source trust boundary

The reviewed K3C runtime boundary includes:

- `tools/runner/build-kaufland-k3c-python-runtime.sh`;
- `tools/runner/kaufland_k3c_python_runtime_contract.py`;
- `backend/locks/manifest.json`;
- `scripts/verify-python-lock-environment.py`;
- `backend/locks/runtime-py311.txt`;
- `backend/locks/runtime-py313.txt`.

The K3C bridge workflow and installer bind these files together with the existing K3C workflow, validator, diagnostic and retained-evidence helpers. Any drift between registration SHA, execution SHA or current-main witness blocks diagnostic execution.

## Supported interpreter and lock selection

The builder uses only `/usr/bin/python3` as the bootstrap interpreter and accepts only repository-supported CPython lines:

- CPython 3.11 -> `backend/locks/runtime-py311.txt`;
- CPython 3.13 -> `backend/locks/runtime-py313.txt`.

The selected lock filename, Python line and SHA-256 must match `backend/locks/manifest.json`. Any other Python implementation or major/minor line fails closed. No alternate interpreter or unlocked fallback is allowed.

## Runtime build boundary

The builder is:

```bash
bash tools/runner/build-kaufland-k3c-python-runtime.sh \
  <exact-registration-merge-sha>
```

It must run as the unprivileged `andris` user from the canonical clean `main` checkout. It verifies that the registration merge is available and is an ancestor of current HEAD and that every runtime trust source is byte-identical between registration SHA and current HEAD.

The builder then creates one K3C-specific candidate under:

`/home/andris/.cache/hermes-deals-kaufland-k3c-python-runtime/candidate-<runtime-identity-sha256>`

This step is a **host mutation and network package-install mutation**. It therefore requires exact owner authorization before execution.

Dependency installation is restricted to:

- a fresh venv created with `/usr/bin/python3 -m venv --copies`;
- clean environment and `PIP_CONFIG_FILE=/dev/null`;
- `pip install --require-hashes --only-binary=:all: --no-cache-dir`;
- exactly the selected repository runtime lock;
- `pip check`;
- exact installed-distribution verification with `scripts/verify-python-lock-environment.py`;
- explicit `bs4` and `httpx` import verification.

The builder does not read retained evidence and does not execute the K3C diagnostic.

Before candidate identity is finalized, venv permissions are normalized and a deterministic tree SHA-256 is calculated over path, type, mode and content. Relative symlinks must stay inside the venv root. Absolute or escaping symlinks and unsupported filesystem entry types fail closed.

The candidate receipt binds:

- registration SHA;
- runtime identity SHA-256;
- CPython implementation/version/line;
- Python binary SHA-256;
- selected lock path and SHA-256;
- installed inventory SHA-256;
- venv tree SHA-256;
- lock manifest SHA-256;
- lock verifier SHA-256;
- provisioner SHA-256;
- runtime-contract verifier SHA-256;
- explicit false flags for diagnostic execution, retained reads/writes, production DB writes and production deploy.

After staging is moved to the final candidate path, the contract verifier re-verifies the final candidate before the builder can report PASS.

If runtime build fails after mutation starts, preserve the reported evidence path and **STOP**. Do not retry, clean up, rebuild with another interpreter, install packages manually or take an alternate mutation path without fresh owner authorization.

## Root registration boundary

Only a previously built and verified candidate may be registered. The installer interface is:

```bash
sudo bash tools/runner/install-kaufland-k3c-promo-structure-rpi5-bridge.sh \
  <exact-registration-merge-sha> \
  <exact-runtime-candidate-dir>
```

Root registration is a separate **host mutation** and requires separate exact owner authorization. It performs no package installation and no diagnostic execution.

Before the first persistent write, the installer:

1. validates the canonical clean source checkout and registration ancestry;
2. validates the candidate path against the fixed K3C cache allowlist;
3. verifies all K3C and runtime trusted-source blobs against the registration SHA;
4. runs the runtime contract as unprivileged `andris` against the candidate;
5. binds the exact runtime identity, tree, inventory, Python line, lock and Python binary SHA values;
6. requires the candidate basename to equal `candidate-<runtime-identity-sha256>`;
7. requires that the destination identity has not already been registered.

Persistent registration copies the exact candidate to:

`/usr/local/libexec/hermes-deals-audits/kaufland-k3c-promo-structure/python-runtimes/runtime-<runtime-identity-sha256>`

The copied runtime becomes `root:root`; the venv remains world-readable/executable but not writable by `andris`. The installer reruns the full contract as `andris` against the root-owned copy before installing the bridge config/dispatcher/sudoers files.

Registration output explicitly records that package installation and diagnostic execution were not performed.

If registration fails after persistent writes begin, preserve evidence and **STOP**. No retry, rollback, cleanup or alternate registration path is authorized automatically.

## Diagnostic execution boundary

The registered dispatcher never creates a venv and never runs package-install commands. Before the first staged application import it:

1. validates source checkout and trusted K3C/runtime blobs;
2. requires the configured root-owned runtime identity path and metadata;
3. reruns `kaufland_k3c_python_runtime_contract.py verify` as unprivileged `andris`;
4. requires every reported runtime identity field to equal the root-owned registered config;
5. keeps runtime-contract stderr private and outside the artifact export allowlist.

Missing runtime fails closed as `DIAGNOSTIC_RUNTIME_UNAVAILABLE`. Runtime identity/tree/inventory/interpreter/lock verification failure fails closed as `DIAGNOSTIC_RUNTIME_IDENTITY_FAILED`.

Only after runtime verification succeeds does the dispatcher use the verified `venv/bin/python` for the ordered import stages:

1. `bs4` -> `DIAGNOSTIC_IMPORT_BS4_FAILED`;
2. `httpx` -> `DIAGNOSTIC_IMPORT_HTTPX_FAILED`;
3. `app.kaufland_source_card_contract` -> `DIAGNOSTIC_IMPORT_SOURCE_CARD_CONTRACT_FAILED`;
4. `app.kaufland_source_discovery` -> `DIAGNOSTIC_IMPORT_SOURCE_DISCOVERY_FAILED`;
5. `app.kaufland_evidence_preflight` -> `DIAGNOSTIC_IMPORT_EVIDENCE_PREFLIGHT_FAILED`;
6. `app.kaufland_evidence_freeze` -> `DIAGNOSTIC_IMPORT_EVIDENCE_FREEZE_FAILED`;
7. `app.kaufland_real_k2_v2_derivation` -> `DIAGNOSTIC_IMPORT_K2_DERIVATION_FAILED`;
8. `app.kaufland_k3c_promo_structure_diagnostic` -> `DIAGNOSTIC_IMPORT_PROMO_MODULE_FAILED`.

The same verified venv Python executes the actual diagnostic. The existing clean environment remains in force: `PYTHONDONTWRITEBYTECODE=1`, `PYTHONNOUSERSITE=1`, `PYTHONHASHSEED=0`.

Diagnostic execution remains a separate owner-authorized retained-evidence read/runtime boundary. A diagnostic authorization does not authorize package installation, runtime rebuild, root registration, source sync or any other host mutation.

## Required post-merge live sequence

After a future source merge, collect fresh GitHub and runtime evidence before each mutation. The intended sequence is:

1. **RPi source sync** to the exact reviewed merge SHA, if required — separate exact owner authorization.
2. Inspect source-sync receipt. Any failure/ambiguity after mutation begins -> preserve evidence and STOP.
3. **K3C runtime build** as `andris` for the exact merge SHA — separate exact owner authorization for the bounded K3C host/network package-install mutation.
4. Inspect the immutable candidate receipt and exact candidate path. Failure -> STOP; no cleanup/retry.
5. **K3C root registration** using the same merge SHA and exact candidate path — separate exact owner authorization for host mutation. No package install and no diagnostic in this step.
6. Inspect registration receipt. Failure -> STOP; no rollback/retry/cleanup.
7. **One-shot K3C diagnostic** through `Kaufland K3C promo structure RPi5 diagnostic`, binding the merged registration PR and exact execution SHA — separate exact owner authorization.
8. Review only sanitized structural evidence against #702/#749 acceptance. Diagnostic PASS or semantic BLOCKED is not, by itself, proof that `nur` is a public-promo role.

No step implicitly authorizes the next one.

## Semantic boundary

This runtime remediation changes dependency/runtime assurance only. It does not:

- promote `nur`;
- create a public-promo receipt;
- permit numeric, proximity or ordering inference;
- modify Kaufland parser semantics;
- authorize #702 parser acceptance;
- write retained evidence;
- write production DB/Review/publication state;
- deploy production.

**Production deploy: NO.**
