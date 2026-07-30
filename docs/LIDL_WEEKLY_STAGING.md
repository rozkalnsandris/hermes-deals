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
