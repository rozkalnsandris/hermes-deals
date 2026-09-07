# Netto #19 runner-independent production read-only helper

This document defines a **source-only** contract for a future RPi5 capability broker to execute the existing Netto #19 production read-only verification semantics without inheriting the persistent public-repository self-hosted runner's output-path authority.

The source gate does not authorize installation or execution. It does not modify sudoers, systemd, users/groups, Docker configuration, database state, credentials, GitHub App permissions, runner registration, deployment state, retained production evidence, or any other host/runtime state. Any installation, registration, broker binding, genuine verification run, evidence retention, or runner retirement requires a separate fresh source gate and/or explicit LIVE authorization as applicable.

## Capability boundary

The future privileged entrypoint is fixed to:

```text
/usr/local/sbin/hermes-deals-netto-19-production-readonly-pull-dispatch <registered-sha>
```

The only caller-controlled value is `<registered-sha>`, which must be exactly 40 lowercase hexadecimal characters and must exactly match the registered Hermes Deals source SHA.

The caller cannot provide a command, executable, script path, repository entrypoint, argv extension, environment, sudo target, URL, database query, Docker target, output directory, evidence file name, machine namespace, or run identifier.

The helper capability is fixed to:

```text
netto-19-production-readonly-verify
```

The fixed machine namespace is:

```text
rpi5
```

## Exact registration

A later LIVE installation may create this root-owned registration file:

```text
/etc/hermes-deals-audits.d/netto-19-production-readonly-pull.json
```

Its complete schema is:

```json
{
  "schema": "rozkalns.hermes-deals.netto-19-production-readonly-pull-registration.v1",
  "capability": "netto-19-production-readonly-verify",
  "registered_source_sha": "<40-hex merged/reviewed source SHA>",
  "helper_sha256": "<64-hex installed helper SHA-256>",
  "verifier_sha256": "<64-hex installed Netto #19 verifier SHA-256>"
}
```

No additional registration fields are accepted. The helper requires the registration to be a regular root-owned `0600` file and fails closed on source/provenance mismatch.

The source-fixed installed identities are:

```text
helper:
  /usr/local/sbin/hermes-deals-netto-19-production-readonly-pull-dispatch
  root:root 0755

verifier:
  /usr/local/libexec/hermes-deals-audits/netto-19-production-readonly-v1/netto_19_production_readonly_verify.py
  root:root 0555
```

The helper verifies both SHA-256 identities before loading the verifier.

## Why this is separate from the legacy runner path

The legacy `.github/workflows/netto-19-production-readonly-verify.yml`, `tools/runner/install-netto-19-production-readonly-verifier.sh`, and `tools/runner/netto_19_production_readonly_verify.py` intentionally remain unchanged by this source gate.

That legacy path accepts a runner-created evidence directory under:

```text
/home/github-runner/_work/_temp/hermes-netto-19-production-verify-*
```

and returns the receipt to `github-runner`. Broadening those checks in place would preserve or widen the old runner privilege boundary instead of proving a replacement.

The new helper therefore uses the hash-pinned installed verifier as a fixed Python implementation dependency, invokes only its existing read-only verification functions, rebuilds the same receipt contract, validates/sanitizes that receipt, and persists it under a source-fixed root. It does **not** invoke the verifier's legacy `--evidence-dir` CLI and does not depend on a GitHub runner temp directory or runner ownership.

Because the verifier itself is hash-pinned in the registration, any verifier source change requires an intentional new reviewed registration identity before the helper can execute.

## Read-only execution contract

The fixed verifier semantics remain the existing Netto #19 checks:

- production Git identity/status captured before and verified unchanged after;
- fixed production Docker Compose services inspected;
- PostgreSQL sessions enforce `default_transaction_read_only=on`;
- selected production tables are hashed before and after and must remain unchanged;
- application health/UI endpoints are GET-only probes;
- immutable Netto snapshot identities and hashes are verified;
- current and historical daily/weekly/UI contracts are checked;
- review-only policy is checked;
- no deploy, review write, publication, scheduler change, host-root change, or production mutation is permitted.

The helper accepts a receipt only when all required contract fields pass and all mutation postconditions are exactly false.

## Evidence boundary

The future evidence root is fixed to:

```text
/var/lib/hermes-deals-audits/netto-19-production-readonly-v1/evidence/rpi5
```

Both the parent evidence directory and `rpi5` machine directory must already exist as regular root-owned `0700` directories. The helper never accepts an evidence path from the caller.

For each run, the helper derives an internal UTC run identifier and creates exactly one new directory:

```text
<registered-sha>-<YYYYMMDDTHHMMSSffffffZ>
```

under the fixed `rpi5` root. Symlinks, wrong ownership/modes, wrong machine namespaces, traversal, and pre-existing destinations fail closed. There is no overwrite/retry fallback.

A successful source contract writes only:

```text
receipt.json
dispatcher-manifest.json
verify-exit-code.txt
```

using exclusive creation and mode `0600`.

The sanitized manifest records only capability/source/run identity, helper/verifier SHA-256 identities, receipt SHA-256, sanitization status, and explicit false mutation postconditions. It contains no secret, credential, arbitrary command, arbitrary environment, response body, database row payload, or caller-selected path.

## Future RPi5 binding

A future `RPi5_main` source gate may bind a capability-specific privileged consumer to exactly:

```text
/usr/local/sbin/hermes-deals-netto-19-production-readonly-pull-dispatch <registered-sha>
```

That later binding must independently prove the exact merged Hermes Deals source/helper/verifier identities and keep generic shell/SSH/sudo execution unavailable.

This source merge alone does not create that binding and does not make the helper live.

## Legacy compatibility and gates

The legacy workflow, installer and verifier remain unchanged until a separately authorized replacement canary is installed, bound, executed and accepted.

This source gate alone:

- does not install the helper or registration;
- does not create the evidence directories;
- does not execute Docker, PostgreSQL, HTTP or Git probes;
- does not change sudoers, systemd, users/groups or runner state;
- does not retire or deregister any runner;
- does not create READY/LIVE-AUTH evidence;
- does not authorize retained-evidence writes or a production verification run;
- does not authorize merge unless the owner separately grants MERGE authority.

After source merge, any host installation/binding and the first genuine broker execution remain separate explicit LIVE authorization gates. Runner retirement remains later still and requires proven replacement evidence for all in-scope capabilities.
