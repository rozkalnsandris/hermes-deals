# Public-readiness secret-scan evidence

This branch adds a mandatory full-history credential scan to the existing CI job before the repository is considered for public visibility.

The scan:

- requires a non-shallow checkout;
- uses Gitleaks 8.30.0 pinned by OCI digest;
- extends Gitleaks default rules with Hermes Deals-specific Cloudflare Access and database/password assignment checks;
- scans all reachable Git history (`--all`);
- redacts findings and prints only rule/file/line/commit metadata on failure;
- runs inside the existing backend CI job to avoid creating an additional billed GitHub-hosted job while the repository is still private.

A green CI run is necessary but not sufficient for public visibility. Self-hosted workflow review, Actions artifact/log review, household/store metadata review and repository-protection review remain separate gates in `docs/PUBLIC_READINESS.md`.
