import test from "node:test";
import assert from "node:assert/strict";
import { initWeeklyOverview } from "../src/features/weekly.js";
import { weeklyRetailerFreshness, weeklyRetailerPresentation } from "../src/features/weekly-trust-state.js";

const keys = ["lidl", "aldi_nord", "netto", "edeka"];
const dates = Array.from({ length: 7 }, (_, index) => `2026-08-${String(index + 3).padStart(2, "0")}`);
function payload(states = {}) {
  return {
    week_start: dates[0],
    days: dates.map((date) => ({ date, deals: [] })),
    retailers: keys.map((retailer_key) => ({ retailer_key, state: states[retailer_key] || "no_offers", deal_count: 0, active_dates: [] })),
  };
}

async function mount(fetchJson) {
  const elements = new Map();
  const element = (id) => {
    if (!elements.has(id)) elements.set(id, {
      innerHTML: "", textContent: "", value: "", hidden: false,
      classList: { toggle() {}, remove() {} },
      addEventListener() {}, querySelectorAll: () => [], querySelector: () => null,
    });
    return elements.get(id);
  };
  globalThis.document = { getElementById: element, querySelectorAll: () => [] };
  globalThis.window = { addEventListener() {} };
  let retailer = "";
  let asOf = dates[0];
  const ui = initWeeklyOverview({
    fetchJson, euro: new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" }),
    retailerName: (key) => key, dealPrimaryPrice: () => ["1,00 €"], openRawDealDetail() {},
    getSelectedRetailer: () => retailer, setSelectedRetailer: (key) => { retailer = key; },
    getAsOf: () => asOf, setAsOfIso: (iso) => { asOf = iso; },
    syncUrl() {}, loadGrid() {}, saveViewPrefs() {}, retailers: element("retailers"),
  });
  await new Promise(setImmediate);
  return { ui, element, select: (key) => { retailer = key; ui.render(); } };
}

test("every retailer/day discloses authoritative states and incomplete weeks never imply zero", async () => {
  const data = payload({ lidl: "not_supported", netto: "not_published_yet", edeka: "stale_data" });
  const { element } = await mount(async () => data);
  assert.equal((element("weeklyDays").innerHTML.match(/data-weekly-state=/g) || []).length, 28);
  assert.match(element("weeklyDays").innerHTML, /Vēl nav publicēts/);
  assert.match(element("weeklyStoreGroups").innerHTML, /Piedāvājumu dati nav pilnīgi/);
  assert.doesNotMatch(element("weeklyStoreGroups").innerHTML, /šajā dienā nesākas/);
  assert.equal(element("weeklyRetailerCount").textContent, "—");
  assert.equal(element("weeklyNextActivity").textContent, "Dati nepilnīgi");
});

test("selected retailer uses its own trust state and verified empty remains explicit", async () => {
  const { element, select } = await mount(async () => payload({ edeka: "source_unavailable" }));
  select("edeka");
  assert.match(element("weeklyStoreGroups").innerHTML, /edeka: Dati nav pieejami/);
  assert.doesNotMatch(element("weeklyDays").innerHTML, /aldi_nord:/);
  select("aldi_nord");
  assert.match(element("weeklyStoreGroups").innerHTML, /šajā dienā nesākas/);
  assert.equal(element("weeklyRetailerCount").textContent, "0");
});

test("week cache retains trust metadata alongside offers", async () => {
  let requests = 0;
  const { ui, element } = await mount(async () => { requests += 1; return payload({ netto: "stale_data" }); });
  await ui.load(dates[1]);
  assert.equal(requests, 1);
  assert.match(element("weeklyDays").innerHTML, /netto: Dati novecojuši/);
});

test("missing metadata preserves visible offers while unavailable sources remain disclosed", async () => {
  const data = payload();
  delete data.retailers;
  const deal = { offer_candidate_id: "fixture-a", source_chain: "lidl", product_name_raw: "Fixture", valid_from: dates[0], valid_until: dates[0], price_eur: 1 };
  data.days[0].deals = [deal];
  const { element } = await mount(async () => data);
  assert.match(element("weeklyStoreGroups").innerHTML, /data-weekly-deal-id="fixture-a"/);
  assert.match(element("weeklyStoreGroups").innerHTML, /Datu statuss nav pieejams/);
});

test("missing or duplicate day payloads fail instead of manufacturing empty dates", async () => {
  for (const corrupt of [
    (data) => data.days.pop(),
    (data) => { data.days[1].date = data.days[0].date; },
    (data) => { data.days[1].deals = null; },
  ]) {
    const data = payload(); corrupt(data);
    const { element } = await mount(async () => data);
    assert.match(element("weeklyStoreGroups").innerHTML, /neizdevās ielādēt/);
    assert.equal(element("weeklyRetailerCount").textContent, "—");
  }
});

test("overlapping periods deduplicate offers and count each single-day offer once", async () => {
  const data = payload({ lidl: "offers" });
  const deal = { offer_candidate_id: "fixture-a", source_chain: "lidl", product_name_raw: "Fixture", valid_from: dates[0], valid_until: dates[0], app_valid_from: dates[1], app_valid_until: dates[1] };
  data.days[0].deals = [deal, deal]; data.days[1].deals = [deal];
  const { element, ui } = await mount(async () => data);
  assert.equal(element("weeklySingleDay").textContent, "1");
  assert.equal((element("weeklyStoreGroups").innerHTML.match(/data-weekly-deal-id="fixture-a"/g) || []).length, 1);
  await ui.load(dates[2]);
  assert.doesNotMatch(element("weeklyStoreGroups").innerHTML, /data-weekly-deal-id="fixture-a"/);
});

test("cross-week Thursday-Saturday offer continues on selected day and expires on Sunday", async () => {
  const data = payload({ aldi_nord: "offers" });
  const deal = { offer_candidate_id: "fixture-period", source_chain: "aldi_nord", product_name_raw: "Fixture", valid_from: dates[3], valid_until: dates[5] };
  for (const index of [3, 4, 5]) data.days[index].deals = [deal];
  const { element, ui } = await mount(async () => data);
  await ui.load(dates[4]);
  assert.match(element("weeklyContinuingList").innerHTML, /fixture-period/);
  await ui.load(dates[6]);
  assert.equal(element("weeklyContinuing").hidden, true);
});

test("freshness is source-provided and exact parser failure reasons remain distinct", () => {
  assert.equal(weeklyRetailerFreshness(null), "");
  assert.equal(weeklyRetailerFreshness({}), "");
  assert.equal(weeklyRetailerFreshness({ last_verified_campaign: "fixture-campaign" }), "Pārbaudītā kampaņa: fixture-campaign");
  const status = weeklyRetailerPresentation({ state: "source_unavailable", reason: "netto_relevant_snapshot_parse_unavailable" }, "Netto");
  assert.equal(status.short, "Avota apstrāde neizdevās");
  assert.equal(status.confirmedEmpty, false);
  const futureRetailer = weeklyRetailerPresentation({ state: "source_unavailable", reason: "future_retailer_parse_unavailable" }, "Future");
  assert.equal(futureRetailer.short, "Avota apstrāde neizdevās");
});
