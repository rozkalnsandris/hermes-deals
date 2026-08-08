import test from "node:test";
import assert from "node:assert/strict";

import {
  dealPageSummary,
  dealPrimaryPrice,
  dealsUrl,
  paginationItems,
  rawDealCard,
} from "../src/features/deals.js";
import {
  DAILY_SPECIAL_SOURCE_CONTRACT,
  fetchAllDailyDeals,
  fetchExplicitDailySpecials,
  loadDailySpecialData,
  specialSortRows,
} from "../src/features/daily-specials.js";

const euro = new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" });

test("current deals URL preserves query contract and offset semantics", () => {
  assert.equal(
    dealsUrl({
      asOf: "2026-08-08",
      sort: "discount_desc",
      page: 3,
      dealView: "upcoming",
      query: "  piens  ",
      selectedRetailer: "lidl",
      features: { app: true, coupon: true, discount: true, image: true },
    }),
    "/api/v1/deals/current?as_of=2026-08-08&sort=discount_desc&limit=12&offset=24&view=upcoming&q=piens&retailer=lidl&app_only=true&coupon_only=true&discount_only=true&image_only=true",
  );
});

test("current deals URL falls back to supported sort and current view", () => {
  assert.equal(
    dealsUrl({ asOf: "2026-08-08", sort: "retailers_desc", page: 0, dealView: "other" }),
    "/api/v1/deals/current?as_of=2026-08-08&sort=name&limit=12&offset=0&view=current",
  );
});

test("pagination window matches legacy UI contract", () => {
  assert.deepEqual(paginationItems(1, 1), [1]);
  assert.deepEqual(paginationItems(1, 8), [1, 2, 3, "…", 8]);
  assert.deepEqual(paginationItems(4, 8), [1, 2, 3, 4, 5, 6, "…", 8]);
  assert.deepEqual(paginationItems(8, 8), [1, "…", 6, 7, 8]);
});

test("deal pricing modes preserve legacy labels", () => {
  assert.deepEqual(
    dealPrimaryPrice({ pricing_mode: "unit_price_only", unit_price_eur: 3.5, unit_label: "kg" }, { euro }),
    ["3,50 € / kg", "Cena pēc svara"],
  );
  assert.deepEqual(
    dealPrimaryPrice({ pricing_mode: "app_example_total_plus_unit", price_eur: 2.22 }, { euro }),
    ["ca. 2,22 €", "Lidl Plus piemēra cena"],
  );
  assert.deepEqual(
    dealPrimaryPrice({ price_eur: 1.99 }, { euro }),
    ["1,99 €", "retailer cena"],
  );
});

test("deal card keeps escaped user/source text and list state", () => {
  const deal = {
    offer_candidate_id: "abc",
    product_name_raw: '<b>Piens</b>',
    brand_raw: 'A&B',
    source_chain: "lidl",
    price_eur: 1.49,
    package_text_raw: '1 < l',
  };
  const html = rawDealCard(deal, { items: { "deal:abc": { id: "deal:abc" } }, euro });
  assert.match(html, /&lt;b&gt;Piens&lt;\/b&gt;/);
  assert.match(html, /A&amp;B/);
  assert.match(html, /1 &lt; l/);
  assert.match(html, /Sarakstā ✓/);
  assert.doesNotMatch(html, /<b>Piens<\/b>/);
});

test("deal page summary preserves current and upcoming wording", () => {
  const payload = { available_count: 25, offset: 12, count: 12, as_of: "2026-08-08" };
  assert.equal(
    dealPageSummary(payload, { formatDate: () => "08.08.2026" }),
    "13–24 no 25 aktuāliem piedāvājumiem · 08.08.2026",
  );
  assert.equal(
    dealPageSummary(payload, { dealView: "upcoming", formatDate: () => "08.08.2026" }),
    "13–24 no 25 drīzumā gaidāmiem piedāvājumiem · 08.08.2026",
  );
});

test("explicit daily-special endpoint filters fail-closed evidence", async () => {
  const calls = [];
  const rows = await fetchExplicitDailySpecials(async (url) => {
    calls.push(url);
    return {
      source_contract: DAILY_SPECIAL_SOURCE_CONTRACT,
      deals: [
        { offer_candidate_id: "good", is_daily_special: true, special_valid_on: "2026-08-08", special_confidence: "high" },
        { offer_candidate_id: "bad-confidence", is_daily_special: true, special_valid_on: "2026-08-08", special_confidence: "medium" },
        { offer_candidate_id: "bad-date", is_daily_special: true, special_valid_on: "2026-08-09", special_confidence: "high" },
      ],
    };
  }, "2026-08-08");
  assert.deepEqual(calls, ["/api/v1/deals/daily-specials?as_of=2026-08-08"]);
  assert.deepEqual(rows.map((row) => row.offer_candidate_id), ["good"]);

  await assert.rejects(
    fetchExplicitDailySpecials(async () => ({ source_contract: "legacy", deals: [] }), "2026-08-08"),
    /pierādītu vienas dienas akciju līgumu/,
  );
});

test("daily-special initial data performs exactly two explicit requests", async () => {
  const calls = [];
  const data = await loadDailySpecialData(async (url) => {
    calls.push(url);
    const iso = new URL(`https://example.invalid${url}`).searchParams.get("as_of");
    return {
      source_contract: DAILY_SPECIAL_SOURCE_CONTRACT,
      deals: [{
        offer_candidate_id: iso,
        source_chain: iso.endsWith("08") ? "netto" : "lidl",
        product_name_raw: iso,
        price_eur: 1,
        is_daily_special: true,
        special_valid_on: iso,
        special_confidence: "high",
      }],
    };
  }, "2026-08-08");
  assert.deepEqual(calls, [
    "/api/v1/deals/daily-specials?as_of=2026-08-08",
    "/api/v1/deals/daily-specials?as_of=2026-08-09",
  ]);
  assert.equal(data.todayIso, "2026-08-08");
  assert.equal(data.tomorrowIso, "2026-08-09");
  assert.equal(data.today.length, 1);
  assert.equal(data.tomorrow.length, 1);
  assert.ok(calls.every((url) => !url.startsWith("/api/v1/deals/current?")));
});

test("legacy daily-special helper remains bounded and deduplicated", async () => {
  const calls = [];
  const rows = await fetchAllDailyDeals(async (url) => {
    calls.push(url);
    const offset = Number(new URL(`https://example.invalid${url}`).searchParams.get("offset"));
    if (offset === 0) {
      return {
        available_count: 3,
        deals: [
          { offer_candidate_id: "a" },
          { offer_candidate_id: "b" },
        ],
      };
    }
    return {
      available_count: 3,
      deals: [
        { offer_candidate_id: "b" },
        { offer_candidate_id: "c" },
      ],
    };
  }, "2026-08-08", { pageLimit: 2, maxPages: 5 });
  assert.deepEqual(rows.map((row) => row.offer_candidate_id), ["a", "b", "c"]);
  assert.equal(calls.length, 2);
  assert.match(calls[0], /limit=2&offset=0$/);
  assert.match(calls[1], /limit=2&offset=2$/);
});

test("daily-special sorting round-robins retailers after within-store ranking", () => {
  const rows = specialSortRows([
    { offer_candidate_id: "n2", source_chain: "netto", discount_percent: 10, price_eur: 2, product_name_raw: "N2" },
    { offer_candidate_id: "l1", source_chain: "lidl", discount_percent: 20, price_eur: 1, product_name_raw: "L1" },
    { offer_candidate_id: "n1", source_chain: "netto", discount_percent: 30, price_eur: 1, product_name_raw: "N1" },
    { offer_candidate_id: "a1", source_chain: "aldi_nord", discount_percent: 5, price_eur: 1, product_name_raw: "A1" },
  ]);
  assert.deepEqual(rows.map((row) => row.offer_candidate_id), ["n1", "l1", "a1", "n2"]);
});
