# Public-repository readiness

Status: **PUBLIC; repository/CI security gates passed; post-switch control-plane protection audit pending**.

The owner accepted the documented privacy tradeoffs and changed `rozkalnsandris/hermes-deals` from private to public on 2026-08-08. GitHub repository metadata was re-read after the change and reports `visibility=public`.

The repository-code and CI security gates remain in force. The only remaining item in this document is the GitHub control-plane check for branch protection/rulesets and repository Actions settings, which cannot be proven from tracked files alone.

## Required gates

- [x] Run a full Git-history secret scan (`--all`) with redacted findings and zero unresolved credentials.
- [x] Review every `.github/workflows/*.yml` self-hosted trigger class. No untrusted `pull_request` code may execute on an RPi5 runner.
- [x] Keep production `deals.rozkalns.net` behind Cloudflare Access; repository visibility must not weaken application access control.
- [x] Confirm the tracked repository/history scan has no unresolved production credential, private key or embedded database password finding. Runtime `.env`, dumps, backups and common credential files remain excluded by `.gitignore`.
- [x] Review public-user-triggerable self-hosted workflows (`pull_request_target` and `issue_comment`) and document their owner-authentication / trusted-main / fixed-dispatcher boundaries.
- [x] Owner accepted that existing issue/PR history, workflow metadata and retained sanitized Actions evidence are public. Search review found credential-name/safety discussions but no credential values; GitHub-hosted secret masking and the repository's sanitization contracts remain relied upon for historical runtime logs.
- [x] Owner accepted publication of operational metadata already present in Git history, including household/store selection identifiers, RPi5/internal-path references and private-LAN topology details. These are not credentials, but they are privacy-relevant metadata.
- [x] Repository visibility changed to public on 2026-08-08 and was independently re-read as `visibility=public`.
- [ ] Re-check/re-enable branch protection/rulesets and repository Actions permissions in GitHub control-plane settings after the visibility change.

## Current security evidence

- CI uses a complete-history checkout and runs the pinned Gitleaks scanner before the backend suite.
- The current scan reports nine exact historical findings, all pinned to immutable `(rule, file, line, commit)` identities in `security/gitleaks-history-allowlist.json`; all nine were manually verified as deterministic test/provenance/sudoers fixtures. Unknown findings are zero and any new/unreviewed identity fails CI.
- The public-workflow audit currently inventories 27 workflows, 23 containing self-hosted jobs, with zero direct `pull_request` → self-hosted paths.
- Three `pull_request_target` and four `issue_comment` self-hosted workflows received manual public-repository threat review; see `docs/PUBLIC_READINESS_WORKFLOW_REVIEW.md`.
- `.env.example` contains placeholders only. Runtime `.env`, private keys, dumps, backups and common credential files are excluded by `.gitignore`.
- Cloudflare Access service credentials are GitHub secrets and must never be committed. Repository visibility is independent of the production Access policy.
- A post-switch PR CI run is required before this documentation update is merged so the full-history secret scan, workflow-safety audit and complete test suite are exercised once while the repository is already public.

## Visibility-change rule

Do not weaken RPi5 trust boundaries because the repository is public. Standard PR CI must stay on GitHub-hosted runners. Self-hosted jobs remain owner-gated, post-merge/manual/controlled operations with no untrusted PR checkout.

The remaining manual control-plane action is to verify branch protection/rulesets and repository Actions permissions in GitHub Settings. No production application deploy is required for this documentation-only state update.
