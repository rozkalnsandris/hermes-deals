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

## Rescan policy

Do not run a fresh automatic Lidl corpus rescan merely from the old Codex
worktree. It would use V6.2 and would not reproduce the parser identity of the
authoritative corpus.

Before future automatic rescans, migrate the executable corpus workflow into
the main Hermes Deals repository and bind each scan to an exact parser hash.

## Completeness debt

Do not modify frozen R6 or add product-name-specific V6.3.1 hacks for the four
known KW32 omissions.

Use a separate reviewed completeness-rescue artifact:

native PDF geometry first -> targeted OCR fallback where native text is absent
-> Review -> existing immutable publication flow.
