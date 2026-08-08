import test from "node:test";
import assert from "node:assert/strict";

import {
  normalizeUiPrefs,
  normalizeViewPrefs,
} from "../src/core/storage.js";
import {
  rawDealDetailStatus,
  rawDealDetailUrls,
} from "../src/features/details.js";

test("UI preferences preserve compact-home and card-density schema", () => {
  assert.deepEqual(normalizeUiPrefs({ compactHome: 1, cardDensity: "compact" }), {
    compactHome: true,
    cardDensity: "compact",
  });
  assert.deepEqual(normalizeUiPrefs({ compactHome: 0, cardDensity: "bad" }), {
    compactHome: false,
    cardDensity: "comfortable",
  });
});

test("view preferences fail closed to supported modes retailers sorts and feature booleans", () => {
  assert.deepEqual(normalizeViewPrefs({
    mode: "other",
    dealView: "upcoming",
    retailer: "unknown",
    sort: "bad",
    currentOnly: 1,
    comparisonOnly: 0,
    features: { app: 1, coupon: 0, discount: "yes", image: null },
  }), {
    mode: "deals",
    dealView: "upcoming",
    retailer: "",
    sort: "name",
    currentOnly: true,
    comparisonOnly: false,
    features: { app: true, coupon: false, discount: true, image: false },
  });
});

test("retailer detail canonical requests remain exactly two and date scoped", () => {
  assert.deepEqual(rawDealDetailUrls({ canonical_product_id: "abc" }, "2026-08-08"), [
    "/api/v1/canonical-products/abc/current-offers?as_of=2026-08-08",
    "/api/v1/canonical-products/abc/price-history?limit=60",
  ]);
  assert.deepEqual(rawDealDetailUrls({}, "2026-08-08"), []);
});

test("retailer detail status preserves canonical trust wording", () => {
  assert.equal(rawDealDetailStatus({ canonical_product_id: "abc" }), "Canonical identitāte apstiprināta");
  assert.equal(rawDealDetailStatus({ canonical_comparable: true }), "Canonical salīdzināms");
  assert.equal(rawDealDetailStatus({}), "Tikai retailer deal");
});
