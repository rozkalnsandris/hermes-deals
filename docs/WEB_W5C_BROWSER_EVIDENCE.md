# Web W5C browser/CSS evidence

Issue: #922 · Parent: #319 · Capture date: 2026-09-20

## Decision boundary

W5C exists to establish a browser-evidence boundary before destructive CSS consolidation. It does **not** authorize CSS deletion by itself, and static search is not dead-CSS evidence.

This evidence set exercises the required Weekly, Deals, shopping-list drawer, and deal-detail flows at desktop and narrow/mobile viewports. It records CSS rule-usage Coverage plus stable screenshots without recording authenticated browser state.

## Exact identities

- Current GitHub `main` at capture: `924bc354df8516443b3939599448b6c8c93328b9`.
- Current-main deterministic production bundle: SHA-256 `88e056cc5c5097c520ebb2e3f784eac845aff76a37e6a218ecdcb2f7d20507ad`, 302626 bytes.
- Deployed API image revision: `4a4ec0ae1ec4501d7de9262302bc3ee43a7ab120`.
- Deployed API image ID: `sha256:10b588cc165fb845509cd2e9bdc68dd9cab5c13b7aa81509b75a126d5f5775b5`.
- Deployed tag: `hermes-deals-api:main-4a4ec0ae1ec4`.
- RPi5 source checkout observed at capture: clean `main` at `75bd01b54459c72bc5bed90a3ee3f6e80b271371`.
- Browser: Chrome `153.0.8010.52`, DevTools protocol `1.3`.
- UI identity: `reference-v1` / `minimal-v2` / `control-room-v1`.

## Capture surfaces

Two surfaces are deliberately preserved:

1. **Deployed-release baseline.** A Lenovo loopback SSH local-forward exposed RPi5 `127.0.0.1:9128` as local `127.0.0.1:19128`. The browser only performed read-only navigation/interactions. This surface is bound to deployed image revision `4a4ec0ae…`, not to current `main`.
2. **Current-main presentation.** The exact current-main W3 frontend build was inserted into a copied UI directory and passed through `app.ui_bundle` to produce the production-form HTML. It was served on Lenovo `127.0.0.1:19129`; API GET/HEAD requests were proxied to the RPi5 loopback forward, while POST/PUT/PATCH/DELETE were rejected with HTTP 405.

Current-main browser evidence is therefore bound to current presentation source while reading existing production data without a production mutation. The deployed-release set remains a separate runtime baseline because UI source changed between `4a4ec0ae…` and `924bc354…`.

Each surface captured:

- desktop viewport `1365×768`;
- mobile viewport `390×844`;
- Weekly overview;
- Deals catalog after normal mode interaction;
- shopping-list drawer opened without adding/removing items;
- deal-detail overlay opened without list/source actions.

Coverage used Chrome DevTools `CSS.startRuleUsageTracking` / `CSS.stopRuleUsageTracking`. Screenshots and interaction manifests bind the exact viewport and release metadata.

## Current-main Coverage result

| Capture | Coverage entries | Used entries | Observed-unused entries | Observed rule bytes | Total CSS bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Desktop | 396 | 396 | 0 | 67553 | 153555 |
| Mobile | 716 | 716 | 0 | 82999 | 153555 |

Across both current-main captures there are 592 unique rule ranges. All 592 were observed used in at least one capture; zero were returned as observed-unused. The merged observed-rule range is 83939 bytes. The remaining 69616 stylesheet bytes are **not classified as dead**: they can include unexercised rules, whitespace/comments, and bytes outside the returned rule ranges.

Candidate inventory:

- **Observed used:** the 592 unique current-main rule ranges returned as used across desktop/mobile.
- **Observed unused in a captured path:** none returned by these representative captures.
- **Unknown / not exercised:** all remaining CSS bytes/rules not proven used or unused by these paths.
- **Safe destructive consolidation candidates:** none established by W5C.

The deployed-release evidence is retained for comparison but does not override the current-main result.

## Visual and cascade interpretation

The committed screenshots provide the representative visual record for each required state at both viewports. Current-main Weekly intentionally differs from the older deployed release because the source added explicit retailer trust-state disclosure; that source drift is why cleanup decisions are based on the current-main capture rather than pixel identity with the deployed release.

No cascade/source-order change is justified here. Preserve the W5 target hierarchy `tokens -> base -> layout -> controls -> components -> features -> responsive -> utilities`, and treat source order, specificity, responsive conditions, and accessibility overrides as dependencies before any future consolidation. The historical `body { zoom: .8 }` source rule remains outside this gate and is not removed by #922.

## Evidence and privacy

Machine manifest: `docs/evidence/web-w5c/manifest.json`.

- `docs/evidence/web-w5c/release-4a4ec0ae1ec4501d7de9262302bc3ee43a7ab120/` contains the deployed-release baseline.
- `docs/evidence/web-w5c/main-924bc354df8516443b3939599448b6c8c93328b9/` contains the current-main presentation evidence used for the cleanup decision.

The Coverage documents explicitly record that cookies, storage, request headers, response bodies, and query strings were not retained. The screenshots contain only the rendered Hermes Deals UI and public offer data. No Cloudflare session state or browser profile is committed.

## W5C outcome and next gate

W5C satisfies the evidence boundary but does **not** justify a destructive CSS cleanup PR. The correct result is to preserve the current cascade and move the parent Web plan to M1 mobile/keyboard/accessibility work after this evidence/tooling PR is merged. Any later CSS deletion requires new representative evidence that actually identifies a bounded unused candidate and proves interaction/visual parity.
