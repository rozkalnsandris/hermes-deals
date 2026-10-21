# Price history discovery

`/ui/home/?view=history` searches immutable saved observations, including expired
promotions. The selected date means **known by the end of that Berlin day**,
not promotion validity. A future observation is excluded even when supplied by
UUID in a detail URL.

`list_price_history_series` in `backend/app/price_intelligence.py` ranks observations
in SQL, returning one latest row per conservative source series plus the series
count. `row_number()` partitions on the same identity as the detail service:
retailer, branch, source SKU, exact name/brand/package/unit, pricing basis and
app/coupon requirements. NULL and `fixed_package` are the same fixed-price basis.
Missing SKU or unknown basis means a singleton observation, never guessed identity.
Collection timestamp descending and UUID ascending give a deterministic winner.

Search (name, brand, SKU) and retailer filters apply before ranking because these
fields are constant within a series. Search treats `%` and `_` literally. Sorting,
counting and pagination happen in SQL; only the requested page is materialized as
ORM offers. No schema, source observation, reviewed identity or household state is
written. Existing detail history retains its 200-observation limit and disclosure.

Cards show the **last observed price**, timestamp and branch. Unit-price offers
show EUR per source unit, not the example package total. Unknown price basis shows
an unknown price. Historical prices are not claimed as currently available prices
or savings. The history view has read-only detail links; search/filter/page context
survives opening and closing details. No search matches and no comparable detail
observations have separate messages.

This follows the canonical [Web architecture](WEB_ARCHITECTURE.md): Python owns
identity/pricing/query rules; Jinja emits semantic HTML; HTMX enhances navigation;
plain links and GET forms remain functional without JavaScript. Existing no-store
and HTMX request handling remain in force.

Implementation references:

- [SQLAlchemy window functions](https://docs.sqlalchemy.org/en/20/tutorial/data_select.html#using-window-functions)
- [PostgreSQL window functions](https://www.postgresql.org/docs/current/tutorial-window.html)
- [HTMX documentation](https://htmx.org/docs/)

Regression tests in `test_price_history_discovery.py` execute the same contracts
on SQLite and on the migrated PostgreSQL CI service, including DST cutoffs,
identity boundaries, literal search, tie ordering and bounded page hydration.
`test_north_star_live.py` covers expired discovery, detail prices, empty states,
future exclusion, navigation context and HTMX responses.
