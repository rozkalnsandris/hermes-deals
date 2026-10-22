# Netto #28: pinned reusable shadow executor and disarmed caller

> **2026-10-22 staged source-only correction (Netto #28):** The reusable executor **definition in current source** is being prepared to check out immutable reviewed commit `0aabd85fb813a8432ee5d208655bb092e65b7bbb` (PR #1031 store-5659 trust binding). Its previously deployed immutable caller still references `93b866ba2ec64ab2100f48733487afc960298d61` and thereby uses the original `0110e386d66b24b7d10c75df4d4970113dee3a49` source. This source-only preparation does **not** retarget that caller or change Actions variables; it has no runtime cutover or acceptance effect. After the staged definition is merged, a **separate** reviewed source change must pin the new immutable definition commit and its exact blob in the caller and attestor, preserving fail-closed selection. Any actual re-pin activation or scheduled runner/source/retained-artifact execution remains a separate owner LIVE gate. No pinned extraction/full-card coverage or #28 end-to-end completion is claimed.\n\nThe reusable executor was merged by PR #1025 at immutable commit
`93b866ba2ec64ab2100f48733487afc960298d61`. Its reviewed source definition blob is
`969d51ca97de5021e74ad67555186995fb8111d1`; it checks out the independently pinned executable source
`0110e386d66b24b7d10c75df4d4970113dee3a49` before any retailer source collection.

The follow-up caller change remains **source-only and disarmed**. It modifies
the existing scheduled workflow so the legacy transition observation remains
the default while `NETTO_PINNED_EXECUTOR_V1_*` variables are absent. It adds
one pinned reusable-workflow job at the exact commit above and a read-only
GitHub attestor. It does **not** create/change Actions variables, run the
collector, change the schedule/runner, deploy, write DB/Review/publication
state or claim real runtime evidence.

## Rationale and immutable identity

GitHub's reusable workflow `on: workflow_call` has no independent scheduled
trigger. A caller invokes it as a **job** using
`rozkalnsandris/hermes-deals/.github/workflows/netto-weekly-pinned-shadow-executor.yml@<40-hex immutable SHA>`.
The merged reusable workflow is now called only through the immutable literal
`93b866ba2ec64ab2100f48733487afc960298d61`. Do not use `@main`, a mutable tag, a synthesized future SHA,
or a same-commit relative `./.github/workflows` reference. GitHub documents
that an explicit commit SHA is the safest reusable-workflow reference and that
the `github` context inside a called workflow remains associated with the
caller. The caller head may therefore move for unrelated repository changes
without changing the pinned executable source.

The executor checks out this **pinned source SHA** regardless of the caller:

`0110e386d66b24b7d10c75df4d4970113dee3a49`

That Git commit contains the exact Netto collector, source selector,
transition state, shadow gate, parser, artifact staging, attest helpers and
versioned direct requirements. The executor verifies the Git HEAD **before**
fetching any source. The **caller head SHA** is intentionally independent:
unrelated docs/UI merges must not silently change what collector/parser
code runs. The **called reusable workflow SHA** (chosen after the PR merge)
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
   Those variables were absent in the source-preparation read-only preflight
   and are **not created** here. Unknown later value drift fails closed;
   they must be re-read before a separate LIVE authorization.
3. The reviewed caller uses the literal **called reusable workflow SHA**
   `93b866ba2ec64ab2100f48733487afc960298d61` and only `contents:read`, `actions:read`, `issues:write`
   permissions. The positive pinned selector and the inverse legacy selector
   are mutually exclusive for scheduled `main` runs. If the pinned selector
   is active on a rerun, both execution paths skip rather than falling back to
   mutable-main execution. Manual dispatch continues only through the legacy
   observation path. Original transition-state history keeps its existing
   prefix; pinned proof uses `netto-weekly-pinned-shadow-scheduled-<run-id>`.
4. A later **separate LIVE authorization** must explicitly control
   disabling/reconciling legacy `NETTO_SHADOW_V1_ENABLED`, the new
   enable/source variables, schedule and runner state, and any resulting
   retained artifacts. No automatic toggle, merge, runtime, rollback,
   production/DB/Review write, or collector execution is authorized here.

Until the separate LIVE variable cutover is approved, **the current legacy
transition observation remains the effective scheduled path**. Adding the
caller source does not activate the reusable executor and is not runtime proof.

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
  `rozkalnsandris/hermes-deals/.github/workflows/netto-weekly-pinned-shadow-executor.yml@93b866ba2ec64ab2100f48733487afc960298d61`,
  with resolved SHA `93b866ba2ec64ab2100f48733487afc960298d61` and no mutable ref.
- Independently, the caller workflow source at the actual run head must contain
  that exact immutable reference, and the reviewed reusable workflow blob
  `969d51ca97de5021e74ad67555186995fb8111d1` must be fetched at that SHA.
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
create/set the two pinned selector variables in fail-closed order. Verify
scheduled runner capacity, job authorization, Python dependency trust and
failure notification. No variable, runner or schedule mutation is bundled with
the source merge.

There is no production apply, DB write, publication, Review write, deployment
or manual test run in this preparatory PR.
