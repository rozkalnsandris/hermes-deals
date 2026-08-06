# EDEKA market binding — Gate A

Issue #26 starts with a behavior-neutral identity gate for the family market.

Authoritative binding:

- retailer: EDEKA;
- market: EDEKA Patzer;
- public market code: `071897`;
- source/internal market ID: `587881`;
- scope: `family_primary_edeka`.

The validator fails closed when any market identity changes, fallback is enabled, immutable source manifest/campaign/SHA/parser identity is not required, or ambiguous rows are allowed outside Review.

This gate does not discover or fetch a leaflet, change a collector, write Review or PostgreSQL data, approve/publish offers, deploy production, install a scheduler, or authorize a canary. Later #26 gates must bind every source manifest and candidate to this exact identity before weekly shadow execution.
