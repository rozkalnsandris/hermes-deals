# ALDI new-baseline weekly-shadow execution/evidence bridge

Issue: #682

## Purpose

This bridge is the owner-gated transition from the source-only Gate A/B/C contracts to
**one real weekly shadow evidence family at a time**. It does not reconstruct historical
A3.0/A3.1 evidence and never changes the open/historically-incomplete status of #56.

The bridge reuses, rather than reimplements:

1. `aldi_new_immutable_baseline_gate.py` (Gate A);
2. `aldi_new_baseline_page_card_parity.py` (Gate B);
3. `aldi_new_baseline_gate_c_replay.py` (Gate C);
4. `aldi_new_baseline_two_cycle_shadow_gate.py` (#686 acceptance).

A first accepted real weekly family produces `WEEKLY_SHADOW_EVIDENCE_ACCEPTED`.
A second distinct consecutive family may reach `READY_FOR_PRODUCTION_CANARY_PLAN` only
through the existing #686 validator. That result still does **not** authorize canary
application or deployment.

## Source-only status

Adding these files to GitHub does not activate anything on RPi5.

After merge, installing the root-owned dispatcher is a separate owner authorization.
Every real weekly request is then separately owner-authorized by an exact #682 comment:

`/hermes-aldi-new-baseline-weekly-shadow request=<sha256>`

There is no `schedule:` trigger and no retry loop.

## Immutable request ingress

The root dispatcher accepts only one lowercase SHA256, exact main SHA, authorization
comment id and GitHub run id from the workflow. The SHA selects the fixed root-owned
directory:

`/var/lib/hermes-deals/aldi-new-baseline-weekly-shadow-v01/requests/<sha256>/`

`request.json` itself must hash to the authorized SHA. The request describes fixed-name
metadata files and their exact hashes:

- `gate-a-input.json`
- `gate-b-input.json`
- `gate-c-input.json`
- `execution-evidence.json`
- optionally, and only together for week two:
  - `prior-cycle.json`
  - `observability-proofs.json`

The ingress is metadata/evidence only. The bridge never accepts an arbitrary path from
GitHub, never exports raw page bytes, credentials, tokens, or private keys, and rejects
symlinks, non-root-owned ingress, group/world-writable ingress, hash drift and main
drift.

## Real-execution evidence requirement

`execution-evidence.json` must explicitly attest a real RPi5 shadow observation and is
cross-bound to the exact Gate A source/campaign and Gate B/Gate C identities. It must
prove:

- `evidence_class=real_weekly_shadow`;
- `execution_origin=rpi5_shadow`;
- source state `available`;
- exact ISO week and one Gate A official source identity;
- immutable evidence;
- exact replay is a no-op;
- zero duplicate/new candidates and zero immutable payload drift;
- shadow state SHA before == after;
- `review_pending_count=0`;
- production DB writes = 0;
- Review writes = 0;
- publication writes = 0;
- source mutation writes = 0;
- production published/eligible = false.

The bridge cannot turn a unit-test fixture into real execution: a request must contain
the immutable root-owned real-run evidence and an owner comment must authorize that
exact request SHA.

## Cross-gate binding

The bridge independently recomputes the expected binding between each existing
contract:

- Gate B input must exactly bind the Gate A result;
- Gate C input must exactly bind the Gate B result;
- current cycle source/page/parser/candidate/card/semantic identities are taken only
  from the validated outputs;
- parity contract identity is the exact installed Gate B implementation SHA.

Any mismatch fails closed.

## Two-cycle boundary

For week one, the sanitized artifact contains the current cycle evidence but cannot
claim the two-cycle acceptance result.

For week two, `prior-cycle.json` and all six immutable observability proofs must be
present together. The bridge relabels the immutable ordered evidence as cycle-01 and
cycle-02 and delegates all consecutive-week, distinct identity, stable parser/parity,
replay no-op, zero-write, observability and acceptance checks to #686.

If the parser implementation or parity contract changes, #686 fails closed and the
two-cycle acceptance window must restart.

## Sanitized artifact

The RPi5 dispatcher exports only canonical metadata JSON plus `MANIFEST.sha256`:

- Gate A result;
- Gate B result;
- Gate C result;
- current cycle evidence;
- optional two-cycle result;
- sanitized bridge result.

The dispatcher rejects unexpected members, symlinks, oversized metadata and
secret-like names/content before copying evidence into `RUNNER_TEMP`.

## Safety boundary

This bridge grants no authority for:

- production DB writes;
- Review/publication writes;
- source/corpus mutation;
- automatic approval/publication;
- scheduler/systemd/timer activation;
- production deploy;
- production canary application;
- historical #56 reconstruction or relabeling.

`READY_FOR_PRODUCTION_CANARY_PLAN` means only that the existing two-cycle validator has
accepted two distinct consecutive real weekly families. Canary-plan preparation and
canary application remain separate owner-gated boundaries.

## Host registration boundary

`tools/runner/install-aldi-new-baseline-weekly-shadow-dispatcher.sh` is intentionally
source-only in this PR. When separately authorized after merge, it:

- requires exact clean `main` at the merged SHA;
- installs the bridge and all four reused validators as root-owned immutable files;
- binds their SHA256 values in `/etc/hermes-deals-audits.d`;
- creates only the root-owned request ingress;
- grants the `github-runner` account sudo access only to the fixed dispatcher;
- verifies the audit runner is active and not in the `docker` group.

Running this installer is **not** part of the source PR and is not authorized by a
generic “continue”.
