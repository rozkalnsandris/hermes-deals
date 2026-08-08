# Public-repository readiness

Status: **READY FOR OWNER PRIVACY DECISION; visibility remains private**.

The security gates that can be proven from repository code and CI are now in place. The repository must remain private until the remaining privacy/visibility checks below are explicitly accepted and the post-switch protection check can be performed.

## Required gates

- [x] Run a full Git-history secret scan (`--all`) with redacted findings and zero unresolved credentials.
- [x] Review every `.github/workflows/*.yml` self-hosted trigger class. No untrusted `pull_request` code may execute on an RPi5 runner.
- [x] Keep production `deals.rozkalns.net` behind Cloudflare Access; repository visibility must not weaken application access control.
- [x] Confirm the tracked repository/history scan has no unresolved production credential, private key or embedded database password finding. Runtime `.env`, dumps, backups and common credential files remain excluded by `.gitignore`.
- [x] Review public-user-triggerable self-hosted workflows (`pull_request_target` and `issue_comment`) and document their owner-authentication / trusted-main / fixed-dispatcher boundaries.
- [ ] Accept that existing issue/PR history, workflow metadata and retained sanitized Actions evidence may become public. Search review found credential-name/safety discussions but no credential values; GitHub-hosted secret masking and the repository's sanitization contracts remain relied upon for historical runtime logs.
- [ ] Accept publication of operational metadata already present in Git history, including household/store selection identifiers, RPi5/internal-path references and private-LAN topology details. These are not credentials, but they are privacy-relevant metadata.
- [ ] Change repository visibility to public only after the two privacy items above are accepted.
- [ ] Immediately re-check/re-enable branch protection/rulesets and Actions permissions after the visibility change.

## Current security evidence

- CI uses a complete-history checkout and runs the pinned Gitleaks scanner before the backend suite.
- The current scan reports nine exact historical findings, all pinned to immutable `(rule, file, line, commit)` identities in `security/gitleaks-history-allowlist.json`; all nine were manually verified as deterministic test/provenance/sudoers fixtures. Unknown findings are zero and any new/unreviewed identity fails CI.
- The public-workflow audit currently inventories 27 workflows, 23 containing self-hosted jobs, with zero direct `pull_request` → self-hosted paths.
- Three `pull_request_target` and four `issue_comment` self-hosted workflows received manual public-repository threat review; see `docs/PUBLIC_READINESS_WORKFLOW_REVIEW.md`.
- `.env.example` contains placeholders only. Runtime `.env`, private keys, dumps, backups and common credential files are excluded by `.gitignore`.
- Cloudflare Access service credentials are GitHub secrets and must never be committed. Repository visibility is independent of the production Access policy.

## Visibility-change rule

Do not weaken RPi5 trust boundaries to make the repository public. Standard PR CI must stay on GitHub-hosted runners. Self-hosted jobs remain owner-gated, post-merge/manual/controlled operations with no untrusted PR checkout.

The next action is an explicit owner privacy decision, followed by the GitHub visibility switch and an immediate protection audit.
