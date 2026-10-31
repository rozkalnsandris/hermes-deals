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

## Production compatibility diagnosis (2026-10-27)

Read-only SSH diagnosis of API revision eb207d3 found a verified 71-page V3
publication from September 26. The collector stores the original request URL
in SourceSnapshot but the final store URL includes `?stores_id=5659`.
Compare only that explicit selected-store variation; keep HTTPS, official host,
same branch path and all other query parameters bound. The official viewer host
`wochenprospekt.netto-online.de` is supported, with conflicting viewer store IDs
rejected. Original manifest/publication SHA verification remains unchanged.

If the selected date has no booklet, a separately dated last-available archive
link is shown when verified publication metadata can be read and the observation
was made within its validity. It never labels historical offers as current.

The latest production Netto observation on October 27 uses
`netto_store_html_v1`, while the latest V3 booklet is September 26
(valid September 24–26). Consequently this compatibility fix does not supply a
current-week booklet. Integration of current publication metadata into the
active HTML collection path remains tracked in #1069. No PDF read, collection,
replay, deployment or production mutation was performed during diagnosis.

## Store-bound HTML booklet teaser metadata (source-only)

The existing `netto_store_html_v1` collector now derives the optional
`booklet_teaser_evidence` field from its already fetched, selected-store HTML.
The field records only official viewer slug → same-teaser start date; its values
are checked again against the SHA-verified store HTML on replay. If the brochure
markup is ambiguous, the field is `unavailable` without blocking valid offer
import. When offer prices do not change but the dated booklet teaser changes,
a new immutable observation is kept instead of deduplicating away that evidence.

These starts are **not** proof of `valid_until`, publication pages, PDFs,
product identity or complete weekly coverage. The household booklet reader still
requires independently verified publication metadata before displaying pages;
no new booklet-page UI is claimed by this source-only change. The collector
requires separate LIVE authorization before any production run.

## Start-day official viewer link fallback (source-only)

When no verified current publication pages exist, the booklet UI may display an
**official external viewer link** on the precise start day proven by one teaser in
the latest successful `netto_store_html_v1` snapshot. The source store HTML and
manifest must pass SHA256, store 5659 URL, role, path and scope checks. The optional
teaser field in new manifests is compared to the re-extracted same-card evidence;
older immutable manifests without that field remain readable through their
verified HTML. Corrupt latest source never falls back to older HTML.

This fallback is an explicit `external_link` state, **not** `ready`: it has no
local pages, no page count, no inferred end date, and no matched offer/product
links. Only the exact verified start date is eligible; other selected dates do
not inherit an unproven period. Existing V1–V3 fully verified publication pages
take priority. No new network GET, PDF, collector, migration, or data writes.

## PDF-free verified HTML publication pages

The active `netto_store_html_v1` collector may fetch the selected store's
official viewer HTML and Publitas JSON for each dated teaser (maximum four).
A publication is accepted only when the viewer's explicit metadata validity
starts on the exact same date as its store-bound teaser, the end date is
explicit (at most 14 days after start), and the official API JSON exposes
valid, distinct, bounded page paths. Redirects, wrong MIME types/hosts,
malformed metadata and missing dates are rejected. Invalid viewer data never
blocks separately validated retailer offer imports. There is **no PDF fetch**.

The response bytes are stored immutably by SHA under `raw/netto-html` and
referenced in the existing HTML snapshot manifest as `booklet_publications`.
The existing Jinja booklet reader reads only the newest successful HTML
snapshot (respecting the selected Berlin day cutoff), independently verifies
its manifest, selected store, source HTML and dated teaser bindings, viewer
HTML validity and group identity, API URL and publication JSON/page hashes,
then renders verified official page images with **no linked offer claims**.
The V1–V3 reader remains higher priority. Corrupt metadata fails closed;
without full metadata the original start-day-only external link remains an
explicitly limited fallback. No independent collector process, schema change,
migration, household action, PDF or inferred offer identity is introduced.

Production collection and display availability are still unverified until
a separately authorized deployment/collector run and read-only canary.

## Native swipe reading (#1069)

Only fully verified `netto_store_html_v1` publications expose all
SHA-validated official Publitas page image URLs to a horizontal native
CSS scroll-snap reader. Nonselected images lazy-load. Minimal JavaScript
synchronizes page selection, arrows, the counter and shareable page URL,
without navigating away on each swipe. Browser fullscreen and keyboard
arrows are optional. Legacy V1–V3 keep their per-page navigation and
distinct linked-offer provenance. No PDF or speculative hotspot mapping.

## One-image fullscreen reader correction

Only the currently selected, SHA-verified publication page is an HTML image. Other verified image URLs are options, not DOM images or downloads. A fullscreen button opens a viewport-filling reader with next/previous, keyboard navigation and touch swipes; the CSS overlay stays usable when native Fullscreen API is denied. Ordinary server links work when JavaScript is unavailable. Assets use a changed versioned URL to avoid serving old JavaScript and CSS from browser caches. No PDF, invented hotspots, or offer mapping is introduced.

## Immersive viewer and focal-point zoom (#1069)

The cover image itself enters fullscreen, while the separate button remains.
The reader hides the ordinary page selector, outer zoom button and explanatory
labels when open. Only an overlay close button and compact prev/counter/next
controls are shown. Browser Fullscreen API is requested with
`navigationUI: hide`; the full-viewport CSS fallback remains on unsupported
mobile browsers, and browser-generated fullscreen guidance cannot be hidden by
the application. Native-image selection/dragging is disabled.

Inside the reader: two-finger pinch scales the selected image 1–5x around
the gesture midpoint; a single finger pans while zoomed, or changes the page
with a horizontal swipe while at fit scale. Desktop clicks on the image zoom
around the cursor, and a subsequent click resets zoom. All page changes reset
zoom and use only previously verified publication URL options. The reader still
holds only one image and does not request a PDF or infer product identity.

## Separate image zoom from product selection (#1069)

In the immersive reader, clicking the cover still opens fullscreen, but a
single click on the open page no longer zooms. This keeps future verified
product hotspots possible without conflicting with a magnifier (hotspots and
product mappings are **not** implemented by this change). Desktop controls
are separate 44px + / − buttons, wheel/trackpad zoom over the page at the
pointer, and keyboard + / −. Mouse dragging pans an enlarged page. Mobile
pinch zoom and one-finger panning/swiping retain their previous behavior.
The zoom level is visible and clamped to 100–500%; changing pages resets it.
No collector/DB/offer/PDF/LIVE changes.


## Resolution-aware Netto zoom (verified publication metadata)

The verified Netto HTML publication JSON may contain a `sizes` object
with official Publitas page-image variants. Only a declared `at2400` or
`at2000` variant with finite valid width/height is exposed as an optional
higher-resolution URL for each SHA-validated page path. At normal scale the
reader uses the original `at1600` asset; at zoom >100% it upgrades only
the selected image. On asset load error the reader returns to the verified
`at1600` URL and does not retry the failed higher resolution on that page.
When metadata lacks a usable size, the standard image remains unchanged.
The browser fetches no PDF, tiles or speculative URLs, and does not request
the next page's high-resolution image. Zoom, pan, swipe and product selection
boundaries are unchanged. No source acquisition, database or LIVE change.


## Fullscreen image clarity when scaling (#1069)

A desktop Chrome visual canary showed significantly sharper Netto booklet
text after changing the immersive image element's CSS `will-change` from
`transform` to `auto` at 145%+ zoom. Chromium documents that
`will-change: transform` can avoid re-rasterizing on JavaScript-driven scale
changes, leaving scaled text blurry (see
https://googlechrome.github.io/samples/css-will-change-transform-rasterization/index.html).
The fullscreen image therefore no longer forces `will-change: transform`;
normal browser rasterization behavior applies. CSS `transform` positioning,
verified `at2400` / `at2000` variant selection, mobile pinch/swipe,
and desktop + / − zoom remain untouched. New CSS is cache-busted with
`netto-viewer-v6`. No product hotspots, PDF, persistence, or LIVE mutation.


## Inline viewer cleanup and page-navigation states (#1069)

The official Netto page image remains the opener for the immersive reader;
the cover is also keyboard-operable via the focusable canvas (Enter/Space).
Remove the redundant inline fullscreen button and hint, and remove the
fallback sentence linking to the retailer from beneath the image. The
verified retailer URL remains in the booklet header. Page number and source
provenance remain beneath the image.

Inline previous/next links now receive `aria-disabled="true"` only at the
first/last page boundary. Enabled links remove the disabled attribute;
CSS styles the disabled state with `[aria-disabled="true"]` instead of
`[aria-disabled]`, which had also dimmed `aria-disabled="false"`.
Enabled links have a clear green outline and focus indicator; boundary links
remain visibly inactive and non-focusable. Page URLs, fullscreen HUD controls,
touch gestures, zoom and image provenance are unchanged. Assets use
`netto-viewer-v7` for cache-busting.


## Shared booklet reader presentation contract (#1069)

The original Netto Jinja reader and JavaScript zoom/fullscreen controls
now take retailer name and retailer key from explicit server-side booklet
context rather than hardcoding them in labels, alt text, store badge or offer
navigation. Missing fields retain the existing Netto default, keeping
existing bookmarked Netto deep links, controls and source validation intact.
The reader is exercised with a **synthetic** LIDL context, not proof of
production Lidl booklet availability.

Additional retailers require independently verified, selected-store-bound
page metadata, dates, source identity and safe image URLs before their reader
may be enabled. Lidl Gate B corpus freeze (#906) remains owner-gated; ALDI Nord,
EDEKA and Kaufland still require page source evidence. Do not guess image URLs,
cache extra PDFs or infer offer/product identity. The UI static asset key is
`booklet-viewer-v8`.
