# Phase 2B2 — Lidl leaflet bundle/API discovery

Goal: inspect the JavaScript bundle already discovered in Phase 2B1 without browser automation.

The worker fetches the immutable `lidl.leaflets.schwarz/assets/index-*.js` bundle, stores it as a raw snapshot, and extracts:

- absolute/relative API-like URLs;
- leaflet/flyer/catalog/publication/product/page/config candidates;
- short network-related code contexts;
- a source-map URL only when the bundle explicitly publishes one.

No candidate endpoint is called automatically in this phase. This prevents accidental writes or unsupported API assumptions. Phase 2B3 will be chosen from the resulting report.

Deployment also hardens the web bind mount: after deploy/restore the Nginx `web` container is force-recreated and `/index.html` + HTTP 200 are verified. This prevents stale inode bind mounts after directory replacement during rollback.
