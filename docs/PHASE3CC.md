# Phase 3Cc — normalizer-v1.1 evidence-backed enrichment

Phase 3Cb showed that normalizer-v1's low package coverage was caused by source-format gaps rather than absent data.

Accepted v1.1 enrichments:

- ALDI hyphenated metric packages such as `150-g-Becher`, `0,75-L-Flasche`, `1-kg-Packung`;
- ALDI metric multipacks such as `5x180-g-Packung` and `12x95-ml-Packung`;
- explicit `Ner-Packung` / `Ner-Rolle` counts;
- exact `Stück` as one piece;
- `kg-Preis` as a variable-weight marker without inventing a fixed quantity;
- EDEKA first-party `source_image_url` filename as fallback package evidence only for explicit metric tokens such as `150g`, `250ml`, `4x100g`, `27x0_33l`.

Not accepted:

- trailing numeric image-filename identifiers as GTIN;
- generic `Packung`, `Flasche`, `Paar`, `Pflanze` or `Garnitur` as invented quantities;
- price/unit-price arithmetic as primary package truth;
- generic fuzzy-threshold lowering.

Review-candidate logic:

- explicit matching GTIN remains strongest if it ever appears;
- exact brand-prefix + product-name relation becomes high-confidence review evidence;
- exact package agreement strengthens that review evidence;
- package conflict blocks the candidate;
- the original Phase 3Aa dual threshold (`token_jaccard >= 0.60` and `sequence >= 0.78`) is restored as review-only evidence, preserving the known `nimm2 Lachgummi` candidate;
- no review rule creates a confirmed link.

Phase 3Cca remains zero-write for all four identity tables.
