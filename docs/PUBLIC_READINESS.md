# Public-repository readiness

Status: **BLOCKED pending full-history secret scan and public-runner review**.

This repository may be changed from private to public only after all gates below pass.

## Required gates

- [ ] Run a full Git-history secret scan (`--all`) with redacted findings and zero unresolved credentials.
- [ ] Review every `.github/workflows/*.yml` self-hosted job. No untrusted `pull_request` code may execute on an RPi5 runner.
- [ ] Keep production `deals.rozkalns.net` behind Cloudflare Access; repository visibility must not weaken application access control.
- [ ] Confirm no production credential, `.env`, private key, database dump, raw runtime evidence or backup is tracked in any reachable commit.
- [ ] Confirm issue/PR history and Actions artifacts/logs contain no credential material that would become public.
- [ ] Review whether household/store identifiers currently documented in the repository are acceptable to publish.
- [ ] Re-check branch/ruleset protection immediately after any visibility change.

## Current observations

- Runtime `.env`, keys, dumps and common credential files are excluded by `.gitignore`.
- `.env.example` uses placeholders only.
- Cloudflare Access service credentials are documented as GitHub secrets and must never be committed.
- At least one RPi5 audit workflow uses an owner/merged-PR/exact-main-CI authorization gate and a no-checkout self-hosted job with `permissions: {}`. Every other self-hosted workflow must receive the same public-repository threat-model review before visibility changes.

Do not change repository visibility until every checkbox above is complete.
