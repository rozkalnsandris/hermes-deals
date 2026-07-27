# Phase 2B3 — Lidl public flyer API validation

Goal: prove the data path exposed by the Lidl leaflet viewer before writing a Lidl offer parser.

Evidence from the live viewer bundle:

- API base: `https://endpoints.leaflets.schwarz`
- API version: `v4`
- leaflet detail path observed by the viewer family: `/v4/flyer`
- no Playwright is required for this phase

The worker now:

1. reads the latest Phase 2B1 leaflet keys;
2. performs read-only GET probes against the public v4 flyer endpoint;
3. saves every raw response and SHA-256;
4. introspects flyer metadata, pages, OCR `keyWords`, `altText`, product arrays and related flyers;
5. optionally probes `/v4/overview?client_locale=lidl/de-DE` for future weekly discovery;
6. writes no Lidl offers to PostgreSQL yet.

Hard gate: at least one leaflet must return usable JSON with page data. If this gate passes, Phase 2B4 can implement the Lidl parser from the actual German payload shape instead of assumptions.
