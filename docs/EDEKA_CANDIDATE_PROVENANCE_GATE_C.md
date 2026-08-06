# EDEKA candidate provenance — Gate C

Gate C is a shadow-only contract for issue #26. It accepts candidate rows only when every row is bound to the exact validated Gate B manifest for EDEKA Patzer.

## Required binding

- public market code `071897`;
- source/internal market ID `587881`;
- scope `family_primary_edeka`;
- exact campaign ID;
- exact source SHA256 and manifest SHA256;
- exact parser identity;
- positive page number and non-empty card ID;
- unique candidate ID.

An automatic candidate additionally requires complete provenance. Any ambiguous row must route to `review_required`. Missing, duplicate or mismatched evidence fails closed.

## Safety boundary

This gate does not acquire a live source, run a collector, write PostgreSQL or Review state, approve or publish rows, deploy, install a timer or authorize a production canary. The included fixture is synthetic contract evidence and must not be presented as a live EDEKA campaign.

The output always keeps `promotion_ready=false` and all write, approval, publication and production-apply flags false.

## Next evidence

Issue #26 still requires a real immutable regional source binding, a complete candidate/page provenance run for that source, two consecutive weekly shadow cycles, unchanged-source no-op proof, monitoring and a separately authorized exact-row canary plan.
