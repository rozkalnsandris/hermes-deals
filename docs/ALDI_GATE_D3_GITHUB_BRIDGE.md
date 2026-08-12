# ALDI Gate D3 GitHub bridge

## Purpose

This bridge provides one narrowly allowlisted GitHub issue-comment path for the owner-authorized read-only ALDI Gate D3 recovery inventory tracked by issue #290.

It exists because the ChatGPT GitHub connector can create owner-authenticated issue comments but does not expose GitHub Actions `workflow_dispatch` directly.

## Exact command

The only accepted command is:

```text
/hermes-aldi gate-d3 pr=281
```

The command is accepted only on issue #290 and only from GitHub owner `rozkalnsandris` with numeric ID `277435981`.

The runtime identity is intentionally frozen to merged PR #281 and merge SHA:

```text
530a6b6d2b31f635f182788ccace01003b1cbc7d
```

The bridge also requires that exact SHA to remain reachable from current `main`.

## Execution boundary

The self-hosted job invokes only the pre-existing fixed root-owned dispatcher:

```text
/usr/local/sbin/hermes-deals-aldi-gate-d3-recovery-inventory
```

The bridge has no root installer, no generic registrar and no arbitrary command/argument surface. It does not synchronize or mutate `/home/andris/hermes-deals`, `/home/andris/hermes-deals-audit-source`, retained ALDI state or production runtime.

If the RPi5 dispatcher/config is not already registered to the exact PR #281 merge SHA, the dispatcher fails closed. The bridge reports only the bounded sanitized failure stage/reason; it does not repair or bypass the registration boundary.

## Evidence and safety

The bridge accepts only the three Gate D3 inventory decisions:

- `RECOVERY_CANDIDATE_FOUND`;
- `NO_RECOVERY_CANDIDATE`;
- `AMBIGUOUS_RECOVERY_CANDIDATES`.

Successful evidence must preserve the Gate D3 dispatcher contract and exact runtime SHA. Failure evidence is bounded to sanitized error type/stage/reason metadata. The artifact is rejected if unexpected members, unsafe authority flags or oversized members are present.

The bridge never authorizes:

- raw page-image or stderr export;
- archive extraction;
- corpus/source/manifest mutation;
- parser/candidate execution outside the existing inventory tool;
- Review/database/publication writes;
- production deploy/restart;
- scheduler/systemd changes;
- generic root execution;
- B15M2 V08 actions.

## Bootstrap boundary

This bridge is deliberately execution-only. Installing or updating the root-owned Gate D3 runtime remains a separate owner/root trust-boundary action. Do not weaken the existing `github-runner` sudo policy to make registration generic.
