# Hermes Deals UI Reference Rebuild V7

V7 removes the small initial vertical movement of the desktop sidebar.

## Source audit

The HTML structure is already correct: `.reference-sidebar` is an `aside`, it is a direct child of the grid `.ui2-shell.reference-app`, and `.reference-workspace` is the adjacent grid child. No wrapper or fixed-position offset is required.

The CSS mismatch was exact: the grid starts with 20 px top padding, while V6 used `top: 12px` and `top: 8px` in its short-height rule. Sticky positioning remains in normal flow until its inset threshold is reached, so the sidebar travelled 8–12 px before sticking.

## V7 contract

- One custom property defines both the grid top padding and sidebar sticky inset.
- The shared value is 20 px.
- The sidebar remains sticky and V6 single-page scrolling remains intact.
- `scrollbar-gutter: stable` prevents unrelated horizontal shifts.
- Mobile, production, the production database, and Review UI are unchanged.
