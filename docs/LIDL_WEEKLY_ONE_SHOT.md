# Lidl selected-store weekly one-shot

The B15G one-shot is a read-only gate between official selected-store discovery
and the existing immutable Lidl corpus. It is not a collector and does not
archive, scan, seed Review, approve, publish, or install a timer.

The command uses family store `DE06664`, Husener Straße 44, Dortmund, evaluates
the calendar in `Europe/Berlin`, consumes each flyer's own `/ar/<region>` route,
and requires an immutable worker image reference.

States:

- `READY`: the exact official PDF and stable source identity exist in the corpus,
  an authoritative scan exists, the page-role profile is reviewed, and the
  SHA-gated V6.3.1 completeness dry-run succeeds. Volatile raw JSON may refresh
  only when the stable identity remains exact.
- `WAIT_SOURCE`: the selected-store source is unavailable, explicitly
  `discoverable=false` without product links, or not yet archived exactly.
- `WAIT_SCAN`: source is archived but no authoritative scan exists.
- `WAIT_PROFILE`: the human page-role profile is missing or not reviewed.
- `BLOCKED_SOURCE_DRIFT`: source identity or structure is invalid or ambiguous.
- `BLOCKED_PARSER_DRIFT`: V6.3.1 source SHA or completeness output violates the
  frozen contract.

All output is evidence-only under an explicit empty output directory. The
workflow always records `corpus_write=false`, `db_write=false`,
`review_seed=false`, `auto_approve=false`, `auto_publish=false`, and
`systemd_change=false`.

## Page-role profile compatibility

The profile controls only which physical-deal pages may be inspected. The
legacy status `independent_page_role_reviewed_product_audit_in_progress` is
accepted as page-role reviewed because the remaining product audit is a
separate Review workflow and this one-shot never approves or publishes. Missing,
draft, or otherwise unknown statuses remain `WAIT_PROFILE`.

A stable flyer identity is not sufficient to authorize a refreshed parser input. Existing-PDF semantic payload refreshes are handled by the staging parser-input identity gate and return `WAIT_SOURCE_REVIEW` until reviewed.
