# Runner-independent RPi5 origin-path audit helper contract

Issue #834 adds a source-only, capability-specific helper contract for the future
RPi5 pull executor. It does not authorize installation or execution. The legacy
self-hosted dispatcher, installer and workflow remain unchanged until a later
owner-authorized replacement canary has been accepted.

## Fixed capability and broker interface

The only capability is `origin-path-audit`. A future RPi5 privileged broker may
invoke the installed helper with exactly:

```text
/usr/local/sbin/hermes-deals-origin-path-rpi5-pull-dispatch <registered-sha> <as-of>
```

`registered-sha` must be a lowercase 40-hex Hermes Deals commit identity and
`as-of` must be canonical `YYYY-MM-DD`. There is no command, executable path,
argv extension, environment, sudo target, repository entrypoint, URL, output
path or machine-name argument. The machine identity is source-fixed to `rpi5`.

The helper itself fixes the probe executable, `andris` execution user, public
and origin URLs, Host header, timeout and clean probe argv/environment. It never
uses `shell=True` and exposes no generic privileged execution primitive.

## Registration and provenance

Future installation must create exactly one root-owned `0600` registration at:

```text
/etc/hermes-deals-audits.d/origin-path-rpi5-pull.json
```

Its exact schema is `rozkalns.hermes-deals.origin-path-rpi5-pull-registration.v1`
and it contains only:

- `schema`;
- `capability`, exactly `origin-path-audit`;
- `registered_source_sha`, exactly the reviewed merged Hermes Deals SHA;
- `helper_sha256`, the installed helper identity;
- `probe_sha256`, the installed probe identity.

The helper and probe must be regular, non-symlink, root-owned `0755` files at
the source-fixed installed paths. Hash, ownership, mode, capability or source
identity drift fails closed before the probe runs.

Any future installer is a separate source/live slice. It must start from a clean
detached worktree at the exact merged `main` SHA, prove that SHA remains
reachable from current `origin/main`, compute the reviewed helper/probe hashes,
and prepare the fixed registration and evidence parents. Source acceptance for
#834 performs none of those installation actions and does not modify sudoers,
systemd, users, groups or runner registration.

## Evidence authority

The caller supplies no evidence path. The root is source-fixed to:

```text
/var/lib/hermes-deals-audits/origin-path-audit/evidence/rpi5
```

Both the evidence root and fixed `rpi5` machine directory must already be
root-owned non-symlink directories with mode `0700`. The leaf is derived only as
`<registered-sha>-<as-of>`. A symlink, wrong owner/mode, namespace mismatch or
pre-existing leaf fails closed; the helper neither deletes nor reuses evidence.

Only after the fixed probe has completed and its in-memory result has passed the
sanitizer may the helper create the `0700` leaf and exclusive `0600` files:

- `probe-report.json`;
- `dispatcher-manifest.json`;
- `audit-exit-code.txt`.

## Read-only probe and sanitization

The fixed probe remains `tools/hermes_deals_origin_probe.py` installed at the
reviewed root-owned path. It still performs exactly six GET probes: public and
origin variants of health, overview and current-deals endpoints. The helper
accepts only the exact target/endpoint/URL set, existing allowlisted response
headers and structured problem fields, bounded scalar values, and the existing
classification/severity/exit-code mapping.

The manifest records `production_apply_authorized=false`,
`production_database_write=false`, `production_deployment=false`,
`restart_or_configuration_mutation=false` and
`protected_values_included=false`. Raw bodies, arbitrary headers, arbitrary
environment data, service logs and probe stderr are never retained.

## Activation boundary

Merging #834 proves only the reviewed source contract. It does not install the
helper, create registration/evidence directories, execute an audit, change the
current runner sudoers path, retire a runner, retain production evidence or
activate the RPi5 privileged consumer.

After this source gate, RPi5_main must separately bind the merged helper
identity and exact two-argument interface. Any helper installation, broker
activation or genuine origin-path canary requires separate explicit LIVE
authorization. Runner retirement remains ineligible until the replacement
capability has been installed, canaried and accepted under its later gates.
