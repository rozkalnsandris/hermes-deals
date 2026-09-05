# Kaufland K3C runtime-failure remediation

Refs: #770, #749, #741, #769, Actions run `32769792327`.

## Incident boundary

The first owner-authorized K3C promo-structure execution on registration/execution SHA
`b65fdb4eb98eaee223083b5edfffae870cfaaafe` passed the GitHub-hosted authorization
job, invoked the fixed RPi5 dispatcher, and then failed closed with:

- `BRIDGE_EXECUTION_STATUS=BLOCKED`;
- `DIAGNOSTIC_STATUS=UNAVAILABLE`;
- `REASON_CODE=DIAGNOSTIC_PROCESS_EXIT_UNEXPECTED`;
- diagnostic process exit `1`;
- public promo not promoted;
- production deploy and host mutation not authorized.

The sanitized artifact did not contain the private diagnostic stderr. Therefore the
exact underlying Python exception is not proven and must not be guessed.

The one-shot diagnostic authorization used by run `32769792327` is consumed. This
source remediation does not authorize a retry.

## Remediation contract

A future separately authorized diagnostic uses two fail-closed runtime boundaries.

### 1. Same-runtime import preflight

Before invoking the diagnostic against retained evidence, the root-owned dispatcher
imports `app.kaufland_k3c_promo_structure_diagnostic` using the same fixed execution
identity as the real diagnostic:

- unprivileged user `andris`;
- `/usr/bin/env -i`;
- fixed `/usr/bin/python3`;
- working directory `/home/andris/hermes-deals/backend`;
- `PYTHONDONTWRITEBYTECODE=1`;
- `PYTHONNOUSERSITE=1`;
- `PYTHONHASHSEED=0`.

A failed import does not expose its stderr. The bridge emits only the bounded reason
`DIAGNOSTIC_RUNTIME_IMPORT_FAILED` and remains `BLOCKED`.

This preflight does not select a different interpreter or dependency path. Any future
runtime-contract change requires separate evidence and review.

### 2. Unexpected diagnostic exception sanitization

After import succeeds, the diagnostic preserves the existing exact handling of
`K3CDerivationError`, `KauflandSourceDiscoveryError`, and
`KauflandSourceCardContractError`.

Any other ordinary Python `Exception` is converted to the same validated BLOCKED
shape already accepted by the bridge validator:

- diagnostic exit `20`;
- reason `UNEXPECTED_DIAGNOSTIC_EXCEPTION`;
- `evidence_only=true`;
- `promo_role_promoted=false`;
- all network/write/deploy/runtime mutation flags remain false.

The exception class, message, traceback, retained path, product text, raw HTML, and
price values are not added to the public JSON payload.

`BaseException` subclasses such as process termination are not reclassified as a
semantic diagnostic result; the outer bridge continues to fail closed on unexpected
process exits.

## Acceptance for this source batch

- focused tests prove unexpected `RuntimeError` becomes validator-compatible BLOCKED
  evidence without leaking its message;
- focused tests prove known K3C reason codes remain unchanged;
- focused tests prove the import preflight precedes the retained diagnostic invocation
  and uses the same fixed isolated Python environment;
- existing bridge validator continues to reject unsafe fields and promo promotion;
- repository CI must pass on the exact PR head;
- no diagnostic execution, retained read/write, parser #702 implementation, production
  DB/Review/publication write, deploy, scheduler/systemd change, or host mutation occurs
  in this source batch.

## Post-merge authority boundary

A merge of this remediation would still authorize **no** RPi source sync, root bridge
registration, retained diagnostic execution, production deploy, or other live mutation.
Each required live action must be separately owner-authorized against fresh exact
GitHub/runtime evidence. A future diagnostic authorization must be new because run
`32769792327` consumed the prior one-shot authorization.

**Production deploy: NO.**
