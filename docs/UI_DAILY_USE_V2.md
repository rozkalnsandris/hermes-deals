# UI Daily Use v2

## Goal

Make the Lidl Review Queue faster and safer during weekly manual verification without changing parser, persistence, database schema, or production runtime.

## Review productivity

- Client-side search across product name, brand, package, price, page number, status, and reason codes.
- Clickable status counters for open, pending, draft, follow-up, approved, rejected, and all rows.
- Previous/next buttons and keyboard navigation with Up/Down arrows.
- `/` focuses queue search and `Ctrl+S` saves the selected editable product.
- The selected position is shown as `N no M`.
- Status, search, and selected item are preserved in the page URL.

## Edit safety

- Editable forms show a `Nesaglabāts` indicator after a field changes.
- Switching rows, filters, reloading, or leaving the page warns before discarding unsaved edits.
- Rejecting a row with unsaved edits requires explicit confirmation.
- The action bar remains visible while scrolling a long form.
- Choosing a date through the native calendar marks the form as unsaved.
- Previous/next and status controls retain correct disabled state during and after mutations.

## Scope boundary

This phase changes only Review UI, Review UI tests, and this document. It does not touch Lidl parser files, backend routes, models, schemas, collectors, production database, or deployment configuration.
