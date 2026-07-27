# Phase 3B0 — product identity foundation

Phase 3B0 is the design/truth-sync gate before the first Phase 3 schema migration.

It performs no DB migration and no automatic product linking.

It verifies retailer production state, audits explicit barcode/retailer identifier evidence, records structured identity gaps, synchronizes current documentation and accepts ADR 0001.

The next migration must implement the ADR rather than the older two-table candidate/link design.
