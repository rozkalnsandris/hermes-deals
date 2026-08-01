# Hermes Deals UI Reference Rebuild V8

V8 centers the visible calendar icon inside the date control.

## CSS and HTML audit

The existing HTML is correct and remains unchanged:

- `#asOfDisplay` is the visible Latvian date text field.
- `#asOfPickerButton` is the visible calendar button.
- `#asOfPicker` is the transparent native date input over the same hit area.

The prior CSS positioned the button correctly, but did not restate the button's
internal alignment at the final cascade layer. The generated `::before` glyph
could therefore sit at the top of its 38 x 42 px button instead of at its visual
center.

## V8 contract

- The calendar button is explicitly a flex centering container.
- The generated glyph has a stable 19 x 19 px box with no inherited margin.
- A one-pixel optical correction accounts for the SVG path's visual center.
- The transparent native date input remains vertically aligned with the button.
- The centered date text, V7 stable sidebar, V6 single-scroll behavior, mobile
  layout, production, database, and Review UI remain unchanged.
