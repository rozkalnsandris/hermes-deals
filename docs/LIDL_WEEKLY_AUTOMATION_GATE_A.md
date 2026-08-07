# Lidl weekly automation — Gate A shadow controller

Issue: #24

## Purpose

Gate A adds a deterministic read-only decision layer above the existing Lidl selected-store weekly one-shot readiness flow. It does not activate weekly production automation.

The existing one-shot already proves:

- selected physical-store family discovery;
- exact source PDF and stable source identity matching;
- immutable corpus presence;
- authoritative scan presence;
- reviewed weekly target profile presence;
- canonical V6.3.1 parser integrity;
- weekly completeness manifest integrity;
- no corpus, database, Review, publication or systemd write.

The Gate A controller converts that detailed result into one of four operational states:

- `READY` — a new exact source/parser/review-profile combination requires a new shadow execution and later immutable snapshot handling;
- `NO_OP` — the exact source, parser, scan and reviewed profile match a previously completed Gate A manifest;
- `WAIT` — the source, source review, scan or reviewed profile is not available yet;
- `BLOCKED` — source or parser drift, an unsafe flag, malformed prior evidence or an unsupported state was detected.

## Deterministic unchanged-source identity

For a `READY` one-shot result, the controller hashes a canonical object containing:

- target (`current` or `next`);
- immutable flyer key;
- authoritative scan identifier;
- source PDF SHA256;
- stable source identity SHA256;
- canonical parser-input identity SHA256 represented by the immutable source/scan;
- canonical parser version and SHA256;
- complete reviewed target profile.

A previous Gate A manifest can be supplied with `--previous-manifest`. The controller returns `NO_OP` only when the fingerprint is identical and the previous manifest has the exact controller version, a completed `READY`/`NO_OP` state and all write-authority flags disabled.

A parser change, canonical parser-input change or reviewed-profile change therefore cannot be hidden by an unchanged PDF.

## Same-PDF source refresh boundary

The official Schwarz `source.json` may refresh while the PDF and stable flyer identity stay unchanged. Gate A distinguishes harmless raw-byte churn from parser-relevant drift:

- top-level `dateTime` and `warnings` are treated as volatile metadata and excluded from the canonical parser-input identity;
- if only those volatile fields change, the live raw SHA may differ while the canonical parser-input identity remains unchanged;
- if parser-relevant source content changes for the same PDF/stable flyer identity, the one-shot returns `WAIT_SOURCE_REVIEW` before using the old scan;
- the controller maps `WAIT_SOURCE_REVIEW` to observable `WAIT`, with no retry or write authority.

A parser-relevant same-PDF refresh requires a separately reviewed source-refresh and new authoritative scan path before it can become a new exact `READY` input. The existing frozen scan is never silently reused for changed parser input.

## Command shape

```bash
python tools/lidl_weekly_shadow_controller.py \
  --corpus /corpus \
  --output-dir /safe/evidence/run-001 \
  --target next \
  --previous-manifest /safe/evidence/run-000/controller-manifest.json
```

`--discovery-dir` may be used to replay previously captured discovery evidence without live network discovery.

## Gate A safety contract

Every result keeps these values fixed:

- `dry_run=true`;
- `corpus_write_authorized=false`;
- `database_write_authorized=false`;
- `review_write_authorized=false`;
- `production_publish_authorized=false`;
- `systemd_change_authorized=false`;
- `bounded_retry_authorized=false`.

Gate A does not:

- acquire or promote a new immutable corpus snapshot;
- seed or approve Review rows;
- publish offers;
- install a timer;
- retry unattended;
- deploy production;
- authorize a production canary.

## Later gates

- Gate B: two consecutive weekly families complete the full immutable shadow flow.
- Gate C: separately authorized exact reviewed production canary and replay proof.
- Gate D: timer, monitoring, bounded retries, stale-source alerts, disable and rollback tests.

Production activation remains a separate explicit owner authorization.
