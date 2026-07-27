# Phase 1 — runbook

## Goal

Prove the foundation and retailer access before writing fragile parsers. No retailer-specific offer parser is considered production-ready in Phase 1.

## Install

The deploy script creates `.env`, builds the backend, starts PostgreSQL/API/Nginx, applies Alembic migration `0001_phase1`, runs unit tests, and performs all four probes.

## Re-run probes

```bash
cd ~/hermes-deals
make probe
```

## Verify

```bash
cd ~/hermes-deals
make verify
```

## Diagnostics page

Default LAN URL:

```text
http://192.168.0.180:9128/
```

API docs:

```text
http://192.168.0.180:9128/api/docs
```

## Meaning of strategy hints

- `json_candidate`: direct structured JSON looks possible
- `http_html_candidate`: direct HTTP HTML parser looks promising
- `html_needs_inspection`: page loads but needs manual inspection
- `blocked_needs_browser_or_headers`: likely Playwright/session/header fallback
- `network_error`: DNS/TLS/network issue
- `manual_review`: unexpected response

## Important

The Netto URL in Phase 1 is a Dortmund sample branch used only to prove the data path. It is not yet claimed to be the family's preferred Netto. EDEKA also needs the family's concrete market before production scoring.
