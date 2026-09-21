# Web M1 mobile, keyboard and accessibility evidence

Issue: #925 · Parent: #319 · Capture date: 2026-09-21

## Decision boundary

M1 reconciles the already-merged W6 accessibility baseline against the exact current-main production presentation. It is an acceptance/evidence gate, not a redesign: retailer, parser, comparison, Review, database and authorization semantics remain unchanged.

## Exact identities

- GitHub `main` at capture: `bc82c09c861fe5ce15891ca9fe7de9e23d0a41eb`.
- Deterministic frontend build SHA-256: `9079aa07c84cea1ba627013fcb1b53a1659bd374340c5bb5638cf608139f159d`.
- Production-form HTML SHA-256: `88e056cc5c5097c520ebb2e3f784eac845aff76a37e6a218ecdcb2f7d20507ad`, 302626 bytes.
- Browser: Chrome `153.0.8010.52`, DevTools protocol `1.3`.
- Viewports: mobile `390×844`; desktop `1365×768`.

## Reproducible capture

`backend/frontend/scripts/capture-m1-accessibility.mjs` is dependency-free and drives a fresh loopback-only headless Chrome instance over the DevTools protocol. The capture requires an exact release ref and production HTML SHA-256 and rejects non-loopback target URLs.

Example after serving the exact production-form UI on loopback:

```sh
cd backend/frontend
npm run acceptance:m1 -- \
  --chrome-bin /usr/bin/chromium \
  --base-url http://127.0.0.1:9190/ui/ \
  --release-ref bc82c09c861fe5ce15891ca9fe7de9e23d0a41eb \
  --release-html-sha256 88e056cc5c5097c520ebb2e3f784eac845aff76a37e6a218ecdcb2f7d20507ad
```

The committed machine evidence is `docs/evidence/web-m1/main-bc82c09c861fe5ce15891ca9fe7de9e23d0a41eb/acceptance.json`.

## Acceptance result

All captured checks passed:

- five mobile navigation actions are present at `390×844`;
- the closed shopping-list drawer is inert and `aria-hidden=true`;
- a real keyboard `Tab` produces a visible `3px solid` focus outline;
- opening the drawer removes inertness, exposes it to accessibility APIs, moves focus to `closeList`, and closing restores focus to its opener;
- the detail overlay exposes `role=dialog` / `aria-modal=true`, receives initial close-button focus, becomes inert again on close, and restores opener focus;
- `prefers-reduced-motion: reduce` matches, yields `0.01ms` transition/animation durations and `scroll-behavior:auto`;
- desktop contains one `main` landmark;
- desktop Tab/Shift+Tab wrap from the last/first drawer controls back to the first/last controls;
- computed `body` zoom is `1` at both viewports, so the historical `body { zoom:.8 }` workaround is not effective in the production presentation.

The machine evidence records `acceptance.pass=true` with an empty `failed` list.

## Privacy and mutation boundary

The harness records only release/browser identity and DOM/computed-style acceptance metrics. It does not record cookies, storage, request headers, response bodies, query strings, browser profiles or authentication state. The tested presentation is served from Lenovo loopback; no production/runtime/host/container/DB/Review/collector/scheduler/Cloudflare mutation is performed.

## M1 outcome

The merged W6 accessibility baseline satisfies the representative M1 mobile/keyboard/accessibility acceptance checks on the exact current-main production presentation. No UI behavior rewrite is required. M2 continuation remains gated on merging this evidence/tooling change.
