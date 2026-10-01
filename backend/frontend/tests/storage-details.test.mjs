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

test("retailer details use one date-scoped request even without canonical identity", () => {
  assert.deepEqual(rawDealDetailUrls({ offer_candidate_id: "abc" }, "2026-08-08"), [
    "/api/v1/offers/abc/price-intelligence?as_of=2026-08-08&limit=200",
  ]);
  assert.deepEqual(rawDealDetailUrls({}, "2026-08-08"), []);
});

test("retailer detail status does not claim an unconfirmed identity", () => {
  assert.equal(rawDealDetailStatus({ canonical_product_id: "abc" }), "Produkts atpazīts");
  assert.equal(rawDealDetailStatus({ canonical_comparable: true }), "Veikala piedāvājums");
  assert.equal(rawDealDetailStatus({}), "Veikala piedāvājums");
});

test("source history plots normalized prices and preserves conditions", async () => {
  const { detailHistoryHtml } = await import("../src/features/catalog.js");
  const html = detailHistoryHtml([
    { collected_at: "2026-09-01", price_eur: "2.50", comparison_price_eur: "4.99", package_text_raw: "500 g", source_chain: "lidl", requires_app: true, coupon_required: true },
    { collected_at: "2026-09-02", price_eur: "3.00", comparison_price_eur: "5.99", package_text_raw: "500 g", source_chain: "lidl" },
  ], "", { sourceHistory: true, historyBasis: "kg" });
  assert.match(html, /<svg/);
  assert.match(html, /4,99.*\/kg/);
  assert.match(html, /500 g/);
  assert.match(html, /lietotne/);
  assert.match(html, /kupons/);
  assert.match(html, /2026-09-01/);
});

test("unmapped deal loads history end to end using one offer request", async () => {
  const { initDealDetails } = await import("../src/features/details.js");
  const requests = [];
  const element = { classList: { add() {} }, innerHTML: "", querySelector: () => null };
  const oldDocument = globalThis.document;
  globalThis.document = { body: element };
  try {
    const details = initDealDetails({
      fetchJson: async (url) => { requests.push(url); return {
        history_basis: "package", observations: [{ price_eur: "1.99", comparison_price_eur: "1.99", source_chain: "lidl", collected_at: "2026-09-01" }],
        offers: [], comparison_status: "identity_not_reviewed",
      }; },
      fmtDate: value => value || "—", getAsOf: () => "2026-09-30", getItems: () => ({}),
      scrim: element, dealDetail: element, dealDetailBody: element,
    });
    await details.openRawDealDetail({ offer_candidate_id: "offer-1", product_name_raw: "Piens", price_eur: "1.99", source_chain: "lidl" });
    assert.equal(requests.length, 1);
    assert.match(requests[0], /offers\/offer-1\/price-intelligence/);
    assert.match(element.innerHTML, /1 novērojumi/);
    assert.doesNotMatch(element.innerHTML, /canonical identitātes/);
  } finally { globalThis.document = oldDocument; }
});
