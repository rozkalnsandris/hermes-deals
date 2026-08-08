import test from "node:test";
import assert from "node:assert/strict";

import {
  canonicalCard,
  canonicalDetailUrls,
  canonicalUrl,
  chartSvg,
  packageText,
  statusInfo,
} from "../src/features/catalog.js";

const euro = new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" });

test("canonical URL preserves filter and sort contract", () => {
  assert.equal(
    canonicalUrl({
      asOf: "2026-08-08",
      sort: "retailers_desc",
      query: "  piens ",
      selectedRetailer: "edeka",
      currentOnly: true,
      comparisonOnly: true,
    }),
    "/api/v1/catalog?as_of=2026-08-08&sort=retailers_desc&q=piens&retailer=edeka&current_only=true&comparison_only=true",
  );
  assert.equal(
    canonicalUrl({ asOf: "2026-08-08", sort: "newest" }),
    "/api/v1/catalog?as_of=2026-08-08&sort=name",
  );
});

test("canonical package and status text preserve legacy semantics", () => {
  assert.equal(packageText({ item_quantity_value: 500, item_quantity_unit: "g", pack_count: 2 }), "500 g × 2");
  assert.equal(packageText({}), "Iepakojums nav zināms");
  assert.deepEqual(statusInfo({ comparison_status: "multi_store_comparison", retailer_count: 3 }), ["good", "Salīdzinājums pieejams · 3 veikali"]);
  assert.deepEqual(statusInfo({ comparison_status: "single_current_offer" }), ["warn", "Viens aktuāls veikala piedāvājums"]);
  assert.deepEqual(statusInfo({}), ["", "Šajā datumā nav aktuāla piedāvājuma"]);
});

test("canonical card escapes source text and preserves list state", () => {
  const html = canonicalCard({
    id: "p1",
    display_name: "<Piens>",
    brand_display: "A&B",
    item_quantity_value: 1,
    item_quantity_unit: "l",
    comparison_status: "single_current_offer",
    lowest_price_eur: 1.25,
    retailer_count: 1,
    comparison_available: false,
  }, { items: { p1: { id: "p1" } }, euro });
  assert.match(html, /&lt;Piens&gt;/);
  assert.match(html, /A&amp;B/);
  assert.match(html, /Sarakstā ✓/);
  assert.match(html, /1,25 €/);
  assert.doesNotMatch(html, /<Piens>/);
});

test("canonical detail performs the same three endpoint requests", () => {
  assert.deepEqual(canonicalDetailUrls("abc", "2026-08-08"), [
    "/api/v1/canonical-products/abc",
    "/api/v1/canonical-products/abc/current-offers?as_of=2026-08-08",
    "/api/v1/canonical-products/abc/price-history?limit=60",
  ]);
});

test("price-history chart keeps minimum observation gate", () => {
  assert.match(chartSvg([]), /vismaz divus novērojumus/);
  assert.match(chartSvg([
    { collected_at: "2026-08-01T00:00:00Z", price_eur: 2 },
    { collected_at: "2026-08-02T00:00:00Z", price_eur: 1 },
  ]), /<svg viewBox="0 0 640 150"/);
});
