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
truth, publication readiness, or two genuine unattended transitions. Always:
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
