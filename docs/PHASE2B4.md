# Phase 2B4 — Lidl flyer structure correction

Phase 2B3 proved that Lidl Germany exposes the current and next weekly flyers through the public read-only endpoint:

`https://endpoints.leaflets.schwarz/v4/flyer?flyer_identifier=...`

The first inspector assumed `flyer.products` would be an array. The live payload shows that product data can be object-shaped and product details can also be embedded inside page links. Phase 2B4 fixes the inspector before any Lidl database writes are allowed.

This phase:

1. accepts both array- and object-shaped `products` collections;
2. reports the actual collection type and structured product count;
3. walks every page link and counts embedded `productDetails` records;
4. records small structured product samples (id, title, brand, price, image/url);
5. records price-like tokens from page `keyWords` to assess the remaining grocery-only gap;
6. writes no Lidl offers to PostgreSQL yet;
7. keeps Netto regression, ownership, HTTP 200 and container health gates.

Hard gate: at least one live German flyer must expose structured product data either through the root product collection or through page-link `productDetails`.

Next decision:

- if structured records cover grocery offers sufficiently, Phase 2B5 can write the first Lidl collector;
- if structured records mainly cover clickable non-food products, Phase 2B5 will add a deterministic `keyWords`/page-text parser for grocery offers while preserving structured records when available.
