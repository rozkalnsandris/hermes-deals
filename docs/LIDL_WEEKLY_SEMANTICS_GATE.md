# Lidl weekly extraction semantics gate

Issue #23 adds a post-parser semantics boundary without modifying the frozen R6
or V6.3.1 parser sources.

## Why the gate exists

The frozen parser is precision-first evidence, but its row-level
`production_ready_shadow` flag is not sufficient for a new week. A row must
also be bound to the reviewed weekly physical-store page partition and pass
independent price, scope, channel and variable-weight semantics.

The canonical V6.3.1 runtime adapter now wraps `analyze_lidl_pdf()` and marks
all fresh rows review-only until a reviewed weekly profile is explicitly
applied. It preserves the original parser decision in
`parser_production_ready_shadow`.

This closes the earlier staging order leak where `accepted-physical.tsv` could
be materialized before `review-profile.json` had been applied.

## Weekly eligibility contract

`backend/app/lidl_weekly_semantics.py` requires all of the following before a
row may become production-ready:

- the weekly page-role profile is reviewed;
- the row page belongs to the exact reviewed target-page set;
- the channel is `physical_store` and no structured online signal exists;
- parser scope is `in_scope`;
- the shared generic scope contract does not exclude the title;
- unknown shared scope is manually product-reviewed;
- the frozen parser itself marked the row ready;
- store, regular and Lidl Plus price semantics are credible;
- variable-weight rows have one unambiguous unit price and explicit product
  review.

Page consensus and broad classifiers remain review hints. They cannot
independently release a row.

## Immutable profile-gated view

The raw parser scan remains immutable and fail-closed. After a complete reviewed
`review-profile.json` exists, `tools/lidl_weekly_semantic_view.py` creates a
separate content-addressable view. It never rewrites the parser scan.

The view emits:

- `semantic-rows.json` with the original parser readiness preserved;
- `accepted-physical.tsv` containing only fully eligible target-page rows;
- `review-required.tsv` for ambiguous scope, parser rejection, price ambiguity
  and unapproved unit-basis rows;
- `excluded.tsv` for out-of-target, online-only, nonphysical or explicit
  out-of-scope rows;
- `coverage-report.json` proving every input row has exactly one partition;
- `profile-binding.json` binding the view to the parser rows, summary, source
  hashes and reviewed profile;
- `manifest.json` with sorted file paths, byte counts and SHA-256 values.

The coverage contract requires `explained_count == input_row_count` and
`unexplained_count == 0`. Duplicate row identities, incomplete page partitions,
unknown review approvals or a nonempty output directory fail closed.

## Price ownership

The regression contract binds prices by card geometry. A price observation is
owned only when its centre lies inside the card. Regular prices require an
explicit `Normalpreis`, `UVP`, inline UVP or strikethrough label. Lidl Plus
prices require an explicit Lidl Plus label. More than one distinct value for a
single role is ambiguous and fails closed.

Synthetic adjacent-card regressions prove that store, regular and app prices
cannot leak to the neighbouring card.

## Variable-weight semantics

A `variable_weight_example` row retains:

- the example total as `price_eur` / `example_price_eur`;
- the selected unit price as `unit_price_eur`;
- basis quantity `1` and basis unit `kg`;
- the derived example weight in grams;
- pricing mode `example_total_plus_unit`.

Zero or multiple unit-price candidates remain review-only. These fields match
the existing `OfferCandidate` unit-basis API contract.

A variable-weight approval in `unit_basis_reviews` is bound to the exact
`semantic_row_key` SHA-256 and requires the decision
`approve_unit_basis_semantics`, reviewer, timestamp and note. Unknown or
reused identities are rejected.

## Known false negatives

The frozen fixture
`backend/tests/fixtures/lidl/issue_23_semantic_regressions_v1.json` records
explicit generic outcomes for:

- ALESTO Walnusskerne;
- LANGNESE Magnum;
- Buttercroissant;
- KINDER Maxi King.

A known title is not automatically promoted. It is either generically
classified in scope or explicitly routed to Review with a documented reason.

## Reproducible evidence

The semantic module builds evidence manifests from normalized safe paths,
sorts entries by path, rejects duplicate and case-colliding paths, and emits
canonical JSON with a deterministic SHA-256. Repeating the semantic-view build
with byte-identical inputs produces byte-identical output files and the same
manifest digest.

## Safety boundary

This change performs no production deployment, database write, approval,
publication or timer installation. Frozen parser files remain byte-for-byte
unchanged. Production activation remains a separate controlled step.
