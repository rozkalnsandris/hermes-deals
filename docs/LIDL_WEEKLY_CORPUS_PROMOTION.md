# Lidl weekly immutable corpus observation promotion

B15H4 promotes exactly one already reviewed `STAGED_SCAN_READY` observation
from the Lidl staging area into the matching immutable corpus flyer.

## Safety contract

The promotion is append-only and content-addressed by the exact raw JSON SHA-256.
It must not:

- replace the corpus root `source.pdf`, `source.json`, manifest or reviewed
  page-role profile;
- write the production database;
- seed or change Review Queue rows;
- automatically approve or publish offers;
- install or modify systemd timers;
- tune or replace the V6.3.1 parser.

The promotion approval explicitly permits `corpus_write=true` only for
`observations/<raw64>/` and keeps every other write permission false.

## Required evidence

The promoter validates:

- exact staging and corpus PDF SHA-256;
- exact staging and corpus review-profile bytes and SHA-256;
- exact raw observation SHA-256 and observation metadata;
- exact approved source-review SHA-256 and permissions;
- V6.3.1 parser version and SHA-256;
- all authoritative scan files against `SHA256SUMS`;
- exact scan counts: 353 total, 352 physical, 204 accepted, 148 review and
  1 online-only row;
- exact reviewed staging digest;
- exact corpus-promotion approval scope and permissions.

The first successful run atomically creates the observation directory. An
identical replay verifies and reuses every byte. Any mismatch or pre-existing
collision fails closed.

## Result

A successful promotion returns:

```text
RESULT=CORPUS_OBSERVATION_PROMOTED
status=PROMOTED_OBSERVATION_READY_FOR_CONTROLLED_IMPORT
canonical_root_replace=false
db_write=false
review_seed=false
auto_approve=false
auto_publish=false
systemd_change=false
timer_install=false
```

This result means the reviewed observation is available inside the immutable
corpus for a later, separately controlled import and Review Queue bridge. It is
not itself a production data import.
