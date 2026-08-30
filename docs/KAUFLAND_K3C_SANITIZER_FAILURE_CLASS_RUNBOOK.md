# Kaufland K3C bounded sanitizer failure classes

Refs: #798, #794, #795, #797, #749, #702.

## Purpose

This source-only runbook records the fail-closed observability contract for K3C promo-structure diagnostic output that reaches the reviewed diagnostic producer but is rejected by the bridge sanitizer.

It does **not** authorize diagnostic replay, retained-evidence access, runtime build, root registration, source sync, production writes or deploy.

## Triggering evidence

Owner-authorized workflow run `33316225473` executed registration/execution SHA `52099f37f323d1dd11b7dc4a493c85d8badcff14` after the post-#795 registration/runtime/root-registration sequence.

The hosted authorization job passed. The RPi dispatcher reached the diagnostic process, whose exit code was `0`, but the sanitizer failed closed and the exported summary reported:

- `bridge_execution_status=BLOCKED`;
- `diagnostic_status=UNAVAILABLE`;
- `reason_code=SANITIZED_OUTPUT_VALIDATION_FAILED`;
- dispatcher exit `30`.

The raw diagnostic stdout, diagnostic stderr and sanitizer implementation detail were intentionally not exported. Therefore run `33316225473` proves a sanitizer rejection but does **not** prove which field/value caused it and must not be reinterpreted as structural evidence.

## Bounded classifier contract

A sanitizer rejection may be reduced only to one fixed reason code selected by reviewed source. No exception text, raw HTML, product text, price value, locator value, filesystem path or arbitrary diagnostic content may be copied into the public artifact.

Current allowlisted classes are:

- `SANITIZER_PRICE_CLASS_REJECTED`;
- `SANITIZER_LOCATOR_REJECTED`;
- `SANITIZER_IDENTITY_REJECTED`;
- `SANITIZER_SCHEMA_REJECTED`;
- `SANITIZER_BOUND_REJECTED`;
- `SANITIZER_INPUT_READ_REJECTED`;
- `SANITIZER_OUTPUT_REJECTED` as the generic fallback.

The classifier does not relax any validator rule. A rejected raw payload is exported only as a bounded `diagnostic_status=BLOCKED` receipt with no structural projection. A `SANITIZER_*` reason is control-plane validation evidence, not proof of promo semantics and not acceptance for #702/#749.

Unknown or unclassified validation failures remain generic and fail closed.

## Trust-boundary consequence

`tools/runner/kaufland_k3c_promo_structure_bridge_validator.py` is in the K3C trusted-source set. Merging a change to it invalidates the prior registration/runtime chain for future diagnostic execution unless the exact merge itself also satisfies the registration-anchor rule by changing the reviewed K3C workflow or installer.

Therefore after #798 is reviewed and merged, do not reuse the #797 registration, runtime candidate, root registration or diagnostic authorization. Establish the next valid reviewed registration anchor, then follow the canonical sequence:

`source sync -> read-only host preflight -> runtime build -> root registration -> separately authorized diagnostic`

Every live step remains separately owner-authorized.

## Safety classification

- diagnostic replay in this source-only change: **NO**;
- retained evidence read/write: **NO / NO**;
- validator acceptance relaxation: **NO**;
- parser #702 implementation: **NO**;
- production DB/Review/publication write: **NO**;
- host/runtime/root mutation: **NO**;
- production deploy: **NO**.
