# Phase 2B1 — Lidl source discovery

Goal: determine a stable Lidl data path before writing a product parser.

The current public Lidl landing page links into the interactive `/l/prospekte/.../view/flyer/page/N` viewer. Phase 2B1 therefore:

1. takes a fresh immutable Lidl landing snapshot;
2. extracts all linked flyer pages visible in HTML/hydration payloads;
3. probes a small number of those pages with plain HTTP;
4. inventories candidate API/JSON/catalog/leaflet URLs found in the landing/flyer HTML;
5. stores a JSON discovery report under `data/raw/lidl-analysis/`;
6. fails closed if no leaflet link or reachable flyer page is found.

No Playwright is installed or used in this phase. No Lidl offers are inserted into the offer table yet.
