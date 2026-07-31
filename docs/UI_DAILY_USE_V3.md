# UI Daily Use v3

## Scope

This isolated UI change improves the family shopping list without changing the backend API, retailer parsers, database schema, collectors, or production runtime.

## Family list

- Both canonical products and concrete retailer deals can be added.
- Concrete retailer deals keep retailer, price, package, and validity context.
- Existing `hermesDeals.shoppingList.v1` entries are migrated as canonical items.
- Items can be marked bought while remaining available for the shopping trip.
- The header badge counts only remaining items.
- The drawer shows remaining and bought totals.
- Bought items can be removed in one action.
- The full list can be copied to the clipboard.
- Clearing the entire list requires a Hermes-styled accessible confirmation panel; the browser-native confirm dialog is not used.
- The drawer footer respects mobile safe-area spacing and changes to a single-column action layout on very narrow screens.
- Destructive-action text uses the theme surface color so contrast remains readable in both light and dark modes.

## Basket comparison truth

Only remaining canonical products are sent to the basket-comparison API. Concrete retailer deals stay visible in the family list but are explicitly excluded from canonical cross-store comparison. Bought items are excluded as well.

## Acceptance

1. Add one raw retailer deal and one canonical product.
2. Open the family list and verify both item types and their metadata.
3. Mark one item bought and verify the header count decreases.
4. Copy the list and verify quantities, names, and retailer-deal context.
5. Compare the basket and verify only the remaining canonical item is submitted.
6. Remove bought items and verify remaining entries stay intact.
7. Attempt to clear the full list and verify the Hermes confirmation panel opens, focus starts on `Atcelt`, Escape/backdrop cancel safely, and confirmation clears the list.
8. At a viewport below 420 px, verify the drawer actions are single-column and fully visible above the safe area.
9. Reload the page and verify the list persists.

## Deferred

List sharing between different devices remains deferred because the current list is intentionally browser-local and has no authenticated server-side owner.
