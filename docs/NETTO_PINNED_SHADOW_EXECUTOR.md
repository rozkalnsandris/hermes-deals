# Netto #28: pinned reusable shadow executor and disarmed caller

> **2026-10-22 staged caller/attestor re-pin (SOURCE ONLY).** PR #1055 merged reviewed reusable executor definition at immutable commit `20b26150741ffd727cd7062e8a772fbcdeaf86cb`, exact Git blob `470b67f8192f12d501bc39c144c3acd339d7fc26`. That executor checks out the immutable `0aabd85fb813a8432ee5d208655bb092e65b7bbb` source from #1031, including exact Netto store-5659 binding. This PR updates the scheduled caller and independent attestor to those source identities. It makes **no** GitHub Actions variable, runner, schedule, publication, production or LIVE change. When pinned enablement is true with an old/missing approved source SHA, **both scheduled paths skip** rather than falling back to the mutable-main legacy job. Fresh separately authorized LIVE activation is required before any pinned scheduled execution.

**Historical baseline only:** original PR #1025 reused workflow `20b26150741ffd727cd7062e8a772fbcdeaf86cb` (blob `470b67f8192f12d501bc39c144c3acd339d7fc26`) that checked out `0aabd85fb813a8432ee5d208655bb092e65b7bbb`. Those values are no longer the proposed caller/attestor source identity. Existing repository variable values must be checked separately; no real post-hardening pinned extraction, end-to-end coverage, or #28 acceptance is claimed.

## Rationale and immutable identity

GitHub's reusable workflow `on: workflow_call` has no independent scheduled
trigger. A caller invokes it as a **job** using
`rozkalnsandris/hermes-deals/.github/workflows/netto-weekly-pinned-shadow-executor.yml@<40-hex immutable SHA>`.
The proposed caller uses the immutable literal
`20b26150741ffd727cd7062e8a772fbcdeaf86cb`. Do not use `@main`, a mutable tag, a synthesized future SHA,
or a same-commit relative `./.github/workflows` reference. GitHub documents
that an explicit commit SHA is the safest reusable-workflow reference and that
the `github` context inside a called workflow remains associated with the
caller. The caller head may therefore move for unrelated repository changes
without changing the pinned executable source.

The reviewed executor definition checks out this **pinned source SHA** regardless of the caller:

`0aabd85fb813a8432ee5d208655bb092e65b7bbb`

That Git commit contains the exact Netto collector, source selector,
transition state, shadow gate, parser, artifact staging, attest helpers and
versioned direct requirements. The executor verifies the Git HEAD **before**
fetching any source. The **caller head SHA** is intentionally independent:
unrelated docs/UI merges must not silently change what collector/parser
code runs. The **called reusable workflow SHA** (fixed by PR #1055's merge)
is a third immutable value. GitHub documents that `github` context inside
the called workflow describes its **caller**, so `github.sha` must **never**
be treated as the executor source SHA. See
https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows
and https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations.

Pinned Git source is **not** a fully reproducible runtime: the runner's
Python/pip and transitive dependencies fetched with
`backend/requirements.txt` are not locked to a complete wheel hash set.
That unresolved environmental trust dependency must be evaluated before
full unattended production-grade acceptance.

## Two independent disarm layers and staged cutover

1. The reusable file declares **only** `workflow_call`, never schedule,
   dispatch, push, `workflow_run` or PR triggers. The existing
   `netto-weekly-transition-state.yml` is the sole scheduled caller.
2. The transition job requires `NETTO_PINNED_EXECUTOR_V1_ENABLED=true`,
   `NETTO_PINNED_EXECUTOR_V1_APPROVED_SOURCE_SHA` equal to the exact
   source SHA above, repository and original caller workflow identity,
   `event=schedule`, `ref=refs/heads/main`, and first attempt.
   These variables are externally LIVE-managed; they are **not changed** here.
   Enabled with an old/missing approval fails closed (both scheduled jobs skip).
   Fresh values must be re-read before separate LIVE authorization.
3. The reviewed caller uses the literal **called reusable workflow SHA**
   `20b26150741ffd727cd7062e8a772fbcdeaf86cb` and only `contents:read`, `actions:read`, `issues:write`
   permissions. The positive pinned selector and the inverse legacy selector
   are mutually exclusive for scheduled `main` runs. With pinned enablement
   true and stale approval, both paths skip. Pinned reruns also skip instead
   of falling back to mutable-main execution. Manual dispatch continues only through the legacy
   observation path. Original transition-state history keeps its existing
   prefix; pinned proof uses `netto-weekly-pinned-shadow-scheduled-<run-id>`.
4. A later **separate LIVE authorization** must explicitly control
   disabling/reconciling legacy `NETTO_SHADOW_V1_ENABLED`, the new
   enable/source variables, schedule and runner state, and any resulting
   retained artifacts. No automatic toggle, merge, runtime, rollback,
   production/DB/Review write, or collector execution is authorized here.

Legacy scheduled observation is eligible only when pinned enablement is false.
Enabled with a stale source approval skips both paths: a source-only caller
change does not activate the reusable executor and is not runtime proof.

## Independent attestation contract (not yet independently attested)

The existing `tools/netto_weekly_shadow_attestation.py` validates a real
scheduled run/step/ZIP artifact for the **legacy** workflow only. It is
**not** sufficient evidence for the new `netto-weekly-pinned-shadow-scheduled-*`
namespace. In particular, a JSON file created by the runner must not
self-certify which GitHub workflow definition was actually called.

The read-only `tools/netto_weekly_pinned_shadow_attestation.py` implementation
reads authoritative GitHub GET run/job/artifact/workflow-content metadata and
fails closed unless all of these bind:

- GitHub run ID, repository, `main`, scheduled first attempt,
  `Netto weekly transition state` original caller identity, completed
  success and the successful `Build offline shadow extraction receipt` step.
- The actual **caller head SHA**, its recorded approval and GitHub run identity;
  never equate it with the reviewed executor source SHA.
- The GitHub workflow run's `referenced_workflows` metadata must contain
  exactly one entry for
  `rozkalnsandris/hermes-deals/.github/workflows/netto-weekly-pinned-shadow-executor.yml@20b26150741ffd727cd7062e8a772fbcdeaf86cb`,
  with resolved SHA `20b26150741ffd727cd7062e8a772fbcdeaf86cb` and no mutable ref.
- Independently, the caller workflow source at the actual run head must contain
  that exact immutable reference, and the reviewed reusable workflow blob
  `470b67f8192f12d501bc39c144c3acd339d7fc26` must be fetched at that SHA.
- The exact **pinned source SHA** above, verified through the immutable
  reusable YAML checkout ref **and** the observed successful checkout
  verification step; neither untrusted artifact contents nor the
  caller `github.sha` proves it alone.
- The unique GitHub-owned pinned-shadow artifact ID, run ID, sha256 archive
  digest, exact expected ZIP members, internal SHA256SUMS, bounded sizes,
  no symlinks, and selector/report manifest, HTML, PDF, campaign, validity
  and parser identity reconciliation.
- Result must stay `source_card_accounting=unknown`,
  `shadow_acceptance_passed=false`,
  `issue_28_two_real_transitions_ready=false` and production-write
  authority false until independent source-card reconciliation and two
  authentic consecutive weekly windows have been proven.

No pinned attestation success may be reported until a real external scheduled
run, caller source, referenced reusable definition and verified artifact can
actually be fetched. The implementation and synthetic regression fixtures are
preparation only: the pinned path is **not yet independently attested**.

## Future activation blockers

After this caller/attestor source change passes review and is merged, re-read
both legacy and pinned Actions variable baselines plus runner state. A separate
LIVE authorization must disable/reconcile the stale legacy shadow switch and
reconcile/set both pinned selector variables in fail-closed order. Verify
scheduled runner capacity, job authorization, Python dependency trust and
failure notification. No variable, runner or schedule mutation is bundled with
the source merge.

There is no production apply, DB write, publication, Review write, deployment
or manual test run in this preparatory PR.
