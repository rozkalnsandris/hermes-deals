# EDEKA live shadow provenance bridge

This bridge closes the evidence-format gap between the existing real EDEKA Patzer shadow-cycle capture and the synthetic Gate B / Gate C contracts from issue #26.

## Input

The tool reads one already captured immutable EDEKA shadow-cycle directory. It does **not** fetch EDEKA, run the collector, write PostgreSQL, write Review state, publish offers, deploy, or activate a scheduler.

Required evidence is verified fail-closed before any provenance output is emitted:

- passing `cycle-evidence.json` and its self-hash;
- exact Patzer identity `071897` → `587881` and scope `family_primary_edeka`;
- exact current source URL;
- raw HTML and source-manifest SHA256 / byte lengths;
- isolated SQLite only, one snapshot, first-write count equality, and identical replay delta `0`;
- deterministic normalization report counts and hashes;
- one normalization row per persisted offer;
- persisted parser/campaign/snapshot identity;
- exact HTML card provenance: `source_offer_id`, `#angebot-<id>`, and `dialog-angebot-<id>`.

The SQLite database is opened with `mode=ro&immutable=1`.

## Output contract

The resulting JSON is directly compatible with `edeka_regional_source_manifest_v1` and `edeka_candidate_provenance_v1`.

For EDEKA the authoritative source is one HTML offers document, not a PDF leaflet. Therefore:

- `candidate_id` is the stable EDEKA `source_offer_id`;
- `card_id` is the exact matching HTML dialog ID;
- `page_number=1` is only the Gate C compatibility ordinal for the single HTML document;
- `live_evidence.source_document_kind=html_offer_cards` records the real source semantics;
- resolved package rows route to `automatic_candidate`;
- unresolved package rows route to `review_required`;
- source state is `review_pending` whenever unresolved rows exist;
- all production/apply/approval/publication flags remain false.

The campaign ID is deterministic from the exact market, validity window and raw HTML SHA256 prefix, so an unchanged source/week produces the same campaign identity.

## Usage

```bash
python tools/edeka_live_provenance_bridge.py \
  --cycle-dir /path/to/immutable/cycle \
  --output-file /separate/evidence/edeka-live-provenance.json
```

The output is exclusive/idempotent: rerunning with identical evidence is a no-op, while attempting to replace an existing output with different bytes fails closed.

## Current issue #26 boundary

A successful bridge over one real week proves complete live candidate/card provenance for that cycle. Issue #26 still requires a second consecutive weekly shadow cycle, cross-week ledger validation, monitoring/stale-data alerts, and a separately authorized exact-row production canary plan before any production apply.
