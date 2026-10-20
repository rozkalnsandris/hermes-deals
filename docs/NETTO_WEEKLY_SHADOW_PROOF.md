# Netto #28 — shadow extraction vs unattended acceptance

Status: **source-only specification**, not authorization to execute the host
collector or run a scheduled shadow job. Parent #28 and child #1014 remain
incomplete until genuine evidence is available.

## What the offline report proves

`tools/netto_weekly_shadow_report.py` verifies exact Netto 5659 manifest,
store HTML and PDF SHA-256 under a caller-provided raw root, then invokes the
existing HTML-offer and PDF daily-special parsers. The create-only receipt binds
the campaign, validity and digests. It reports extracted counts only.

It **does not** prove complete booklet/card ownership, independent source
truth, publication readiness, or two genuine unattended transitions. The
`source_card_breakdown` carries six **null**, not zero, independently
unverified quantities: `total_source_cards`, `parsed_cards`,
`review_pending_cards`, `excluded_cards`, `unsupported_cards`, and
`unaccounted_cards`. The existing HTML/PDF candidate counts refer only to
parsed candidates and must not be relabeled as source-card counts. The GitHub
attestation rejects any missing/modified breakdown or a fabricated 0. This
is an explicit unknown-state contract, **not** source-card reconciliation.
Always:
`source_card_accounting=unknown`, `shadow_acceptance_passed=false`,
`issue_28_two_real_transitions_ready=false`, `promotion_ready=false`.
Each offline CLI invocation emits one create-only receipt outside the raw-evidence
root. Verified extraction yields `execution_outcome=extraction_complete_coverage_unverified`;
input/evidence/parser failures yield `execution_outcome=failed` and only a
fixed `failure_category` without unverified campaign identity or raw error
strings. Failed receipts return a nonzero process code. Receipt outputs are
created exclusively (`xb`); pre-existing paths and symlinks are not replaced,
and partial writes are never silently retried or cleaned up. These receipts
are diagnostics, not independently authenticated scheduled-run evidence.

Zero parsed daily specials is not proof that no special offers exist. For
`verified_no_pdf` the current V3 PDF-bound extraction contract fails closed;
it does not substitute an invented empty PDF or a stale campaign.

## Needed future scheduled-run proof — NOT wired/authorized here

A separate reviewed execution plan and explicit LIVE authority are needed
before enabling source parsing on the trusted self-hosted runner or modifying
its timer/workflow. The scheduler currently records `run_shadow` **decision**
only. It has no completed shadow-extraction artifact.

A future source-only verifier should accept an artifact **only after** it
obtains the following independently using authenticated, read-only GitHub APIs,
not values asserted by a JSON payload:

1. Immutable repository/workflow identity, exact checked-out `main` commit,
   workflow/job ID, `event=schedule` (not `workflow_dispatch`), successful
   conclusion and final job status; an expected execution step actually invoked
   the reviewed shadow parser on that same commit.
2. Exact artifact ID, owning workflow run ID, unexpired status, `sha256:`
   archive digest computed over downloaded bytes, bounded ZIP members and
   member hashes, canonical receipt hash and single known receipt schema.
   No ambiguous second artifact or mixed provenance is accepted.
3. Receipt's campaign key/window, store 5659, parser strategy/identity,
   selector evidence identity, HTML/PDF/manifest digests and exact run binding
   must match the independently attested source evidence. Count totals alone
   do not establish card completeness.
4. Independent reviewed source-card accounting must reconcile extracted,
   explicitly Review-pending, excluded, unsupported and unaccounted cards.
   Any unknown/unaccounted card, failed parser, missing PDF or ambiguous
   comparison fails the acceptance gate.
5. Only **two consecutive distinct real weekly campaign windows** with two
   authenticated scheduled successful shadow results (not duplicate identity,
   re-run, manually dispatched job or synthetic fixture) may satisfy the parent
   #28 shadow-transition criterion. Sunday early-window observation does not
   count. Old observation receipts cannot be grandfathered in.

The current workflow does **not** satisfy these conditions. Nothing in this
source work turns the parent acceptance flag true. Production writes, Review,
approval, publication, deployment, scheduler/runner and host changes all
remain separately authorized.

## Independent read-only GitHub run/artifact attestation (source-only)

`tools/netto_weekly_shadow_attestation.py --run-id <numeric-run-id>` obtains
the workflow run, complete job listing, and run artifact listing using
authenticated GitHub REST GET requests, then downloads only the exact bounded
scheduled shadow artifact. It validates GitHub's sha256 ZIP digest, internal
SHA256SUMS and known ZIP members (`selector.json`, `shadow-report.json`,
`SHA256SUMS`). A signed archive redirect never receives the GitHub API token.

For an attestation to pass, the real GitHub run must be first-attempt,
`event=schedule`, on `main`, from the exact Netto weekly workflow,
completed successfully, and contain a successful step named
`Build offline shadow extraction receipt`. The artifact name must be exactly
`netto-weekly-shadow-scheduled-<run-id>` and its GitHub-owned run ID and head
must match; SHA/path/campaign/store/validity/parser identity must match across
selector and report. This report is **not** user-supplied authenticated state.

Important: **the current scheduled workflow does not yet have that step or
artifact**. A currently completed `run_shadow` source-selection decision is
rejected; reruns, manual dispatches, duplicate/expired artifacts, mismatched
evidence and self-declared acceptance are rejected. Test fixtures demonstrate
the mechanics only, **not real historical acceptance**.

A passing attestation means only **scheduled extraction observed**. It still
returns `source_card_accounting=unknown`,
`shadow_acceptance_passed=false` and
`issue_28_two_real_transitions_ready=false`. Future independent source-card
reconciliation plus two real distinct consecutive qualifying weekly campaigns
remain separate work and separate LIVE activation gates.

## Two separate unattended campaign windows — source-only verification

`tools/netto_weekly_shadow_attestation.py --run-id <first-id> --second-run-id <second-id>`
performs **two independent GitHub read-only fetch/verification sequences**.
It accepts neither two self-asserted JSON receipts nor one reused artifact.
Both runs must pass the one-run attestation first. Their authenticated GitHub
run IDs, archive digest, artifact IDs, immutable campaign/manifest/PDF identity
and campaign keys must differ. The run creation timestamps must be ordered and
fall **within the respective campaign in Europe/Berlin** (an early Sunday
observation cannot count). Campaign start dates must be exactly seven days
apart and their windows must not overlap, with the normal one/two-day weekly
boundary gap. Missing, manual, rerun, out-of-order, repeated, early or
skipped-week evidence fails closed.

The result exposes `two_consecutive_scheduled_extractions_attested=true`
**only when those two separately authenticated extractions pass**. It
continues to emit `source_card_accounting=unknown`,
`shadow_acceptance_passed=false` and
`issue_28_two_real_transitions_ready=false`: two parsed runs are **not**
two validated booklet-coverage cycles. Independent source-card accounting
and a separately authorized LIVE scheduler/runner activation are still
required; the current scheduler does **not** emit shadow extraction receipts.
Unit tests use synthetic inputs and are not real evidence.

## Prepared staging and exact LIVE activation boundary (not activated)

A source-only staging helper, `tools/netto_weekly_shadow_artifact.py`, now
prepares the **exact three member files** expected by the authenticated GitHub
attestor. It does **not** invoke a parser, upload anything, authenticate a
scheduled run, or confer #28 acceptance. On `event=schedule` only, it checks
the selector/report identity, all six unknown card counts, read-only source
directory separation, and the non-promoting safety flags, then creates a
new, non-existing temporary output directory containing only:
`selector.json`, `shadow-report.json` and `SHA256SUMS`. Existing output
is not clobbered; any partial write is retained for inspection with no
automatic retry or cleanup.

**Source-only candidate wiring, NOT an active workflow modification:**

1. Only after separate explicit LIVE authorization, modify the existing
   `.github/workflows/netto-weekly-transition-state.yml` in a separately
   reviewed PR. Keep the existing non-root self-hosted
   `hermes-deals-audit` runner, immutable `github.sha` checkout, read-only
   source selection, and restricted permissions; do not grant DB/Review/
   publication or production mutation.
2. Add a scheduled-only job step named exactly
   `Build offline shadow extraction receipt`. Require the existing
   `state.json` decision `run_shadow`, store 5659 and `pdf_bound`
   evidence; never fall back to stale campaigns or synthesize a PDF.
   Execute `tools/netto_weekly_shadow_report.py` against the current
   `$ROOT/current/selector.json` and
   `$ROOT/current/source`, with create-only output
   `$ROOT/current/shadow-report.json`, **only if** these checks pass.
   Handle `verified_no_pdf`/other decisions explicitly as unaccepted
   skips, not as successful shadow steps/artifacts.
3. After a successful step, invoke the staging helper on those **same**
   immutable paths, using an **unused temporary output directory** outside
   the raw source root, with `--event "$EVENT_NAME"`. Then upload the
   three staged files **only for GitHub `schedule` events**, as artifact
   `netto-weekly-shadow-scheduled-${GITHUB_RUN_ID}`, with bounded retention.
   The new artifact does not replace the existing transition-observation
   artifact. Upload errors fail the run; never retry silently.
4. Independently verify actual completed workflow run/job/step, immutable
   commit, artifact ID/digest/member checksums and first-attempt scheduling
   using the merged `netto_weekly_shadow_attestation.py` tool, *after*
   the authorized source is deployed and real weekly cycles occur.
   Synthetic fixtures/manual replays never count. Successful staging or a
   single scheduled extraction still does not prove source-card completeness
   or authorize publication.
5. The owner must approve the exact workflow change through a separate
   source PR and MERGE gate, and then separately authorize actual
   runner/scheduler/retained-artifact execution if required by the
   deployment policy. Do not infer any LIVE permission from this staging
   helper, its tests, or its merger.

This is preparation only. No changes to currently active workflow, timer,
runner, database or production collection are made by this PR.

## Merged disarmed wiring and separate post-merge activation (NOT LIVE)

PR #1023 merged scheduled shadow gate/parser/staging/upload steps into
`.github/workflows/netto-weekly-transition-state.yml`. Its original static
`NETTO_SHADOW_RUN_ENABLED: 'false'` deliberately prevented runner-side shadow
execution. The subsequent **control-preparation** PR replaces that static
sentinel with two separately owner-managed repository configuration variables.
No GitHub Actions variable is created or changed by this source-only PR.
The actual switch remains fail-closed until explicit post-merge LIVE approval.

After the existing immutable transition observation artifact is uploaded,
four currently disarmed steps are configured: a first-attempt scheduled-only
guard that independently binds the source selector, transition state and
SHA-256 state receipt; the exact offline HTML/PDF shadow parser; create-only
three-file artifact staging outside the evidence root; and a bounded
schedule-only GitHub artifact upload. The parser/stage/upload steps also require
the previous step's successful eligibility/outcome. The guard rejects
manual/dispatch and reruns, duplicate transition records, campaign/identity
drift, early/out-of-window records, promotion or DB authority. A
`verified_no_pdf` campaign or an unchanged/non-shadow decision is skipped
without creating a successful extraction step or shadow artifact. The scoped
parser and staging steps set `DATABASE_URL` to ephemeral in-memory SQLite,
not production.

All existing transition observation, report, permissions, self-hosted runner,
concurrency, and cleanup steps are left intact. The new artifact's name,
three member files, run identity and successful extraction step match the
read-only GitHub provenance attestor. Importantly, **two genuinely scheduled
extractions still do not establish source-card reconciliation or #28
readiness**, and no offer/price or production publication can be promoted.

## External two-key Actions control — source-only preparation

GitHub's documented `vars` context exposes repository/organization/environment
configuration variables in step `if` expressions. A missing variable resolves
to the **empty string**, not `true`. GitHub evaluates step `if` conditions
before dispatching that step to the runner. Official references:

- https://docs.github.com/en/actions/reference/workflows-and-actions/contexts
- https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-variables

Every scheduled-only shadow step now additionally requires **both**:

1. `vars.NETTO_SHADOW_V1_ENABLED == 'true'`
2. `vars.NETTO_SHADOW_V1_APPROVED_MAIN_SHA == github.sha`

It also requires `github.ref == 'refs/heads/main'`,
`github.run_attempt == 1`, and `github.event_name == 'schedule'`.
Neither configuration variable is defined in the repository source. The
approved commit SHA is the **exact merged `main` SHA**, which cannot be known
when this proposal is prepared or before its squash merge. A preceding
value, absent value, wrong SHA, missing enable flag, manual dispatch or rerun
must not execute the new shadow steps.

This gate is deliberately **commit-scoped**: after any new `main` commit
(including automated progress commits), a previous activation automatically
fails closed. To span another real scheduled campaign at a different head,
the owner must explicitly authorize and revalidate that new exact SHA.
Never pre-authorize a guessed future commit or set either variable to `true`
without checking the current exact source and runner/scheduler baseline.

**Before a separate LIVE authorization**, verify the Actions variables'
existing names/values (including effective organization/repository scope)
using GitHub's authorized settings/API and confirm the immutable workflow SHA,
current `main`, active runner, and expected schedule. Read-only access to
repository variables was unavailable to the original source-preparation
session; their present values are **unknown**, not presumed absent. A merge
does **not** set the variables or authorize their creation. Changing the
variables, executing the runner/collector, uploading actual scheduled
artifacts, changing the schedule, applying migrations, or publishing offers
requires a separate exact owner LIVE authorization. Two authentic extractions
still do **not** establish full card coverage or the parent #28 acceptance
criterion.
