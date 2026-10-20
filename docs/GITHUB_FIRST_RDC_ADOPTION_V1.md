# GitHub-first / RDC fallback v1 — Hermes Deals consumer

**Status:** SOURCE ONLY proposal; effective in `hermes-deals` upon separate exact-head owner merge.

**Canonical revision:** `rozkalnsandris/ops-workflows@4e89b75d7f496dfb43fd9c1eb10a995fad53fdd8` (merged upstream PR #159).
**Tracking:** `hermes-deals#1030`.
**Local adapter:** `.github/github-first-rdc-v1.json`.
**Local workflow gate:** `.github/workflows/github-first-rdc-policy.yml`.

## Mandatory per-step transport selection

1. Select connected GitHub for source/repository files, commits/branches, issues/PR, CI/review and continuity; use GitHub Actions when they can validate source safely.
2. RDC becomes eligible **only** if both connected GitHub tooling and applicable GitHub-hosted Actions cannot complete an **actually host-local** task with equivalent evidence.
3. Before any RDC step, establish the exact capability gap, minimal necessary action/target, and existing read/STRICT LIVE authority. Record `STEP`, `REPOSITORY_AND_TARGET`, `GITHUB_CAPABILITY_CHECKED`, `PRECISE_CAPABILITY_GAP`, `GITHUB_CI_NOT_EQUIVALENT_REASON`, `MINIMAL_RDC_OPERATION`, `EXISTING_AUTHORIZATION` and `GITHUB_RETURN_EVIDENCE`; keep the record free of sensitive data.
4. Execute that one bounded action and return to GitHub: **GitHub -> minimal RDC -> GitHub**.
5. On GitHub denial, 403/429, failed tool, rate limit, missing authorization, timeout, or uncertain dispatched mutation: **STOP**. RDC is not a source-write/retry/rollback alternative.

## Hermes Deals stricter exclusions

Production DB/schema/migration/data, retained/source observations, Review and publication, collectors, runtime/replay/APPLY, source execution with write effects, scheduler, systemd, host/container, credentials/permission, Cloudflare/network and deployment remain **STRICT** separately exact-authorized mutation classes. Repo evidence/provenance requirements remain unchanged. Do not infer runtime success from CI or source work.

This is not `GITHUB-ONLY`, `LIVE-ALL`, `AUTO-RUN FULL` or `AUTO-RUN FULL QUEUE`; this adaptation changes no operator-mode selection, activation, merge or live authority, and shared policy merge never edits other consumer repositories.
