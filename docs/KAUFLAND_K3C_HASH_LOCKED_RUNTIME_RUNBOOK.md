# Kaufland K3C hash-locked Python runtime

Refs: #702, #741, #749, #769, #772, #774, #775, #780, #785.

## Purpose

The K3C retained-evidence diagnostic must not depend on unverified application packages from the RPi system interpreter or user site-packages. The runtime is therefore provisioned from one reviewed self-contained CPython artifact, populated from repository hash locks, verified independently, registered as a root-owned immutable runtime, and only then consumed by the diagnostic dispatcher.

This runbook does **not** authorize any live action. Runtime build, root registration, source sync and diagnostic execution remain owner-authorized live boundaries. Merge authorization does not authorize them.

The runtime contract is:

`kaufland-k3c-hash-locked-python-runtime-v2`

## Canonical Python contract

Hermes application, CI dependency verification and new K3C runtime candidates use one active interpreter line: **CPython 3.13**. K3C runtime v2 pins exact CPython **3.13.14** for Linux `aarch64` without replacing Debian Bookworm `/usr/bin/python3`.

`/usr/bin/python3` is control-plane only. It validates repository metadata, the bootstrap manifest, archive structure and runtime receipts. It may remain Debian's CPython 3.11. K3C application imports and diagnostic execution use only the isolated bootstrapped interpreter at:

`python/bin/python3.13`

The active locks recorded in `backend/locks/manifest.json` are:

- `backend/locks/runtime-py313.txt`;
- `backend/locks/ci-py313.txt`.

Older `py311` lock files may remain in Git history or as conservative provenance witnesses. They are not active manifest entries and cannot be selected by the K3C builder or runtime contract.

## Pinned bootstrap artifact

The reviewed bootstrap manifest is `tools/runner/kaufland-k3c-python-bootstrap.json`.

It pins one immutable `astral-sh/python-build-standalone` release and asset:

- release tag: `20260805`;
- release ID: `365709887`;
- target commit: `76b41240bc8dfe753a54b2e32c8941e536568be8`;
- immutable release: `true`;
- asset ID: `502923386`;
- asset name: `cpython-3.13.14+20260805-aarch64-unknown-linux-gnu-install_only.tar.gz`;
- asset size: `89958991` bytes;
- asset SHA-256: `4777d7df2edb47b96e53abad5e1b9df1b2a1a9b2f7bdba12b5c0122163b3fed9`;
- expected runtime executable: `python/bin/python3.13`.

The builder verifies exact platform, manifest identity, byte size and SHA-256 before extraction. There is no unpinned release lookup or alternate artifact fallback.

## Source trust boundary

The active K3C runtime boundary includes:

- `tools/runner/build-kaufland-k3c-python-runtime.sh`;
- `tools/runner/kaufland_k3c_python_runtime_contract.py`;
- `tools/runner/kaufland-k3c-python-bootstrap.json`;
- `backend/locks/manifest.json`;
- `scripts/verify-python-lock-environment.py`;
- `backend/locks/runtime-py313.txt`.

Any drift between the reviewed registration SHA and current source for an active runtime trust source fails closed. Bootstrap manifest SHA and pinned asset identity are also part of the runtime identity and candidate receipt.

## Safe extraction contract

The archive is inspected in full before extraction. The runtime contract accepts only a bounded, previously absent `python/` tree and fails closed on:

- absolute paths;
- `..` path traversal;
- non-canonical paths;
- unexpected top-level paths outside `python/`;
- duplicate member paths;
- a pre-existing destination `python/` tree;
- device entries and FIFOs;
- hardlinks;
- unsupported member types;
- absolute symlinks;
- symlinks that resolve outside the extracted `python/` tree;
- any archive member nested below another archive member that is a symlink, independent of tar member order.

The builder extracts a self-contained runtime tree. It does **not** create a PEP 405 venv from the host interpreter or from a temporary prefix.

## Runtime build boundary

The builder interface remains:

```bash
bash tools/runner/build-kaufland-k3c-python-runtime.sh \
  <exact-registration-merge-sha>
```

It must run as unprivileged `andris` from the canonical clean `main` checkout. Preflight requires Linux `aarch64`, registration ancestry, canonical repository origin, clean source state and byte-identical active trust sources between registration SHA and current HEAD.

Only after preflight may it create a K3C-specific candidate under:

`/home/andris/.cache/hermes-deals-kaufland-k3c-python-runtime/candidate-<runtime-identity-sha256>`

A future execution of this builder is a **host/network mutation** and requires exact owner authorization. It downloads only the pinned bootstrap asset into K3C staging, validates exact size and SHA-256, safely extracts it, and then installs dependencies with:

- clean environment and `PIP_CONFIG_FILE=/dev/null`;
- `pip install --require-hashes --only-binary=:all: --no-cache-dir`;
- exactly `backend/locks/runtime-py313.txt`;
- `pip check`;
- exact installed-distribution verification with `scripts/verify-python-lock-environment.py`;
- explicit `bs4` and `httpx` import verification.

The builder does not read retained evidence and does not execute the K3C diagnostic.

Before candidate identity is finalized, runtime permissions are normalized and a deterministic SHA-256 is calculated over the `python/` tree, including path, type, mode, content and bounded symlink targets.

The candidate receipt binds registration SHA, runtime identity, exact CPython implementation/version/line, relative executable path, Python binary SHA-256, bootstrap manifest SHA, bootstrap asset ID/name/size/SHA, selected dependency lock and SHA, installed inventory, runtime tree, lock manifest, verifier, provisioner and runtime-contract identities. Diagnostic execution, retained reads/writes, production DB writes and production deploy flags remain explicitly false.

The staging directory is atomically renamed to its final candidate identity. The contract is then rerun against the **final path** and requires the interpreter to report the exact relocated `sys.executable` and `sys.prefix`. Failure after mutation starts preserves the reported evidence path and requires STOP; no automatic retry, cleanup or alternate interpreter path is authorized.

## Root registration boundary

Only a previously built and verified candidate may be registered. The installer interface remains:

```bash
sudo bash tools/runner/install-kaufland-k3c-promo-structure-rpi5-bridge.sh \
  <exact-registration-merge-sha> \
  <exact-runtime-candidate-dir>
```

Root registration is a separate **host mutation** and requires separate exact owner authorization. It performs no package installation and no diagnostic execution. The installer verifies the runtime contract before the first persistent write and again after copying the runtime into the root-owned registration path.

The root-owned registered interpreter is exactly:

`<registered-runtime>/python/bin/python3.13`

Bootstrap manifest source SHA and asset SHA are stored in the bridge configuration and rechecked by the dispatcher together with the runtime identity/tree/inventory/lock/Python binary identities.

If registration fails after persistent writes begin, preserve evidence and STOP. No retry, rollback, cleanup or alternate registration path is authorized automatically.

## Diagnostic execution boundary

The registered dispatcher never downloads Python, creates a venv or runs package-install commands. It verifies source identity and the registered runtime contract before any staged application import, then uses only the exact verified `python/bin/python3.13` for imports and diagnostic execution.

Missing runtime fails closed as `DIAGNOSTIC_RUNTIME_UNAVAILABLE`. Runtime source/bootstrap/identity/tree/inventory/interpreter/lock verification failure fails closed as `DIAGNOSTIC_RUNTIME_IDENTITY_FAILED`.

Diagnostic execution remains a separate owner-authorized retained-evidence read/runtime boundary. A diagnostic authorization does not authorize package installation, runtime rebuild, root registration, source sync or any other host mutation.

## Required post-merge live sequence

After a future source merge, collect fresh GitHub and runtime evidence before each mutation. Do not reuse prior K3C runtime-build or registration authorization after runtime trust-source code changes.

The intended sequence is:

1. establish a reviewed registration SHA whose K3C control-plane/runtime trust sources match the intended execution source;
2. source-sync the trusted RPi5 checkout to that reviewed SHA if required — separate exact owner authorization;
3. read-only preflight verifies Linux `aarch64`, clean canonical checkout and the distribution-managed control-plane Python; Debian Bookworm `/usr/bin/python3` does **not** need to be 3.13;
4. build one K3C runtime candidate as `andris` — separate exact owner authorization;
5. inspect the immutable candidate receipt and exact candidate path; failure/ambiguity -> STOP;
6. root-register that exact candidate — separate exact owner authorization;
7. inspect registration receipt; failure/ambiguity -> STOP;
8. execute one K3C diagnostic only under separate exact authorization;
9. review sanitized structural evidence against #702/#749 acceptance.

No step implicitly authorizes the next one.

## Semantic boundary

This runtime remediation changes dependency/runtime assurance only. It does not promote `nur`, create a public-promo receipt, permit numeric/proximity/ordering inference, modify Kaufland parser semantics, authorize #702 parser acceptance, write retained evidence, write production DB/Review/publication state, or deploy production.

**Production deploy: NO.**
