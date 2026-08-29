# FAST-LANE v2.2 Composite — Hermes Deals

This is the active local FAST-LANE startup contract. The older versioned filename is retained only for backward compatibility and is not startup authority.

## Core rule

**The human approves the RISK / DECISION. Automation executes the TECHNICAL STEPS.** STRICT describes mutation risk, not the number of approval prompts. Read-only checkpoints do not create owner gates.

## Command routing invariant

Bare `START`, `START hermes-deals`, `turpini`, or equivalent continuation selects normal **FAST-LANE v2.2** operation. It does **not** select `GITHUB-ONLY`.

`GITHUB-ONLY` is active only when the owner explicitly includes `GITHUB-ONLY` in the current command, including the documented `git hub only` spelling. `LIVE-ALL` likewise requires an explicit current-command `LIVE-ALL` token.

Never infer either explicit mode from `.github/start-github-only.json`, deploy-queue state, handoff/issue continuity, executor availability, historical chat state, or a prior authorization receipt. Those are state/evidence inputs after command mode has been selected; they are not mode selectors. The machine-readable local dispatcher contract is `.github/start-mode-routing.json`.

## FAST source envelope

`START`, `turpini`, or an equivalent continuation instruction may carry safe source work from fresh canonical GitHub state through Ready: branch, implementation, focused tests, commit/push, Draft PR, CI/review and up to two scope-preserving corrective commits. Batch 2-5 closely related same-risk items when they form one acceptance story. Merge remains explicit.

## Human gate budget

Normal delivery has at most two owner gates: **MERGE**, then **COMPOSITE LIVE** only if live work is actually required. CI polling, diff inspection, GET/preflight, evidence refresh, checkout discovery, build preparation, candidate verification and reconciliation are automation steps.

## Composite STRICT

One live authorization may cover the tightly coupled operations required for one bounded rollout when it binds the exact Git SHA, exact target, allowed mutation categories, hard limits, explicit exclusions and expected baseline. All obtainable read-only evidence is collected before asking. Preflight is the first part of the same fail-closed one-shot, not a separate owner session.

Revalidate approved SHA/target/baseline immediately before the first live write and again where drift matters. If another actor changed the target, STOP. Where artifacts/versions apply: pin tooling, build once, verify the exact candidate and deploy that exact artifact/version.

## Local STRICT boundaries

Separate live authorization is required for production deploy, production DB write/migration, retained-evidence mutation, scraper/runtime activation or live collection with write effects, replay/APPLY/runtime executor invocation, scheduler/systemd/host/container mutation, secrets/credentials, Cloudflare mutation or another live authority change.

## Failure and evidence

Authorization is consumed at the first authorized mutation. Any later error/ambiguity requires evidence preservation and STOP; no automatic retry, rollback, cleanup, reset, rebase or alternate mutation path unless explicitly pre-authorized.

Use one Ready receipt and one final live receipt. Put any remaining owner decision at the **end** under one visible `ACTION REQUIRED` section; when the owner must enter/run something, provide the exact copyable instruction in a fenced `bash` block.

Merge never authorizes deploy/runtime/DB/retained mutation.
