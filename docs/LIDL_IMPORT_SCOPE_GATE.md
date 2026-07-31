# Lidl import-time target scope gate (B15I3)

## Final target scope

Hermes Deals automatically publishes only physical-store offers that belong to:

- food;
- drinks;
- household consumables.

The following are excluded from automatic publication:

- personal care;
- flowers and ornamental plants;
- clothing and footwear;
- electronics;
- tools;
- furniture;
- toys and books;
- other durable non-food products.

Unknown or non-product titles are routed to Review rather than production.

## Why the extra gate exists

The parser-level `scope=in_scope` field is evidence, not sufficient authority for a
production write. B15I2 proved that 24 of 204 previously accepted rows were unsafe:
21 were out of scope and three were incomplete promotional fragments.

B15I3 adds a second import-time decision:

1. parser scope and physical-store channel remain mandatory;
2. the shared title/category classifier may veto an accepted row as `excluded`;
3. promo fragments and incomplete titles become `review`;
4. only the final `in_scope` decision reaches `OfferCandidate` persistence.

## Shared contract

`app.lidl_weekly_completeness_contract.classify_target_scope` is used by both the
weekly discovery path and the corpus importer. Personal-care terms are explicit
exclusions and are no longer treated as household consumables.

The import partition is exposed through:

- `safe_rows()` — automatic production candidates;
- `accepted_review_rows()` — accepted rows downgraded to Review;
- `accepted_excluded_rows()` — accepted rows blocked from production;
- `review_rows()` — native review rows plus import-time Review downgrades.

## Regression fixture

`tests/fixtures/lidl_b15i2_scope_204.json` is bound to classification SHA256:

`0016e56540e032deee866e01bd75bb5ae9d98d89ba6e906e23240754b9b1dbc0`

Expected partition:

- 180 automatic `in_scope`;
- 21 `excluded`;
- 3 `review`.

The fixture is a regression contract only. It does not replace future flyer
provenance, corpus promotion or Review evidence.
