# Original booklet UI — first Netto slice

Tracking: #1069. Separate navigation entry **Bukleti**, URL
`/ui/home/?view=booklets&date=2026-10-01&page=1`.
The existing household UI opt-in and household actions remain authoritative.
Offers and the legacy UI keep their existing routes and behavior.

## Behavior

Show original Netto publication page images with page selection, previous/next,
and keyboard-accessible CSS enlargement. The date and page survive opening and
closing product details and adding a product to the list or favorites.
Changing day/week resets to the first page.

Read only existing successful family Netto snapshots, no later than the selected
Berlin day's end. Within the latest 50 candidates, use the first verified
manifest whose validity includes that day. Missing/invalid metadata is an honest
empty/unavailable state; a corrupt latest source does not silently become an older
booklet. JSON files must resolve under the configured raw root, be at most 2 MiB
and match the recorded SHA. Store 5659, scope, strategy, selected-store evidence,
validity and official source/page URL restrictions are checked.

The browser loads official Publitas images directly. This code does not download,
read or cache PDFs, create images, run OCR, collect offers, mutate snapshots or
activate the PDF retention registry. The maximum 30-day PDF requirement remains
tracked independently in #1069; this view introduces no local PDF copies.

## Product identity boundary

Adjacent product cards require a persisted offer from the same snapshot,
Netto store 5659, PDF content SHA and exact integer page, valid and observed by
the selected day. Shadow-only / ineligible candidates are excluded. The cards
reuse existing household actions and price history/detail services. No product
name matching or synthetic production offers are introduced.

Image hotspots are **not implemented**: existing shadow geometry alone is not
proof of a persisted offer mapping or normalized page dimensions. Unlinked pages
stay browseable with an explicit explanation. Complete verified product bindings,
image hotspots and an explicit cross-store weekly comparison are still TODO.

## Verification and availability

`backend/tests/test_north_star_live.py` covers full HTML / HTMX, URL restoration,
real isolated household mutations, conflict re-rendering, provenance exclusions,
metadata integrity, invalid paths, escaping and honest empty states.
CI runs focused UI tests before the full suite, renders a clearly synthetic
page using the actual templates/styles and checks 1440×900 / 412×892 browser
layout and image loading. One-day artifact: `booklet-ui-synthetic`.
Those screenshots demonstrate the layout, not production retailer availability.

Deployment and the actual availability of saved manifests/publication metadata
on RPi have not been verified by this source PR. The UI can truthfully be empty
until a matching retained source is available. No collector, migration or
production write is authorized or performed by this step.
