import test from "node:test";
import assert from "node:assert/strict";

import {
  normalizeWeeklyRetailerStates,
  weeklyRetailerIsTrustedEmpty,
  weeklyRetailerPresentation,
  weeklyUnavailableRetailers,
} from "../src/features/weekly-trust-state.js";

function retailer(retailer_key, state, overrides = {}) {
  return {
    retailer_key,
    display_name: retailer_key,
    source_chain: retailer_key,
    state,
    reason: `${retailer_key}_${state}`,
    deal_count: 0,
    active_dates: [],
    ...overrides,
  };
}

function fullRows(overrides = {}) {
  return [
    retailer("lidl", overrides.lidl || "not_supported"),
    retailer("aldi_nord", overrides.aldi_nord || "no_offers"),
    retailer("netto", overrides.netto || "offers", { deal_count: overrides.netto === "no_offers" ? 0 : 3 }),
    retailer("edeka", overrides.edeka || "stale_data"),
  ];
}

test("weekly trust-state normalization requires all four unique retailers", () => {
  const states = normalizeWeeklyRetailerStates(fullRows());
  assert.equal(states.size, 4);
  assert.equal(states.get("netto").state, "offers");
  assert.equal(states.get("netto").deal_count, 3);

  assert.throws(
    () => normalizeWeeklyRetailerStates(fullRows().slice(0, 3)),
    /Trūkst weekly retailer trust-state: edeka/,
  );
  assert.throws(
    () => normalizeWeeklyRetailerStates([...fullRows(), retailer("netto", "offers")]),
    /Dublēts weekly retailer trust-state: netto/,
  );
  assert.throws(
    () => normalizeWeeklyRetailerStates(fullRows().map((row) => row.retailer_key === "lidl" ? { ...row, state: "unknown" } : row)),
    /Nezināms weekly retailer state/,
  );
});

test("only offers and verified no-offers are trusted empty states", () => {
  const states = normalizeWeeklyRetailerStates(fullRows());
  assert.equal(weeklyRetailerIsTrustedEmpty(states.get("netto")), true);
  assert.equal(weeklyRetailerIsTrustedEmpty(states.get("aldi_nord")), true);
  assert.equal(weeklyRetailerIsTrustedEmpty(states.get("lidl")), false);
  assert.equal(weeklyRetailerIsTrustedEmpty(states.get("edeka")), false);
  assert.equal(weeklyRetailerIsTrustedEmpty(null), false);
});

test("unavailable states never use confirmed-zero wording", () => {
  for (const [state, expected] of [
    ["not_published_yet", "Vēl nav publicēts"],
    ["source_unavailable", "Dati nav pieejami"],
    ["stale_data", "Dati novecojuši"],
    ["not_supported", "Avots vēl nav atbalstīts"],
  ]) {
    const presentation = weeklyRetailerPresentation(retailer("lidl", state), "Lidl");
    assert.equal(presentation.short, expected);
    assert.equal(presentation.confirmedEmpty, false);
    assert.doesNotMatch(presentation.title, /jaunu akciju nav$/i);
  }
});

test("verified empty and available-week empty remain explicit", () => {
  const noOffers = weeklyRetailerPresentation(retailer("aldi_nord", "no_offers"), "ALDI Nord");
  assert.equal(noOffers.confirmedEmpty, true);
  assert.match(noOffers.short, /Pārbaudīts/);

  const offers = weeklyRetailerPresentation(retailer("netto", "offers"), "Netto");
  assert.equal(offers.confirmedEmpty, true);
  assert.match(offers.short, /Šajā dienā/);
});

test("missing retailer metadata fails visually conservative", () => {
  const presentation = weeklyRetailerPresentation(null, "EDEKA");
  assert.equal(presentation.state, "source_unavailable");
  assert.equal(presentation.confirmedEmpty, false);
  assert.match(presentation.detail, /nevar uzskatīt par apstiprinātu nulles rezultātu/);
});

test("aggregate unavailable inventory excludes trusted-empty retailers", () => {
  const states = normalizeWeeklyRetailerStates(fullRows());
  assert.deepEqual(
    weeklyUnavailableRetailers(states).map(([key, entry]) => [key, entry.state]),
    [
      ["lidl", "not_supported"],
      ["edeka", "stale_data"],
    ],
  );
});
