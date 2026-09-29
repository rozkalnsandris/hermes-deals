# Netto 5659 HTML-primary collector

`python -m app.collector_cli collect --source netto --min-offers 20` uses the
selected family-store HTML catalogue. The existing systemd command stays the
same; deploying this source changes its next execution. No timer is installed or
activated by this source change. Production deployment/import still requires
separate LIVE authority.

The previous store/prospect PDF reader remains available for historical
manifest replay and the separate PDF/shadow tools. It is no longer a prerequisite
for the regular CLI import. This does not complete the unattended acceptance
criteria of issue #28.

## Source and interpretation

A new HTTP session selects the configured Rauschenbuschstr. 1 branch (5659),
requires its selection cookie, and verifies the selected address returned by the
catalogue. Only the official HTTPS host and supported store/catalogue paths are
accepted. The full weekly listing is fetched once. Short-period catalogue links
are discovered on the branch page (at most four), fetched in the same session,
and independently checked for the selected address. No wishlist action is
called: URL query parameters in each card are parsed as embedded evidence only.

Each card binds its SKU, title, public price, package, image and validity.
Structured public prices are cross-checked against the public-price DOM node;
app-price nodes remain separate, with their own price fields and card period.
An offer with a public price does not become `requires_app` merely because an
optional app price exists. `ab` lower-bound prices are counted as rejected,
never converted to fixed prices. `je` and whole-euro typography are supported.
UVP is retained in raw evidence, not mapped to a historical store price. A clear
`statt` amount above the current price may populate `regular_price_eur`.

Package, unit-price text and deposit text remain in immutable card evidence.
Explicit `pro kg/l/100 g/100 ml` prices use `unit_price_only`; other unit-price
normalization/product equivalence remains downstream. No low end of a unit-price
range is invented as the one true unit price.

The page period must be a bounded non-stale interval, and every accepted card's
`ValidityPeriod` and `ValidTo` must agree with it. Short-period cards are never
backdated to Monday. Future cards do not satisfy the CLI minimum-current-offer
gate. A stale/empty page or store mismatch fails the capture. Card-specific
ambiguities are reported with SKU, index and reason; accepted + rejected equals
the number of captured cards. This is HTML catalogue accounting, not a claim of
complete PDF/booklet coverage.

## Persistence and recovery

Raw HTML is retained by SHA256 beneath `raw_snapshot_dir/netto-html`. Each
capture has an immutable JSON observation; a successfully parsed capture also
has a manifest with page hashes, source identities, collection time, card counts,
rejections and the semantic fingerprint. Failed parsing keeps its capture
reference. Private HTTP session cookies are never serialized.

Snapshot and offer rows commit together. Failure rolls back offers and records
a failed observation; it cannot leave a successful new snapshot with a partial
batch. A semantically unchanged capture replays the previous hash-verified
manifest and invokes the existing exact-set idempotent writer. It therefore
recovers an absent offer batch, leaves a complete batch unchanged, and rejects
partial or changed existing rows. Raw transport/order changes alone do not
create a second successful snapshot. Newly fetched raw observations may still
be retained even when the previous snapshot is reused.

Parser/strategy versions bind semantic replay. A future incompatible parser
change must version the strategy or supply an explicit migration/replay design;
old immutable rows are never silently reinterpreted or overwritten.

## Acceptance evidence (2026-09-29)

Local replay of the captured official branch catalogues accounts for 235 cards:
197 exact-price weekly candidates (28 September–2 October), 35 short-period
candidates (30 September–2 October), and 3 rejected lower-bound prices.
An isolated database import writes 232 rows; its repeat writes zero and reuses
one successful snapshot. These are local source/persistence results, not a
production import claim. The fixtures preserve real card fragments; their
provenance file records original response hashes and extraction indexes.
