# Public-repository readiness

Status: **PUBLIC; repository/CI security gates passed; active `main` ruleset enforcement verified; final fork-workflow approval confirmation pending**.

The owner accepted the documented privacy tradeoffs and changed `rozkalnsandris/hermes-deals` from private to public on 2026-08-08. GitHub repository metadata was re-read after the change and reports `visibility=public`.

The repository-code and CI security gates remain in force. The active `Protect main` ruleset was additionally exercised with a real documentation-only pull request after the visibility change.

## Required gates

- [x] Run a full Git-history secret scan (`--all`) with redacted findings and zero unresolved credentials.
- [x] Review every `.github/workflows/*.yml` self-hosted trigger class. No untrusted `pull_request` code may execute on an RPi5 runner.
- [x] Keep production `deals.rozkalns.net` behind Cloudflare Access; repository visibility must not weaken application access control.
- [x] Confirm the tracked repository/history scan has no unresolved production credential, private key or embedded database password finding. Runtime `.env`, dumps, backups and common credential files remain excluded by `.gitignore`.
- [x] Review public-user-triggerable self-hosted workflows (`pull_request_target` and `issue_comment`) and document their owner-authentication / trusted-main / fixed-dispatcher boundaries.
- [x] Owner accepted that existing issue/PR history, workflow metadata and retained sanitized Actions evidence are public. Search review found credential-name/safety discussions but no credential values; GitHub-hosted secret masking and the repository's sanitization contracts remain relied upon for historical runtime logs.
- [x] Owner accepted publication of operational metadata already present in Git history, including household/store selection identifiers, RPi5/internal-path references and private-LAN topology details. These are not credentials, but they are privacy-relevant metadata.
- [x] Repository visibility changed to public on 2026-08-08 and was independently re-read as `visibility=public`.
- [x] Configure an active `Protect main` branch ruleset targeting the default branch, with an empty bypass list, deletion protection, linear history, pull-request-only changes, zero required human approvals, the two CI jobs required, no up-to-date-before-merge requirement, force-push protection, and squash as the intended merge method.
- [x] Exercise the ruleset with a real PR and verify that GitHub refuses a squash merge while both required checks are still in progress.
- [x] Keep default workflow token permissions read-only for repository contents/packages and keep `Allow GitHub Actions to create and approve pull requests` disabled.
- [ ] Confirm that `Approval for running fork pull request workflows from contributors` is saved as `Require approval for all external contributors`.

## Current security evidence

- CI uses a complete-history checkout and runs the pinned Gitleaks scanner before the backend suite.
- The current scan reports nine exact historical findings, all pinned to immutable `(rule, file, line, commit)` identities in `security/gitleaks-history-allowlist.json`; all nine were manually verified as deterministic test/provenance/sudoers fixtures. Unknown findings are zero and any new/unreviewed identity fails CI.
- The public-workflow audit currently inventories 27 workflows, 23 containing self-hosted jobs, with zero direct `pull_request` → self-hosted paths.
- Three `pull_request_target` and four `issue_comment` self-hosted workflows received manual public-repository threat review; see `docs/PUBLIC_READINESS_WORKFLOW_REVIEW.md`.
- `.env.example` contains placeholders only. Runtime `.env`, private keys, dumps, backups and common credential files are excluded by `.gitignore`.
- Cloudflare Access service credentials are GitHub secrets and must never be committed. Repository visibility is independent of the production Access policy.
- Post-switch PR #354 exercised the full-history secret scan, workflow-safety audit and complete test suite while the repository was already public.
- Ruleset smoke-test PR #357 was deliberately offered for squash merge before its required checks completed. GitHub rejected the merge with a repository-rule violation stating that 2 of 2 required status checks were still in progress. This proves the required-check gate is active on `main` for the normal merge path.

## Visibility-change rule

Do not weaken RPi5 trust boundaries because the repository is public. Standard PR CI must stay on GitHub-hosted runners. Self-hosted jobs remain owner-gated, post-merge/manual/controlled operations with no untrusted PR checkout.

No production application deploy is required for this documentation-only control-plane verification.
