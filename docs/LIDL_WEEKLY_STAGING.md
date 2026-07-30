# Lidl weekly source staging and authoritative scan

B15H1 adds an append-only staging boundary between selected-store discovery and
the immutable Lidl corpus. Staging is not production import and is not corpus
promotion.

The worker consumes already captured discovery evidence with networking disabled.
For a usable source it creates:

- a PDF-content-addressed flyer directory;
- one immutable raw observation directory per raw SHA-256;
- a SHA-gated V6.3.1 authoritative scan for that exact PDF/raw pair;
- a status document that stops at `WAIT_PROFILE` until a reviewed page-role
  profile is explicitly supplied.

Layout:

```text
~/hermes-deals-lidl-staging/flyers/<dates>-r<region>-<pdf12>/
  source.pdf
  source-manifest.json
  observations/<raw64>/
    source.json
    observation.json
    scans/v631-<parser12>/
      parser-report.json
      parser-rows.json
      corrected-rows.json
      parser-rows.tsv
      corrected-rows.tsv
      review-required.tsv
      accepted-physical.tsv
      summary.json
      SHA256SUMS
```

Existing bytes are verified and reused; they are never overwritten. A raw refresh
with the same stable source identity receives a new observation directory. A
source, manifest, observation, scan, or checksum collision fails closed.

This step records `staging_write=true` but always keeps `corpus_write=false`,
`db_write=false`, `review_seed=false`, `auto_approve=false`,
`auto_publish=false`, and `systemd_change=false`.

## Parser-input identity gate

For an already known PDF, a refreshed Schwarz payload is not treated as merely volatile when its canonical parser input changes. The staging workflow removes only top-level `dateTime` and `warnings`, hashes the remaining canonical payload, and records the product-binding digest. A mismatch against the matching immutable corpus source returns `WAIT_SOURCE_REVIEW` before any authoritative scan is created. The raw observation remains content-addressed in staging for controlled review.

## Explicit source-refresh review

A parser-input refresh for an already known PDF remains blocked until an exact
review decision is supplied with `--source-review-file`. The decision is bound
to the flyer key, PDF SHA-256, reference parser-input digest, approved live
parser-input digest, product-binding digests/counts, and the observed binding
change summary.

Only the decision `approve_parser_input_refresh` with scope
`authoritative_staging_scan_only` is accepted. Its permissions must explicitly
keep corpus writes, production DB writes, Review Queue seeding, automatic
approval/publication, and systemd changes disabled.

After validation the canonical decision is written once as
`observations/<raw64>/source-review.json`. The V6.3.1 authoritative scan may then
be created in that same observation. With no reviewed page-role profile, the
expected result is `WAIT_PROFILE`; this is still not corpus promotion or
production import.

## Reviewed page-role profile gate

A source-reviewed authoritative scan is not promotion-ready until an immutable
human-reviewed page-role profile is supplied with `--review-profile-file`.
The profile is bound to the exact PDF SHA-256, must use a reviewed status, and
must partition every flyer page exactly once across:

- `target_pages` for physical weekly food, drink and household-consumable deals;
- `baseline_pages` already covered by normal structured extraction;
- named `excluded_page_roles` such as editorial, online-only or durable non-food.

The profile decides only page roles. It does not approve products, prices,
packages, validity, production writes, Review Queue seeding or publication.
The exact input bytes are written once as `<flyer>/review-profile.json`; a
mismatching replay fails closed. Once the profile and scan are both valid, the
staging result becomes `STAGED_SCAN_READY` for a separately controlled corpus
promotion step.

## Controlled immutable corpus observation promotion

A `STAGED_SCAN_READY` result is still not a production import. B15H4 adds a
separate append-only promotion boundary that copies one exact reviewed staging
observation into the matching immutable corpus flyer without replacing the
canonical root source, changing the reviewed page-role profile, writing the
production database, seeding Review Queue, publishing offers or installing a
timer.

The promoted layout is:

```text
~/hermes-deals-lidl-corpus/flyers/<flyer-key>/
  source.pdf                       # existing canonical PDF, unchanged
  source.json                      # existing reference raw source, unchanged
  review-profile.json              # existing reviewed page-role profile, unchanged
  observations/<raw64>/
    source.json
    observation.json
    source-review.json
    corpus-promotion.json
    scans/v631-<parser12>/...
```

Promotion requires an exact user approval bound to the flyer key, PDF SHA-256,
raw SHA-256, V6.3.1 parser SHA-256, source-review SHA-256, review-profile
SHA-256, staging digest and exact scan counts. The only permitted write is the
new content-addressed corpus observation directory. Existing bytes are verified
and reused; collisions fail closed.
