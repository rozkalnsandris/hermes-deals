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
may be enabled. Lidl's Oct 26–31 frozen corpus was promoted and verified (#906), but
new weeks and UI publication still require exact-source gates. ALDI Nord,
EDEKA and Kaufland still require page source evidence. Do not guess image URLs,
cache extra PDFs or infer offer/product identity. The UI static asset key is
`booklet-viewer-v8`.


## Store selection, fail-closed reader routing (#1069)

The booklet view accepts a server-allowlisted retailer selection: Netto, Lidl,
ALDI Nord, EDEKA and Kaufland. Existing URLs without a retailer still open the
original Netto reader and preserve its publication, image and offer validation.
The selected retailer survives the Berlin day/week navigation; a date change
starts a new page lookup. Unknown retailer IDs return HTTP 422.

All non-Netto stores currently render an explicit **unavailable** state without
any synthetic page, guessed official URL, implicit offer mapping or fallback to
Netto. The shared reader is still a presentation capability, not evidence that
new stores have published, registered, validated page data. In particular,
Lidl #906 confirms a 76-page Oct 26–31 frozen corpus, but the future weekly
source/production publication and 30-day raw/derived expiry contracts are
separate gates. No LIVE, DB, corpus, parser, PDF or collector mutation is part
of this change.


## Lidl source-bound booklet pages (#1069)

The same shared single-image full-screen viewer, swipe, previous/next controls
and zoom resolution are used for Lidl; only the server-side source adapter is
different. It reads already-saved \`lidl_public_flyer_json_canonical\` JSON
under \`RAW_SNAPSHOT_DIR/lidl\`, verifies the exact snapshot SHA and bytes,
official Lidl viewer/Schwarz self API, region, validity, contiguous full page
list, and each official \`imgproxy.leaflets.schwarz\` image/zoom URL.
It requires an independent **already-persisted DE06664 family-store offer**
bound to the same snapshot and exact flyer/PDF/page provenance; region alone
cannot prove store identity. Corrupt evidence fails closed, without falling
back to a different/older publication. No page images are fabricated.

Lidl page product cards are not enabled yet, because client-side page swipes
do not refresh server-side offer binding. A frozen 76-page source in #906
alone is not proof of available published offers at runtime. This source-only
change does not execute collectors, render/retain PDFs, alter the DB, Review,
publication, the 30-day PDF retention mechanism, or production deployment.



## ALDI Nord rotating publication correction (#1069)

The public current/preview ALDI URLs are dynamic aliases, not immutable
issue-specific URLs. On 2026-11-01 Berlin time the official catalogue at
https://www.aldi-nord.de/prospekte.html labelled 2026-11-02 as Aktuell
and 2026-11-09 as Vorschau, while the local ISO-week still began 2026-10-26.
Therefore mapping the selected calendar week to those aliases can open
the wrong issue.

The ALDI selector now only exposes the official brochure catalogue
(https://www.aldi-nord.de/prospekte.html) for the Berlin-local current and
following week. It does not claim any selected date is covered: the visitor
must choose the edition/date on the official site. Historical/out-of-window
dates remain unavailable. The existing Netto external_link date metadata
and the Netto/Lidl image readers are unchanged.

This remains an external link, not an embedded booklet or source publication.
Full ALDI integration requires an independent immutable official magazine/
iPaper issue/date/region/full-page manifest and complete provenance before
reader activation. No guessed image URLs, OCR matching, PDF copies, collector,
DB/Review/publication or LIVE mutations are introduced.

## ALDI Nord offline first-party page candidate parser (#1069)

`backend/app/aldi_page_candidates.py` can decode a captured official ALDI Nord
Next.js `__NEXT_DATA__` payload (`page.link` and `apiData[*].res`) into
ordered **unverified** iPaper page candidates. It refuses absent/duplicate/
gapped numbers, cross-issue URLs, unsafe schemes/hosts, sensitive URL tokens,
and unbounded input; it performs no HTTP or storage access. Tests use
synthetic data only, **not a verified 2026 live ALDI issue**.

No date/branch/region/publication identity can be inferred from page URL or
Next.js source alone. This parser is intentionally **not wired to the reader**.
To enable it, first obtain independently verifiable, immutable first-party
publication evidence (exact official edition, Berlin dates, region/store,
full page coverage, SHA/retention). Only then connect the existing shared
reader without guessed offers or OCR identity.

## ALDI Nord opt-in registered original-page reader (#1069)

ALDI Nord now supports the exact same Jinja page navigation, fullscreen viewer,
swipe, Zoom/Normal image sizes and unlinked-product panel as Netto. The adapter
`backend/app/aldi_verified_booklets.py` does **not** download PDFs or
create a guessed page sequence. It reads at most 256 KiB of an explicitly
registered, immutable `RAW_SNAPSHOT_DIR/aldi-booklets/verified-manifest.json`.
`ALDI_NORD_BOOKLET_MANIFEST_SHA256` must be the exact lowercase SHA256 of
those bytes; absent registration preserves the official ALDI catalogue link.
A corrupt/missing/expired registered source fails **unavailable**, never
silently falls back to an older edition. The manifest expires at most 30 days
after capture (display gate only: expiry does not delete files).

Each entry must declare explicit official magazine viewer and PDF URL, PDF
SHA256 and byte size, publisher validity, `national_unbound` scope (not
a Dortmund branch), page count and every original first-party
`Image.ashx?PageNumber=N&ImageType=Normal/Zoom` URL. The page list must be
contiguous, same edition, with no unsigned/remote arbitrary host URL or
extra query parameters. No product hotspots or offers are invented.

PDFs captured 2026-11-01 into
`/home/andris/Downloads/hermes-aldi-pdf-2026-w45-w46/` are **not**
an activated backend data source and are not reachable via
`RAW_SNAPSHOT_DIR`. Captured W45 43 pages / SHA256
`37b4e379b8c8c570049bd0a6de29aa22582980a4ccf7de7ca79464b2c08484f6`,
W46 47 pages / SHA256
`7ac0ff94b3063f45f468c919ae969e75112860f642f7728f9fb0ff32ff3ac1ee`.
These checks prove the PDFs, **not** that every page's live image URL was
independently verified nor that any exact Aldi branch has matching offers.
Activation requires first-party full page-list evidence, separately
authorized immutable manifest promotion / registration and actual 30-day
file purge. Merge is not authorization to copy/delete PDF files,
change environment/service configuration, deploy or write DB rows.

### Owner-gated original-page manifest preparation

`tools/aldi_verified_booklet_prepare.py` is an **unexecuted** source-only
one-shot helper for the previously downloaded Nov 2–7 and Nov 9–14 PDFs.
It verifies both original PDF SHA256/byte counts/`pdfinfo` pages and then
probes **every** expected first-party page URL in Normal and Zoom via HTTP
range GET. It requires JPEG magic, the exact CDN redirected page/quality,
a single paper ID within each edition, and different paper IDs between editions.
Only after all **180** checks succeed will it create a *new* output manifest,
exclusively (never overwrites). Signed CDN redirects are never retained.

This only prepares candidate evidence. Execution on the host and any retained
file mutation, raw snapshot promotion, digest registration, 30-day purge,
service configuration or deployment are each owner-LIVE gated. No routine
collector or scheduled script is activated by merging this code. The metadata
is not a store-binding claim; products remain unlinked until independently
approved offer provenance is present.

## EDEKA Patzer verified market catalogue entry (#1069)

The source-backed family EDEKA market is **EDEKA Patzer 071897**
(Eichwaldstraße 5–7, Dortmund-Wickede), exactly the existing
`family_primary_edeka` collector identity in `backend/app/edeka_store_offers.py`.
A public, first-party page on
`https://www.edeka.de/maerkte/071897/prospekte/` shows the market-specific
"Angebote der Woche" digital-brochure entry for **02–07 November 2026**
(confirmed 2026-11-01 on the official market site). The page also lists a
separate "SUUPER Angebote" entry; it must not be silently substituted for the
ordinary weekly booklet. The official issue opens through a JavaScript dialog.

`backend/app/edeka_booklets.py` provides an **external catalogue link
only** for the current and following Berlin calendar weeks; it never infers
that a selected date is the date of the catalogue's currently rotating
edition. Past or distant selections show an unavailable state. No PDF, full
page inventory, page images, hotspots or offer identity is fabricated.
The existing shared UI continues showing an honest no-pages state until
an independent immutable first-party issue and complete page inventory
can be validated. Do not use a generic EDEKA Nordwest flyer or a
different market as Patzer evidence.

Next proof gate: independently capture the EDEKA Patzer weekly **viewer/dialog
source**, official brochure identity, its exact publication dates and
complete page image URLs or PDF, bind to market 071897, calculate SHA256,
and implement a source-only reader against that verified input. Retained
files/collectors/deploy/UI activation are separate owner-LIVE actions.
No live EDEKA assets or production mutation were performed by this PR.

### EDEKA Patzer: current issue viewer and immutable image capture (2026-11-01)

Official market 071897's 02–07 November 2026 **"Angebote der Woche"**
iframe resolves to
`https://blaetterkatalog.edeka.de/RHEINRUHR/1897/index.html`.
The original first-party brochure exposes
`/RHEINRUHR/1897/blaetterkatalog/normal/bk_N.jpg` (450×652)
and `/large/bk_N.jpg` (1100×1594).
Public verification established that pages 1 and 34 are retrievable in both
resolutions. On RPi5 on 2026-11-01 the page-35 request returned HTTP 403,
not evidence of a missing page. The explicitly pinned 34 first-party image
pages are for **EDEKA Patzer, Eichwaldstraße 5–7, Dortmund-Wickede**;
the publisher's full page count is **not independently established**.
They are distinct from the "SUUPER Angebote" catalogue and other markets.
The official EDEKA market site identifies the 02–07 November validity.

**Critical:** Unlike ALDI's issue-specific magazine slug, the EDEKA image
paths contain only region/market identifiers, **not** a dated edition ID.
They can be replaced while retaining the same URL, so linking their live
`bk_N.jpg` URLs into a historical reader would invent immutable provenance.

`tools/edeka_patzer_booklet_capture.py` is a **SOURCE-ONLY, NOT RUN**
one-shot candidate capturer for this exact week. It:
- checks the market-specific official HTML, weekly validity and exact weekly
  iframe (never the SUUPER iframe);
- acquires only the 34 × 2 explicitly pinned first-party JPEGs; validates
  source URLs and Content-Type/JPEG structure, without requesting page 35
  or treating HTTP 403 as proof that the booklet ends at 34;
- re-reads the first and last image in both qualities, rejecting a detected
  upstream rotation during capture;
- only after all read-only checks creates a **new**, exclusively written
  34-page image corpus plus SHA256-bound `capture.json` with both official
  source URLs, the first acquisition time and a 30-day expiry.
  The capture is candidate-only and **cannot** activate the reader.

No external PDF, DB writes, collector or service changes. No stored-image
publication endpoint or automatic deletion exists yet. The 30-day deadline
requires a separately authorized purge of captured image files and any copies
or backups; a timestamp check alone does not delete files. Never run the
capturer unattended or for another edition without new verified first-party
evidence and a new source-reviewed contract. A downstream reader will need
a separately SHA-registered local immutable asset path, explicit authorization
and a full HTML/mobile navigation canary before activation.


## EDEKA Patzer original-page reader (source-only, #1069)

A separately registered EDEKA Patzer 071897 captured edition dated
02–07 November 2026 may use the existing full-screen Jinja reader.
The reader never renders EDEKA's rotating upstream JPEG URL.
A separately owner-LIVE-authorized capture and promotion must preserve
the byte-identical capture.json and pages/normal|large/bk_NN.jpg
under RAW_SNAPSHOT_DIR/edeka-booklets. Explicit owner-LIVE registration
of the capture.json SHA256 as EDEKA_PATZER_CAPTURE_SHA256 is required.
No registration keeps the official market catalogue fallback.
Corrupt/partial/expired registered images fail closed. The locally displayed
34 pages do not independently prove the publisher's total issue length.
The reader verifies
all 68 local image hashes before reporting ready; the image endpoint checks
registration, page identity and the exact requested JPEG hash and returns
no-store and nosniff. The entry contains no fabricated offer links.
The 30-day expiry is a display gate, not file deletion: actual purge,
backup expiry, capture execution, configuration, activation and deploy
remain separate LIVE permissions, with later mobile/desktop canary.


## Kaufland Dortmund-Aplerbeck 1503 original-image reader and capture (#1069)

The official exact-store source
https://filiale.kaufland.de/service/filiale/dortmund-aplerbeck-1503.html
links the **01–07 November 2026** edition at
https://leaflets.kaufland.com/de-DE/DE_de_KDZ1_1503_D45/ar/1503.
On 2026-11-01, the official JavaScript viewer displayed **70 UI positions**,
but its same-session first-party API
\`https://endpoints.leaflets.schwarz/v4/flyer?flyer_identifier=DE_de_KDZ1_1503_D45&region_id=1503&region_code=1503\`
returned **69 actual image pages**: 68 \`STANDARD\` pages followed by one
separately identified \`PROMOTION\` page. The final viewer position is
a dynamically rendered recommendation area, **not a downloadable original page**.

The flyer identifier is \`01a1831f-2f9c-7e3d-96ff-72c3cf783f80\`.
Its standard images are original first-party Schwarz CDN pages with signed
normal 1200px and zoom 2400px URLs. Page 69 is the specifically published
promotion \`01a17c12-30f4-7598-8e9f-60efaead0abe\`, whose signed
\`rs:fill\` URLs have a separate original \`flyer_promotions\` identity.
Neither an invented 70th page nor other overlapping Kaufland leaflets are
accepted. **These image pages are not evidence of retailer offer/product
identity or promotional price ownership.**

The network-free server reader
\`backend/app/kaufland_verified_booklets.py\` uses the existing Jinja
immersive booklet controls. Only a separately owner-LIVE-captured and
promoted \`RAW_SNAPSHOT_DIR/kaufland-booklets/capture.json\` may be
registered via \`KAUFLAND_APLERBECK_CAPTURE_SHA256\`. It checks all 69
ordered original page identities, normal/zoom source signatures,
138 locally stored JPEG SHA256 hashes, market 1503, edition validity,
HTML/API provenance digests and the 30-day display expiry.

\`tools/kaufland_aplerbeck_booklet_capture.py\` is a *one-shot*
owner-LIVE-gated candidate capture tool. It validates the exact market
landing and the first-party JSON API; it never guesses URLs by walking
the JavaScript viewer route, and cannot manufacture product evidence.
It fetches all 138 images and rechecks API/landing/cover invariants
before creating an exclusive candidate directory. Missing, changed or
ambiguous first-party evidence fails closed. No registration leaves an
honest official store link; a corrupt registered source fails closed.

This source PR performs **no capture, raw/DB/collector writes, registration,
deployment or API restart**. After merge, any candidate capture, promotion,
registration and controlled API restart require **separate owner LIVE
authorization** with exact runtime preflight and a read-only UI canary.
30-day metadata expiry blocks display, but does not automatically
delete retained raw files or backups.
