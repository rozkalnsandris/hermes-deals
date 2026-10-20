# Netto #28: pinned reusable shadow executor (disarmed PREP)

This PR only adds `.github/workflows/netto-weekly-pinned-shadow-executor.yml`,
focused source-contract tests and this document. It **does not modify**
`.github/workflows/netto-weekly-transition-state.yml`, GitHub Actions
variables, the existing scheduled runner, or production. The currently
authorized legacy schedule and exact-`main` gate remain unchanged.

## Rationale and immutable identity

GitHub's reusable workflow `on: workflow_call` has no independent scheduled
trigger. A caller invokes it as a **job** using
`rozkalnsandris/hermes-deals/.github/workflows/netto-weekly-pinned-shadow-executor.yml@<40-hex immutable SHA>`.
The new workflow file does not exist at the **current** old commit and
therefore **the called reusable workflow SHA cannot be selected until after
this source PR is merged**. Do not use `@main`, a mutable tag, a synthesized
future SHA, or a same-commit relative `./.github/workflows` reference.

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

1. This file declares **only** `workflow_call`, never schedule, dispatch,
   push, `workflow_run` or PR triggers. **No caller is added here.**
2. The transition job requires `NETTO_PINNED_EXECUTOR_V1_ENABLED=true`,
   `NETTO_PINNED_EXECUTOR_V1_APPROVED_SOURCE_SHA` equal to the exact
   source SHA above, repository and original caller workflow identity,
   `event=schedule`, `ref=refs/heads/main`, and first attempt.
   Those variables were absent in the source-preparation read-only preflight
   and are **not created** here. Unknown later value drift fails closed;
   they must be re-read before a separate LIVE authorization.
3. After a future reviewed caller PR, the caller must use the literal
   post-merge **called reusable workflow SHA**, and only the approved job
   permissions; it must not concurrently invoke both legacy and new
   transition jobs. Preserve immutable artifacts, scheduled-only source
   selection and the non-root runner. Original transition-state history
   uses its existing prefix; a new shadow proof uses separate
   `netto-weekly-pinned-shadow-scheduled-<run-id>` so legacy proof cannot
   misclassify it.
4. A later **separate LIVE authorization** must explicitly control
   disabling/reconciling legacy `NETTO_SHADOW_V1_ENABLED`, the new
   enable/source variables, schedule and runner state, and any resulting
   retained artifacts. No automatic toggle, merge, runtime, rollback,
   production/DB/Review write, or collector execution is authorized here.

Until steps 3–4 are independently approved, **the current schedule remains
the only active one**. This is not a working cutover or runtime proof.

## Independent attestation contract (not yet independently attested)

The existing `tools/netto_weekly_shadow_attestation.py` validates a real
scheduled run/step/ZIP artifact for the **legacy** workflow only. It is
**not** sufficient evidence for the new `netto-weekly-pinned-shadow-scheduled-*`
namespace. In particular, a JSON file created by the runner must not
self-certify which GitHub workflow definition was actually called.

A future pinned-executor attestor must read authoritative GitHub GET
run/job/artifact metadata, and fail closed unless all of these bind:

- GitHub run ID, repository, `main`, scheduled first attempt,
  `Netto weekly transition state` original caller identity, completed
  success and the successful `Build offline shadow extraction receipt` step.
- The actual **caller head SHA**, its recorded approval and GitHub run identity;
  never equate it with the reviewed executor source SHA.
- The exact **called reusable workflow SHA** resolved from an immutable
  caller-job reference and GitHub-verified called-workflow identity.
  The source-preparation PR cannot attest this future SHA.
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

No pinned attestation success may be reported until the external run,
referenced-workflow identity and verified artifact can actually be checked.
Synthetic tests and this contract are only preparation, **not yet
independently attested**.

## Future activation blockers

A separate reviewed source change must supply a caller using the exact
merged reusable workflow SHA, plus a complete read-only attestation
implementation. Review the currently enabled legacy shadow variables before
cutover and avoid duplicate publication of transition artifacts. Verify
scheduled runner capacity, job authorization, Python dependency trust and
failure notification. Then request exact owner MERGE and a **separate LIVE
authorization** before any active schedule/runner or variables are changed.

There is no production apply, DB write, publication, Review write, deployment
or manual test run in this preparatory PR.


## Source-wired fail-closed caller after PR #1025

The reusable executor merged at immutable Git SHA `93b866ba2ec64ab2100f48733487afc960298d61`.
The scheduler source now prepares a **disarmed** direct reusable-workflow job
using the literal reference:

`rozkalnsandris/hermes-deals/.github/workflows/netto-weekly-pinned-shadow-executor.yml@93b866ba2ec64ab2100f48733487afc960298d61`

No new trigger is added. The existing Sunday/Monday schedule remains the only
scheduler. The legacy `transition` job continues whenever the pinned controls
are absent, partial or stale. Only when **both**
`NETTO_PINNED_EXECUTOR_V1_ENABLED=true` and
`NETTO_PINNED_EXECUTOR_V1_APPROVED_SOURCE_SHA=0110e386d66b24b7d10c75df4d4970113dee3a49`
match does the legacy job skip and the immutable pinned executor become
eligible. Neither variable is created or changed by this source PR.

This means merging the caller wiring alone does not execute the new
self-hosted path and does not break the currently active transition-state
observation. Actual cutover still requires a separate exact LIVE
authorization that freshly proves variable baseline, runner status and the
merged caller source.

GitHub documents commit SHA as the safest reusable-workflow reference and
returns a workflow run's `referenced_workflows` entries, including the
resolved reusable-workflow SHA. The new read-only
`tools/netto_weekly_pinned_shadow_attestation.py` therefore requires the one
exact referenced workflow `93b866ba2ec64ab2100f48733487afc960298d61`, a successful scheduled
first-attempt caller run, the required non-root/pinned-checkout and shadow
steps on the audit runner labels, and the pinned-only artifact namespace.
Only after those external GitHub facts pass does it delegate the existing
selector/report/archive integrity checks.

The attestor records the approved source revision `0110e386d66b24b7d10c75df4d4970113dee3a49` separately
from the **caller head SHA**. Future unrelated `main` changes are therefore
allowed without silently changing executor source. The caller head still has
to be a real scheduled `main` run, but it is not used as parser/collector
identity.

This remains extraction proof only:
`source_card_accounting=unknown`,
`shadow_acceptance_passed=false`,
`issue_28_two_real_transitions_ready=false` and production-write authority
false. Two independently verified pinned weekly runs still require the same
calendar-window ordering checks as the legacy attestor and still do not prove
full source-card coverage.
