# ALDI A3.1 deterministic offer-to-page parity v1

## Purpose

A3.0 proves that the exact A2.1 evidence archive and all 90 official ALDI
flyer pages are available without depending on a live viewer. A3.1 adds the
missing identity layer between the A2.1 offer rows and visually distinct flyer
cards.

This gate is deliberately fail-closed and shadow-only. It does not change the
collector, database, API, UI, timers, containers, deployment, approval state,
or publication state.

## Frozen inputs

A3.1 accepts only:

- the exact A2.1 adjudicated projection SHA256
  `64699b7ede52dcaa5b85f3306426f3b90399dd037209621a38bacd166161d5ea`;
- the A2.1 publication counts:
  `346 auto_candidate`, `54 review_required`, `119 blocked_out_of_scope`;
- one A3.0 page-image manifest containing the exact 49 current and 41 preview
  official pages;
- one card ledger bound to the derived frozen page-set SHA256.

The runner reuses the A3.0 archive verifier before any template or parity work.

## Card ledger schema

The ledger is JSON with `schema_version: 1`, `source_page_set_sha256`, and a
`cards` array. Every card has:

- `card_id`: stable identity such as `current:p004:c003`;
- `source_page`: `current` or `preview`;
- `page_number`: page within the frozen 49/41 range;
- `region`: normalized `x`, `y`, `width`, `height` values in the range 0..1;
- `scope`: `in_scope`, `review`, or `out_of_scope`;
- `title`, optional `brand`, and optional `price_eur`;
- optional `explicit_offer_ids` when visual/source identity is proven;
- optional `unmatched_reason` for a visually verified card that is not
  represented by the A2.1 source corpus.

Stable IDs, page ranges, regions, duplicate assignments, and page-set binding
are validated before matching.

## Matching policy

Matching order is deterministic:

1. an explicit `source_offer_id` assignment;
2. otherwise a conservative same-source-page title/brand/price match.

A heuristic match is eligible only when title evidence is strong and either the
price matches or brand/title evidence is sufficiently complete. The best match
must be unique with a fixed score margin. Ties and near-ties are ambiguous and
fail closed.

Every automatic candidate must map to exactly one card. An unresolved
`review_required` row is allowed only when its frozen A2.1 review reasons are
non-empty.

## Reverse verification

Every `in_scope` or `review` card must have at least one matched A2.1 offer or a
documented `unmatched_reason`. An unexplained card blocks the gate.

The outputs are:

- `offer-to-card-mapping.json`;
- `reverse-card-coverage.json`;
- `parity-blockers.json`;
- `parity-summary.json`;
- `artifact-manifest.json`.

Rows are sorted canonically and output hashes are stable across input order.

## Controlled workflow

Prepare a ledger template from one exact A3.0 run:

```bash
HERMES_AUDIT_EXPECTED_HEAD=<exact-main-sha> \
A30_RUN_DIR=<exact-a30-run-directory> \
A31_MODE=template \
tools/run-hermes-deals-aldi-a31-parity-v01.sh
```

The generated `card-ledger-template.json` contains all 90 frozen page
identities and all 400 target candidate hints. It does not invent card regions
or automatic assignments.

After controlled visual adjudication, verify the completed ledger:

```bash
HERMES_AUDIT_EXPECTED_HEAD=<exact-main-sha> \
A30_RUN_DIR=<exact-a30-run-directory> \
A31_MODE=verify \
A31_CARD_LEDGER=<completed-card-ledger.json> \
tools/run-hermes-deals-aldi-a31-parity-v01.sh
```

Template preparation is not a parity pass. Production integration remains
blocked until verify mode reports `ALDI_A31_PARITY_PASS` with all 346 automatic
and 54 review-required candidates accounted for and zero unexplained cards.

## Safety

Both modes are offline after reading frozen local evidence. They contain no
Docker, PostgreSQL, systemd, collector, deploy, approval, publication, commit,
or push action.
