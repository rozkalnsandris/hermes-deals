# Kaufland K3C sanitizer bound taxonomy

Refs: #802, #801, #799, #798, #749, #702.

## Evidence

Owner-authorized diagnostic run `33320156704` on registration/execution SHA `4f80ceb8d9c13d03da4cf97c8642dd2165831997` completed the reviewed bridge but remained fail-closed with `SANITIZER_BOUND_REJECTED`.

That receipt is control-plane evidence only. It does not expose raw validator detail and does not establish promo semantics, price identity, product identity, `nur` role, or parser #702 acceptance.

## Refinement

The validator keeps every existing acceptance condition unchanged but splits the former generic bound reason into three fixed non-semantic classes:

- `SANITIZER_COLLECTION_BOUND_REJECTED` — bounded integer/list/raw-size/sample-list limit failures;
- `SANITIZER_SAMPLE_CONSISTENCY_REJECTED` — sample/count/truncation consistency failures;
- `SANITIZER_EXACT_CARDINALITY_REJECTED` — exact-cardinality failures such as a candidate amount count not equal to one.

The reason codes contain no labels, values, HTML, product text, price values, locators, file paths, or private validator messages. Unknown failures still map to the existing bounded fallback classes and unknown `SANITIZER_*` codes remain rejected by workflow receipt inspection.

## Trust consequence

This change modifies both the trusted validator and the workflow. Any future K3C diagnostic requires a new reviewed registration anchor and the normal separately authorized sequence:

`source sync -> read-only host preflight -> runtime build -> root registration -> diagnostic`

Do not reuse the runtime/root-registration/diagnostic authorization associated with registration SHA `4f80ceb8d9c13d03da4cf97c8642dd2165831997` after this change merges.

No diagnostic replay, retained-evidence read/write, host/runtime mutation, production DB/Review/publication write, scheduler/systemd/container/Cloudflare mutation, or deploy is performed by this source-only change.

**Production deploy: NO.**
