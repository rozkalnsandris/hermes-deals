# Lidl filtered Review Queue seed

Phase 5G-B15H6 seeds only the unresolved rows from an exact, content-addressed
review seed plan.

The authoritative KW32 scan contains 148 review-required rows:

- 44 rows are explicitly out of scope and are never seeded;
- 47 rows already have approved, published Review decisions and are suppressed;
- 57 fixed-price physical-store rows are seeded as pending Review items.

The plan is bound to the flyer key, scan, source raw SHA, source PDF SHA,
production SourceSnapshot, exact row digests, and these permissions:

- Review seed is allowed;
- offer writes, automatic approval, and automatic publication are forbidden;
- existing rows may not be deleted or updated;
- systemd and timer changes are forbidden.

The importer validates all 148 source rows and all 47 suppressed approved
decisions before creating any of the 57 pending items. Replays must reuse the
same 57 immutable Review identities and create zero new rows.

The production deploy keeps the existing 204 safe offers unchanged and does
not install the weekly Lidl timer.
