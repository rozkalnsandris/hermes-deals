# Issue #32 UI audit

## Contract

- API and URL values remain ISO `YYYY-MM-DD`.
- Every user-visible calendar date is rendered as `DD.MM.YYYY`.
- “Today” is resolved in `Europe/Berlin`; rendering does not coerce calendar-only values through UTC.
- Invalid URL dates fall back to the Berlin-local current date instead of entering API requests.

## Audited surfaces

The current `main` implementation was checked across the weekly overview, offers, canonical comparison, daily specials, Review, filter summaries, retailer cards, drawers, detail dialogs and mobile navigation.

The implementation fixes the two confirmed contract gaps:

1. weekly day, validity and range labels previously mixed `DD.MM.` with `DD.MM.YYYY`;
2. the primary family and Review workflows lacked one final page-level overflow and safe-area contract on narrow screens.

## Mobile and accessibility safeguards

- page-level horizontal overflow is clipped while intentional inner navigation/filter scrollers remain scrollable;
- grid children and long product/filter text may shrink and wrap;
- weekly date/store controls use two bounded mobile columns and stay within the viewport;
- the Review toolbar and sticky actions collapse to full-width controls;
- sticky Review actions include the device bottom safe area;
- primary calendar and navigation controls retain at least 44 px touch targets on coarse pointers;
- active filter summaries remain visible and provide a full-width reset action on narrow screens.

## Verification

Focused contract tests cover date format/timezone semantics, URL validation, calendar anchoring, mobile overflow, Review safe areas, filter reversibility and absence of preview/diagnostic copy in the normal rendered family body.

No production deployment or database write is part of this change.
