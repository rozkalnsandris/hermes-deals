# Dated orientation — 2026-07-27

This file is orientation only. Verify every item against newer project/runtime evidence before acting.

- Active work is Hermes Deals Phase 5G around Lidl full-card semantics and store/region binding.
- The latest evidence mentioned in the working conversation included a B15A v02 full-card-semantics artifact and a B15B v10b1 Lidl store-region-binding JSON/log pair dated 2026-07-27.
- The unresolved issue is not simply "find a numeric region id". The task is to prove how the selected Lidl family branch/store is represented across page state, URL parameters, cookies/storage, requests, and source payloads without conflating store identity with region/warehouse/zone identity.
- Netto family-primary external store id 5659 is established project context; historical 6071 must remain historical rather than becoming the active family store again.
- Core design constraints remain immutable source snapshots/provenance and controlled production writes.

Before implementing B15B, locate the newest available audit/log/JSON and build a fact table of each identifier and the observation that proves its meaning.
