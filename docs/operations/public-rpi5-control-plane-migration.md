# Public-repository RPi5 control-plane migration

Tracking issue: #384.

## Scope of this contract

This document freezes the current public-repository self-hosted execution surface and defines the source-only migration architecture. It does **not** migrate, register, deregister, install, enable, restart, deploy, or mutate any RPi5/runtime/production component.

The machine-readable inventory is `policy/public-rpi5-control-plane-v1.json`. The inventory baseline is `aa86c956ed2f487e0c8223eab6e8d7224cea7f8f`.

## Current baseline

The current public-workflow safety audit reports:

| Metric | Current baseline |
| --- | ---: |
| Workflow files | 79 |
| Workflows containing self-hosted jobs | 52 |
| Direct `pull_request` self-hosted paths | 0 |
| `pull_request_target` self-hosted paths | 10 |
| `issue_comment` self-hosted paths | 22 |
| Union requiring manual public-trigger review | 32 |
| Mutable external Actions used from self-hosted jobs | 0 |

The issue was opened when the reviewed surface was 27 workflows / 23 self-hosted workflows. The current surface is materially larger, so the migration must use the current 52-workflow inventory rather than the historical issue-body count.

Two persistent runner trust labels are relevant to the migration architecture:

- `hermes-deals-audit` — audit/diagnostic and several narrowly controlled operational paths;
- `hermes-deals-release` — production release/cutover and production smoke paths.

A runner label is **not** an authority classification. For example, EDEKA production canary control currently runs on `hermes-deals-audit` but its fixed dispatcher is a production-capable authority boundary. Migration grouping therefore follows operation capability, not label name alone.

## Capability inventory

The policy file lists all 52 current self-hosted workflow paths exactly once. The planning groups are:

| Capability | Count | Replacement class |
| --- | ---: | --- |
| `read_only_retailer_audit` | 29 | narrow RPi5 pull/read-only operation |
| `diagnostic` | 11 | narrow RPi5 pull/read-only operation |
| `owner_finalizer_bootstrap` | 6 | separately gated narrow host/finalizer operation |
| `production_release` | 5 | separately gated release authority |
| `scheduled_unattended` | 1 | local/scheduled pull model with no public-event command surface |

These are migration-planning classes, not new permissions. Existing repository-local and root-helper restrictions remain authoritative.

## Why one universal agent is rejected

The replacement must not turn 52 reviewed entrypoints into one generic privileged command executor. A universal shell/argv bridge would collapse existing trust separation and make a single credential or parser bug equivalent to arbitrary host execution.

The replacement model is therefore capability-scoped:

1. **Hosted authorization / state validation** remains on GitHub-hosted infrastructure where practical. It validates immutable owner identity, exact merged/reachable SHA and required CI state.
2. **RPi5 pull selection** consumes only a narrow operation identifier plus immutable arguments. Public/fork-controlled text is never executable input.
3. **Static operation adapters** map the operation identifier to one reviewed command contract. No shell text, arbitrary executable path or arbitrary argv expansion is accepted.
4. **Privilege remains behind fixed helpers/dispatchers.** A pull worker is not granted generic root authority.
5. **Audit and release authority remain separate.** A read-only worker credential cannot select production release operations.
6. **Result publication is non-authority.** Reporting failure cannot cause replay and must not expand authorization-reader rights.
7. **Persistent repository runners stay registered until replacement evidence exists.** Deregistration is a later explicit live mutation, not part of source migration PRs.

## Scheduled/unattended exception

`netto-weekly-transition-state.yml` is intentionally a separate class. Its self-hosted job checks out the current default-branch commit and performs bounded source acquisition directly as the non-root runner user. It is not equivalent to the fixed-dispatcher read-only audit canary and must not be migrated by mechanically copying the canary adapter.

Scheduled work should ultimately use a local scheduled/pull contract whose inputs are fixed by source-controlled policy. It must not manufacture an owner LIVE authorization for every cron tick, and public events must not be able to alter the executable operation.

## Canary: `origin-path-rpi5-audit`

The first migration candidate is `.github/workflows/origin-path-rpi5-audit.yml`.

Current narrow contract:

- GitHub-hosted authorizer validates the owner and a merged/reachable PR SHA;
- RPi5 job label: `hermes-deals-audit`;
- RPi5 workflow does not checkout repository source;
- privileged entrypoint is fixed to `/usr/local/sbin/hermes-deals-origin-path-audit-dispatch`;
- dispatcher validates registered SHA/hash/path constraints;
- the probe executes as the non-root `andris` user;
- evidence is sanitized;
- production DB write, production deploy, restart and configuration mutation remain false/not authorized.

This canary is preferred over `cloudflare-ingress-rpi5-audit.yml`, whose collector remains a root-context runtime/config inventory operation, and over production/release paths, whose blast radius is larger.

## Canary source acceptance contract

A future canary implementation PR must prove, before any host activation:

1. the public repository no longer needs a persistent self-hosted runner to request this one operation;
2. only the exact static `origin-path` operation can be selected;
3. owner identity and exact merged/reachable SHA validation are preserved;
4. no untrusted PR/head checkout reaches RPi5;
5. no arbitrary shell, executable path or free-form argv crosses the boundary;
6. the fixed root-owned dispatcher remains the only privileged entrypoint;
7. the result stays read-only, sanitized and non-promotable;
8. duplicate/replayed authorization is rejected or safely no-op according to the chosen pull protocol;
9. reporting failure cannot cause a second execution;
10. regression tests demonstrate that public issue/PR content cannot select arbitrary RPi5 execution.

Only after the source contract is reviewed and merged may a separate explicit owner live authorization install/register/activate the canary-side host component.

## Migration sequence

1. **Inventory/architecture contract** — this source-only change.
2. **Canary source implementation** — one narrow `origin-path` pull adapter and adversarial tests; no host activation.
3. **Canary live activation** — separate explicit owner authorization for the exact RPi5 host mutation.
4. **End-to-end evidence** — prove exact-SHA authorization, single execution, sanitized result and no persistent-runner dependency for the canary.
5. **Incremental capability migration** — read-only audit/diagnostic paths first, then separately reviewed finalizer/bootstrap and scheduled paths, production release last.
6. **Runner deregistration** — only after every required capability has a proven replacement; separate explicit owner live authorization.
7. **Final audit** — repository runner count 0, or an explicitly accepted narrowly justified residual runner.

## Explicit exclusions

This contract does not authorize or perform:

- runner registration/deregistration;
- systemd/timer/sudoers/package changes;
- credential, token, GitHub App or secret changes;
- production DB/Review/publication writes;
- production deploy/cutover;
- Cloudflare mutation;
- parser/collector behavior changes;
- retained-evidence promotion;
- B15M2 V08 changes.

## Regression lock

`backend/tests/test_public_rpi5_control_plane_policy.py` fails if the current self-hosted workflow set drifts away from the 52-path manifest. It also locks the selected canary to the current `hermes-deals-audit` label, fixed dispatcher and no-workflow-checkout boundary.

The existing `scripts/audit-public-workflow-safety.py` remains the authoritative runtime-independent safety audit for trigger classification and immutable external Action references. The migration contract complements it; it does not replace it.
