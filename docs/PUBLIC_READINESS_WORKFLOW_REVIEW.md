# Public-readiness review of self-hosted workflow triggers

Review date: 2026-08-08

Result: **PASS with owner-only public trigger boundary**.

## Automated inventory

The CI public-workflow audit enumerates all workflow files and fails if any self-hosted runner is directly reachable from a `pull_request` event. Self-hosted `pull_request_target` and `issue_comment` workflows are deliberately surfaced for manual review because those events can originate from public-repository activity.

Current reviewed inventory:

- 27 workflow files total;
- 23 workflows contain a self-hosted job;
- 0 self-hosted workflows are directly triggered by `pull_request`;
- 3 self-hosted workflows use `pull_request_target` and require review;
- 4 self-hosted workflows use `issue_comment` and require review.

## `pull_request_target` review

### `netto-geometry-rpi5-replay.yml`

PASS. The self-hosted replay depends on a GitHub-hosted authorizer. Authorization requires the exact owner login and numeric account ID to apply the exact audit label, requires a merged PR into this repository's `main`, requires the merge SHA to remain reachable from current `main`, and requires successful exact-SHA `main` CI. The self-hosted job does not checkout repository code and calls a fixed root-owned dispatcher with the registered merge SHA.

### `netto-ownership-separator-rpi5-audit.yml`

PASS. Same owner-login + numeric-ID label gate, merged-main reachability and exact successful `main` CI boundary. The self-hosted job has `permissions: {}`, performs no checkout, and invokes only the dedicated root-owned dispatcher.

### `netto-shadow-rpi5-audit.yml`

PASS. The exact owner login and numeric account ID must apply the exact audit label, and the requested PR must already be merged into and reachable from current `main`. The self-hosted job performs no repository checkout and invokes only the fixed root-owned read-only audit dispatcher. Unlike the two workflows above, this older workflow does not separately require an exact successful main-CI run; its owner-only post-merge trigger and fixed-dispatcher/no-checkout boundary are therefore the controlling public-repository trust gate.

## `issue_comment` review

### `hermes-command-bridge.yml`

PASS. Public comments can make the GitHub-hosted authorizer start, but authorization fails unless both the sender login and immutable numeric account ID match the owner. The command grammar is allowlisted and exact, the referenced PR must already be merged into this repository's `main` and reachable from current `main`, and the self-hosted job invokes only the fixed Gate A dispatcher. Authorizer code is checked out from the default branch, not the commenter's branch.

### `hermes-deals-307-bridge.yml`

PASS. The authorizer requires the exact owner login and numeric account ID, exact issue number, and exact command. The runtime SHA is fixed and must remain reachable from current `main`. The self-hosted job has `permissions: {}` and invokes only the installed root-owned #307 dispatcher.

### `hermes-gate-b-plan-bridge.yml`

PASS. The authorizer explicitly checks out `main`, requires exact owner login + numeric ID, accepts only the allowlisted command grammar, requires the referenced PR to be merged into/reachable from `main`, and verifies exact registered Gate B blobs at both the requested merge SHA and current `main` before queuing the self-hosted planner. The RPi5 path is read-only planning through a fixed dispatcher.

### `hermes-lidl-source-refresh-audit.yml`

PASS. Authorization is inline on a GitHub-hosted job and requires exact owner login + numeric ID, exact issue number and exact command grammar. The referenced PR must be merged into/reachable from this repository's `main`. The self-hosted job has `permissions: {}` and invokes the fixed read-only source-refresh dispatcher; raw source export and production/DB/Review mutations are contractually rejected.

## Public-repository invariant

A future workflow that combines `pull_request` with a self-hosted runner must fail CI. A future self-hosted workflow using `pull_request_target` or `issue_comment` must be treated as security-sensitive and receive the same owner-authentication, trusted-main-code, no-untrusted-checkout and fixed-dispatcher review before merge.

This review does not authorize a repository-visibility change by itself. Git-history secret scanning, artifact/log privacy, household/operational metadata privacy and post-visibility branch/ruleset verification remain separate gates.
