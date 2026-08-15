# EDEKA production canary control bridge

This document records the source-only GitHub control boundary for the EDEKA Patzer production canary.

## Command surface

Commands are accepted only as newly-created owner comments on issue #26:

```text
/hermes-edeka canary verify sha=<exact-current-main-40hex>
/hermes-edeka canary apply sha=<exact-current-main-40hex>
/hermes-edeka canary replay sha=<exact-current-main-40hex>
/hermes-edeka canary rollback sha=<exact-current-main-40hex>
```

The GitHub-hosted authorizer requires the command SHA to equal current `main`, requires the exact-main push CI to be completed successfully, verifies the current EDEKA canary plan remains `preparation_only` / `production_apply_authorized=false`, and revalidates the fixed +1/+3/+3 first-apply and all-zero replay contracts.

## Trust boundary

The self-hosted job receives only normalized `operation` and exact `sha` outputs from the GitHub-hosted authorizer. It does not receive the issue-comment body, a GitHub token, database credentials, or a repository checkout.

It can invoke only this fixed command path:

```text
sudo --non-interactive /usr/local/sbin/hermes-deals-edeka-production-canary-control \
  <operation> <exact-sha> <runner-temp-artifact-dir>
```

The root-owned dispatcher is intentionally **not installed or registered by this source-only bridge**. Until a separately reviewed, checksum-bound root dispatcher and least-privilege sudo policy are explicitly owner-authorized and installed on the RPi5, every self-hosted control attempt must fail closed.

The future root dispatcher remains responsible for all production-sensitive invariants: retained-evidence paths and hashes, production DB credential access, rollback backup verification, exact baseline counts, mode-bound authorization JSON generation, one-transaction execution, replay verification, exact-ID rollback, and sanitized evidence export.

## Non-authority

Merging this bridge does not authorize or perform:

- production database writes;
- Review/publication/matching/canonical writes;
- EDEKA source refetch;
- root dispatcher or sudoers installation;
- systemd/scheduler changes;
- production deployment.

Each future `verify`, `apply`, `replay`, or `rollback` command is a separate owner action and remains ineffective until the independently reviewed root capability is registered.
