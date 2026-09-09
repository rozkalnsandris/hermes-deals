# Web Gate W0 source baseline

Issue #319 Gate W0 requires a reproducible browser/API baseline before later web performance or hardening work can claim improvement. The source-only helper added by #869 provides the deterministic **repository-side** half of that contract.

It does not complete W0 by itself.

## Deterministic source manifest

Run from an isolated checkout of the exact reviewed commit:

```bash
python tools/web_w0_baseline.py \
  --repo-root . \
  --git-sha "$(git rev-parse HEAD)" \
  --output /tmp/hermes-w0-source-baseline.json
```

The tool inventories only an explicit allowlist of current UI source/build-contract files. For each file it records:

- repository-relative path;
- byte count;
- SHA-256.

It also records a deterministic aggregate fingerprint and the exact 40-character Git SHA supplied by the operator. Identical repository bytes plus the same Git SHA produce byte-identical JSON. No timestamp or machine-local absolute path is included.

Missing files, symlinks, invalid SHA input and repository path escape fail closed.

## External evidence remains external

A source manifest emits these W0 evidence slots with `state: "not_observed"`:

- deployed `/ui` byte count and SHA;
- public/origin cache and security headers;
- desktop/mobile cold and warm browser measurements;
- startup request waterfall;
- Chrome Coverage;
- keyboard-only interaction checks.

Those fields may be satisfied only by genuine read-only observations from the relevant deployed/browser surface under a separately reviewed evidence procedure. Do not fill them from guesses, synthetic payloads, stale screenshots or source-only inference.

In particular, repository source sizes are not proof of deployed transfer sizes, and the local UI bundler is not proof of the exact public artifact currently being served.

## Sanitization boundary

The source manifest contains hashes, byte counts, contract labels and explicit evidence-state metadata only. It must not include:

- offer or API response bodies;
- product values copied from production;
- cookies or authenticated browser storage;
- credentials, tokens or Cloudflare secrets;
- fabricated Lighthouse, Web Vitals, Coverage or request-count values.

The manifest intentionally records `w0_exit_gate_satisfied_by_this_manifest: false`. Gate W0 remains open until a later real evidence phase supplies the production/browser observations required by #319.

This source-only helper changes no UI/API behavior and requires no production deploy.
