## FAST-LANE v2.1

- **Lane:** FAST / STRICT
- **Related work:** #...
- **Runtime effect:** NONE / READ_ONLY / MUTATION
- **Deploy required:** YES / NO
- **Migration required:** YES / NO
- **Trust-boundary change:** YES / NO

## Scope

Describe one coherent acceptance story. FAST may batch 2-5 closely related same-risk work items. Ambiguous extraction/matching remains fail-closed/Review Queue; do not trade precision for batching.

## Validation

List focused validation first and relevant Ready validation separately.

## Ready receipt

Complete once when Ready:

- Base / current main:
- Exact head SHA:
- CI/checks:
- Unresolved review threads:
- Reviewed scope/diff:
- Runtime/deploy/migration classification:
- Exact next gate:

Merge is not authorized by this PR. Merge never authorizes production deploy, DB migration/write, retained mutation, scraper/runtime activation, scheduler/systemd/host mutation, secrets or Cloudflare mutation.
