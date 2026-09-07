# Netto missing-normal-price non-root preflight v2 — pull helper contract

This document defines the Hermes-owned source half of the runner-independent replacement for
`.github/workflows/netto-missing-normal-price-nonroot-preflight-v2.yml`.

## Capability

Capability: `netto-missing-normal-price-nonroot-preflight-v2`.

The future RPi5 control plane may invoke the installed helper with exactly one argument:

```text
/usr/local/libexec/hermes-deals-audits/netto-missing-normal-price-nonroot-preflight-v2/netto_missing_normal_price_nonroot_preflight_v2.py <registered-sha>
```

`<registered-sha>` is the only caller-supplied value. There is no caller-selected command,
path, argv extension, environment, output file, run ID, parser target, Docker target, URL,
query, or shell fragment.

## Immutable source and registration

The helper is fail-closed on a fixed registration file:

`/etc/hermes-deals-audits.d/netto-missing-normal-price-nonroot-preflight-v2.json`

The registration must be root-owned, group `root`, mode `0444`, and contain exactly:

- schema `rozkalns.hermes-deals.netto-nonroot-preflight-v2-registration.v1`;
- capability `netto-missing-normal-price-nonroot-preflight-v2`;
- exact merged/reachable Hermes Deals source SHA;
- exact installed helper SHA-256.

The installed helper itself is root-owned, group `root`, mode `0555`, at the exact fixed path
shown above. A future RPi5 operation must bind the exact Hermes repository, merged source SHA,
helper blob identity and expected helper SHA-256 before any canary can become eligible.

## Fixed read-only probe semantics

The helper preserves the workflow's exact fixed source observations:

- N9 manifest:
  `/home/andris/hermes-deals-audits/netto-n9-visual-cell-validation-pack-v1-20260802T202304Z/generated/fixture-manifest.json`
- N9 SHA-256:
  `2b180d67af4c5d1e586704088e3d685cff21ae2e12f3052254daf4553dd4e147`
- corpus root:
  `/home/andris/hermes-deals-netto-corpus/flyers`

It performs only readability, execute-bit, SHA-256 identity, and bounded stat metadata checks.
It never exports file contents and never invokes a parser.

The legacy workflow intentionally leaves the result blocked at
`campaign_identity_probe_required` even when the fixed paths are readable and hash-correct.
The runner-independent helper preserves that exact behavior; `non_root_ready` therefore remains
false in this v2 contract.

## Non-root trust boundary

The helper must execute as a non-root identity. `root execution is forbidden`.

Membership in the `docker` group is also rejected. `Docker-group authority is forbidden`.

The helper performs no sudo, subprocess, Docker, DB, Review, publication, deploy, scheduler,
credential, permission, runner-registration or host-root mutation. Output is canonical bounded
JSON written through a stdout-only interface; it creates no retained evidence path.

## Activation boundary

Merging this source contract does not authorize installation or execution. The legacy workflow remains unchanged.

Any registration-file creation, helper installation, user/group/permission change, RPi5 operation
binding, runtime invocation, retained evidence write, or genuine replacement canary requires the
separate exact `RPi5_main` source flow followed by explicit LIVE authorization under its current
repository policy.

Runner retirement remains out of scope until all required `hermes-deals-audit` capabilities have
proven replacements and the separate final retirement audit succeeds.
