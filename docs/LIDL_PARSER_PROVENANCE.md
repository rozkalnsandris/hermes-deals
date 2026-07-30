# Lidl parser provenance and rescan policy

## Authoritative corpus source identity

The production Lidl corpus currently contains reviewed observations generated
by parser `lidl-pdf-v08c-r61-shadow-v631`.

The exact V6.3.1 source is preserved under:

`tools/lidl_parser_provenance/v631/`

This bundle is content-addressed and is the authoritative provenance for:

- KW31 `scan-0005`
- KW32 `scan-0003`

The checked-out legacy Codex worktree currently contains a deliberate V6.2
rollback and must not be treated as the source of those scans.

## Executable rescan adapter

The main repository now contains a content-addressed loader at:

`tools/lidl_parser_provenance/lidl_v631_runtime.py`

It verifies both frozen source SHA-256 values before loading V6.3.1 and fails
closed on any drift. The OCR worker installs the pinned PyMuPDF dependency
through `backend/requirements-ocr.txt`.

The adapter was replayed against KW32 `scan-0003`; all 352 canonical parser
rows matched the archived observation exactly. This makes controlled rescans
reproducible, but it does not turn Lidl into an automatic production collector
and does not bypass corpus review or production gates.

Do not run a fresh Lidl corpus rescan from the old Codex worktree. It contains
the V6.2 rollback and is not authoritative.

## Completeness debt

Do not modify frozen R6 or add product-name-specific V6.3.1 hacks for the four
known KW32 omissions.

Use a separate reviewed completeness-rescue artifact:

native PDF geometry first -> targeted OCR fallback where native text is absent
-> Review -> existing immutable publication flow.
