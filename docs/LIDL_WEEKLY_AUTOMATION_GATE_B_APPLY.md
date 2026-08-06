# Lidl weekly automation Gate B — exclusive source freeze apply

Issue: #24

This step applies exactly one separately owner-authorized source freeze after the
read-only Gate B planner has returned `READY_TO_FREEZE`.

It is not a parser run, scan, database import, Review action, publication,
deployment, timer installation or Gate C/D authorization.

## Inputs

The apply command requires:

- the retained private Gate A `WAIT_SOURCE` run directory;
- the authoritative Gate A evidence and Lidl corpus roots;
- the exact 64-character plan fingerprint;
- one owner-created authorization JSON file owned by `andris:andris` with mode
  `0600`.

The tool rebuilds the Gate B plan immediately before staging and again after all
source files have been copied. Both plans must be byte-identical.

## Authorization contract

The authorization file is single-purpose and exact. It binds:

- the Gate B plan fingerprint;
- the Gate A registered commit and run directory;
- the exact corpus destination;
- the PDF and raw-source SHA-256 values;
- one 64-character authorization nonce;
- `corpus_write_authorized=true`;
- every parser, DB, Review, publication, deployment, systemd, retry and Gate C/D
  authority to `false`.

Example shape:

```json
{
  "schema_version": 1,
  "authorization_version": "lidl-gate-b-freeze-authorization-v1",
  "action": "freeze_exact_gate_a_source",
  "authorized_by": "andris",
  "authorization_nonce": "<64 lowercase hex>",
  "plan_fingerprint": "<exact plan fingerprint>",
  "issued_for_commit": "<Gate A registered commit>",
  "gate_a_run_dir": "<exact retained Gate A run directory>",
  "destination": "<exact planned corpus flyer directory>",
  "source_pdf_sha256": "<exact PDF SHA-256>",
  "source_raw_sha256": "<exact raw-source SHA-256>",
  "corpus_write_authorized": true,
  "parser_scan_authorized": false,
  "database_write_authorized": false,
  "review_write_authorized": false,
  "production_publish_authorized": false,
  "production_deploy_authorized": false,
  "systemd_change_authorized": false,
  "automatic_retry_authorized": false,
  "gate_c_d_authorized": false
}
```

Merge of the implementation does not create this authorization and does not
perform the freeze.

## Transaction boundary

The apply implementation:

1. requires execution as the `andris` user and primary group;
2. validates the exact plan and owner authorization;
3. creates one private `0700` staging directory under the authoritative flyers
   root;
4. copies `source.pdf`, `source.json` and `discovery-meta.json` with exclusive
   `0600` creation;
5. verifies source identity did not change during copying;
6. writes a `0600` freeze receipt into staging;
7. fsyncs every file and the staging directory;
8. commits with Linux `renameat2(RENAME_NOREPLACE)`;
9. fsyncs the authoritative flyers directory;
10. verifies the complete committed file set, ownership, modes, sizes and
    SHA-256 values.

No replace fallback is permitted. If `renameat2` is unavailable, the tool fails
closed.

Before commit, failure cleanup may remove only the private staging directory.
After commit, the tool never removes or rewrites the authoritative destination.

## Tests

Focused regressions cover:

- complete exact atomic commit;
- authorization fingerprint and safety drift;
- authorization ownership-mode boundary;
- existing destination and replay blocking;
- source hash and symlink drift;
- pre-commit staging cleanup;
- weakened plan safety;
- no-replace behavior against an occupied destination.

The real RPi5 apply remains separately owner-authorized after merge and
post-merge exact-SHA verification.
