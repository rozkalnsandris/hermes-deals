# Lidl Gate B generic frozen-family promotion

Issue: #228 (child of #24)

This contract replaces **none** of the historical B15H4 code. The old observation promoter remains legacy-only. This path exists for a newly source-frozen physical-store family whose exact `source.pdf` and `source.json` already live under the immutable Lidl corpus.

## Boundary

The repository change provides two separate operations:

1. `tools/lidl_gate_b_family_scan.py` builds a V6.3.1 scan in an isolated staging root. It never writes the corpus. The output flyer key is the exact frozen directory name and the canonical scan name is `scan-v631-<first 12 parser SHA chars>`, which is discoverable by the existing Gate A `find_corpus_match()` contract.
2. `tools/lidl_gate_b_family_promotion.py` validates a reviewed page-role profile, staged scan, exact source identities and an owner approval object, then plans or applies a create-once canonical `scans/<scan-name>/` plus root `review-profile.json` installation.

The promotion tool derives all row/page counts from the exact evidence. It deliberately contains none of the historical `353/352/204/148/1`, `23/69`, 140-binding, fixed parser-input or fixed product-binding constants.

## Deterministic scan time

Fresh scan builds must not use wall-clock time as content-addressed evidence. The builder requires the retained Schwarz `source.json.dateTime`, parses it as an offset-aware timestamp and normalizes it to UTC. The same value is used for parser discovery/collection and `summary.json.scanned_at`.

If `dateTime` is absent, malformed or timezone-naive, the build fails closed. Two independent clean staging roots for the same frozen bytes and parser therefore have the same semantic timestamp and are expected to produce byte-identical scan evidence.

## Review profile

The reviewed profile must:

- use schema version 1 and target kind `weekly_physical_deals`;
- have a reviewed status;
- bind the exact source PDF SHA-256 in `source`;
- partition every page exactly once across target, baseline and excluded roles;
- contain no duplicate or out-of-range page assignment.

The tool does not infer a page-role profile and does not copy the historical 69-page profile to a new family.

## Approval object

Promotion requires a JSON object containing exactly:

- `schema_version: 1`;
- `decision: approve_gate_b_family_promotion`;
- `scope: canonical_scan_profile_create_once`;
- non-empty `approved_by`, `approved_at` and `note`;
- exact `flyer_key`, source PDF/raw SHA-256, parser SHA-256 and canonical scan name;
- exact staged scan tree SHA-256 and review-profile SHA-256;
- dynamic `scan_expectations` copied from the reviewed scan summary;
- permissions exactly:
  - `corpus_write: true`;
  - `replace_existing: false`;
  - `db_write: false`;
  - `review_write: false`;
  - `auto_approve: false`;
  - `auto_publish: false`;
  - `systemd_change: false`;
  - `timer_install: false`;
  - `production_deploy: false`.

This is an explicit evidence-bound corpus-write authorization, not authorization for DB/Review/publication or production activation.

## Create-once semantics

Before apply, the plan verifies the complete scan file set against `SHA256SUMS`, source and parser identity, page partition, scan tree digest and approval bindings.

- absent canonical scan/profile -> `CREATE`;
- existing byte-identical scan/profile -> `REUSE_IDENTICAL`;
- any occupied non-identical or unsafe destination -> fail closed.

Apply copies a scan through a private staging directory and installs it by same-parent rename to the previously absent canonical path. The profile uses exclusive creation. A completed apply is re-planned and must converge to `NO_OP_IDENTICAL`; replay then performs zero writes.

## Gate A compatibility

The canonical scan name intentionally starts with `scan-`, matching the current Gate A inventory. The promoted profile is installed at the flyer root, also matching Gate A. Focused tests call the current `find_corpus_match()` against a promoted synthetic family and require it to resolve the exact scan.

A later controlled live Gate B action must still run Gate A and `tools/lidl_weekly_semantic_view.py` against the exact promoted family and require deterministic replay with `unexplained_count == 0` before #24 can advance.

## Safety

The implementation PR itself performs no live parser execution, corpus write, production DB/Review write, approval/publication, deploy/restart, systemd/timer/retry action, Gate C/D action or B15M2 V08 action. Any real RPi5 scan and canonical promotion remain separate owner-authorized operations after merge and exact-SHA verification.
