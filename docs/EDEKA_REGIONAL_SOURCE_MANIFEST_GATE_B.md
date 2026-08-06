# EDEKA regional source manifest — Gate B

This gate validates one proposed regional weekly source manifest before any EDEKA collection, Review write, database write, publication or production action.

## Fixed family binding

Every manifest must remain bound to:

- retailer `edeka`;
- public market code `071897`;
- source/internal market ID `587881`;
- scope `family_primary_edeka`;
- official HTTPS source hosted on `edeka.de` or a subdomain;
- an explicit campaign ID and bounded validity window;
- exact source and manifest SHA256 values;
- an explicit parser identity.

Fallback to another EDEKA market is forbidden.

## Observable source states

The manifest accepts only these states:

- `available`;
- `not_published_yet`;
- `source_unavailable`;
- `evidence_mismatch`;
- `parser_failed`;
- `review_pending`.

Only `available` and `review_pending` are eligible for later shadow processing. No state authorizes a write or production apply. Missing or failed evidence must never appear as verified zero offers.

## Safety

The gate requires all of the following to remain false:

- database writes;
- Review writes;
- automatic approval;
- automatic publication;
- production apply.

Ambiguous rows must remain `review_required`.

## Scope boundary

This PR defines and tests the fail-closed manifest contract only. The fixture uses synthetic hashes and an example campaign identity; it is not proof that the live authoritative regional source has been acquired. A later bounded step must bind real immutable source evidence before two-week shadow execution.
