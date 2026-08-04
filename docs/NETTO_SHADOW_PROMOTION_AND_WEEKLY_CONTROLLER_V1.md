# Netto shadow promotion and weekly controller v1

## Status

This design is **shadow-only**. It does not approve offers, publish offers,
deploy production code, replace immutable snapshots or write to PostgreSQL.

It provides the common safety layer needed by issues #27 and #28:

- independent promotion gates for title, brand, package, price, validity and
  card ownership;
- immutable manifest, HTML and PDF hash binding;
- family-primary Netto store binding (`5659`);
- Review-only fallback for any field that does not pass both precision and
  coverage gates;
- a deterministic weekly state machine with Sunday-gap safety, unchanged
  campaign no-op, bounded retries, stale-week alerts and verified no-PDF
  handling;
- an exact create-only write/rollback plan whose `apply_authorized` value is
  always `false`.

The implementation is in `tools/netto_weekly_shadow.py`. Focused regressions
are in `backend/tests/test_netto_weekly_shadow.py`.

## Promotion gates

Promotion is field-specific. Passing one field never promotes another field.
The default gates are:

| Field | Minimum precision | Minimum coverage |
|---|---:|---:|
| title | 90% | 90% |
| brand | 95% | 90% |
| package | 90% | 90% |
| price | 99% | 99% |
| validity | 100% | 99% |
| card ownership | 99% | 99% |

Every field also requires at least 25 audited, non-ambiguous observations by
default. A promotion audit must contain at least two frozen campaign families.

Disagreements are classified as one of:

- `parser_defect`;
- `ambiguous_source`;
- `truth_pack_correction`;
- `match`.

`ambiguous_source` and `truth_pack_correction` remain visible in the report but
are excluded from the parser-performance denominator. Parser omissions reduce
coverage. Incorrect automatic selections reduce precision.

The historical N24 evidence remains unchanged:

- full title-token coverage: `46/61 = 75.41%`;
- automatic package selections: `0/61`.

Therefore title and package remain Review-only until a real multi-campaign
frozen corpus passes the gates above. The test corpus proves the gate mechanics;
it is not presented as production evidence.

## PDF and HTML precedence

PDF evidence is authoritative when a campaign has a bound PDF. HTML is only
supplementary candidate evidence and cannot replace contradictory PDF evidence.
A title or package disagreement between HTML and PDF is always routed to Review,
even when the field's aggregate promotion gate passed.

Every shadow candidate retains:

- store external ID and scope;
- manifest path and SHA-256;
- HTML SHA-256;
- PDF path and SHA-256;
- parser identity;
- page number and card ID.

## Evidence states

The controller distinguishes four states:

- `pdf_bound`: immutable PDF path and SHA are present;
- `verified_no_pdf`: PDF path/SHA are null and an explicit reason is present;
- `missing`: expected evidence is unavailable;
- `corrupt`: evidence exists but cannot be trusted.

`verified_no_pdf` returns an explicit safe-empty daily-special mode. `missing`
and `corrupt` fail closed, retry at most three times and then emit a stable alert
key. No stale-path fallback is allowed.

## Weekly state machine

The state machine produces one action:

- `wait_for_window`: target campaign has not started; no Sunday early write;
- `unchanged_noop`: campaign key and manifest SHA are unchanged;
- `safe_empty_no_pdf`: campaign explicitly proves no PDF exists;
- `run_shadow`: bound evidence is ready for validation;
- `retry_fail_closed`: bounded retry, with no data exposure or write;
- `alert_retry_exhausted`: retry limit reached;
- `alert_stale_week`: no verified campaign covers the current date;
- `write_plan_ready`: shadow validation passed and a reviewable plan may be
  generated, but production apply is still unauthorized.

Requested-date selection remains constrained by the manifest's verified
`valid_from..valid_until` window. This complements the existing API selection
contract introduced by PR #14.

## Exact write and rollback plan

`build_write_plan()` creates a deterministic snapshot identity from:

- campaign key;
- manifest SHA;
- PDF SHA;
- parser identity.

The plan is create-only:

- insert a new immutable snapshot and its candidates;
- never replace an existing snapshot;
- never enable automatic approval or publish;
- preserve all pre-existing rows;
- limit rollback to rows created by the exact snapshot identity;
- require separate authorization for both apply and rollback.

## CLI

Audit a frozen JSON array:

```bash
python3 tools/netto_weekly_shadow.py audit \
  --input /path/to/audit-rows.json \
  --output /path/to/promotion-report.json
```

Evaluate one weekly controller input:

```bash
python3 tools/netto_weekly_shadow.py decide \
  --input /var/lib/hermes-deals/netto-weekly-shadow/input.json \
  --output /var/lib/hermes-deals/netto-weekly-shadow/decision.json
```

An error-severity decision exits with status `2`, making timer failures visible
to systemd and the alert unit.

## Timer templates

The repository includes non-installed systemd templates under `ops/systemd/`.
They run the shadow decision hourly on Sunday and once each morning Monday to
Saturday. The service writes no production data. Any failed run triggers an
error-priority journal entry and `/run/hermes-deals/netto-weekly-shadow.failed`.

Installing or enabling these units on the RPi5 is a separate production action
and is not authorized by this change.

## Remaining evidence before closing #27 and #28

Code and simulated transition gates can pass in GitHub CI, but the issues should
remain open until the RPi5 evidence run proves:

1. a real multi-campaign frozen Netto corpus passes or correctly blocks each
   field independently;
2. two consecutive real campaign transitions complete unattended in shadow
   mode;
3. the generated exact campaign manifest, candidate diff, write plan and
   rollback plan are reviewed;
4. no production write occurs without a separate explicit approval.
