import test from "node:test";
import assert from "node:assert/strict";

import {
  WEEKLY_SOURCE_CONTRACT,
  WEEKLY_UI_CONTRACT,
  normalizeWeeklyPayloadUrl,
  reconstructWeeklyPayload,
} from "../src/core/weekly-payload-bridge.js";

const origin = "https://deals.example.test";

test("weekly bridge rewrites only same-origin legacy weekly endpoint", () => {
  assert.equal(
    normalizeWeeklyPayloadUrl("/api/v1/deals/weekly-specials?week_start=2026-08-03", origin),
    "/api/v1/deals/weekly-specials/ui?week_start=2026-08-03",
  );
  assert.equal(
    normalizeWeeklyPayloadUrl("https://deals.example.test/api/v1/deals/weekly-specials?week_start=2026-08-03", origin),
    "https://deals.example.test/api/v1/deals/weekly-specials/ui?week_start=2026-08-03",
  );
  assert.equal(normalizeWeeklyPayloadUrl("https://other.test/api/v1/deals/weekly-specials", origin), null);
  assert.equal(normalizeWeeklyPayloadUrl("/api/v1/deals/current", origin), null);
});

test("weekly compact payload reconstructs exact day deal references", () => {
  const payload = reconstructWeeklyPayload({
    ui_contract: WEEKLY_UI_CONTRACT,
    source_contract: WEEKLY_SOURCE_CONTRACT,
    count: 3,
    deals: [
      { offer_candidate_id: "a", product_name_raw: "A" },
      { offer_candidate_id: "b", product_name_raw: "B" },
    ],
    days: [
      { date: "2026-08-03", deal_ids: ["a", "b"] },
      { date: "2026-08-04", deal_ids: ["b"] },
    ],
  });
  assert.deepEqual(payload.days, [
    { date: "2026-08-03", deals: [
      { offer_candidate_id: "a", product_name_raw: "A" },
      { offer_candidate_id: "b", product_name_raw: "B" },
    ] },
    { date: "2026-08-04", deals: [
      { offer_candidate_id: "b", product_name_raw: "B" },
    ] },
  ]);
});

test("weekly compact payload fails closed on trust and reference drift", () => {
  assert.throws(() => reconstructWeeklyPayload({}), /derīgu normalizētu nedēļas datu līgumu/);
  assert.throws(() => reconstructWeeklyPayload({
    ui_contract: WEEKLY_UI_CONTRACT,
    source_contract: WEEKLY_SOURCE_CONTRACT,
    count: 0,
    deals: [{ offer_candidate_id: "a" }, { offer_candidate_id: "a" }],
    days: [],
  }), /dublēts piedāvājuma ID/);
  assert.throws(() => reconstructWeeklyPayload({
    ui_contract: WEEKLY_UI_CONTRACT,
    source_contract: WEEKLY_SOURCE_CONTRACT,
    count: 1,
    deals: [{ offer_candidate_id: "a" }],
    days: [{ date: "2026-08-03", deal_ids: ["missing"] }],
  }), /nezināmu piedāvājumu/);
  assert.throws(() => reconstructWeeklyPayload({
    ui_contract: WEEKLY_UI_CONTRACT,
    source_contract: WEEKLY_SOURCE_CONTRACT,
    count: 2,
    deals: [{ offer_candidate_id: "a" }],
    days: [{ date: "2026-08-03", deal_ids: ["a"] }],
  }), /skaits nesakrīt/);
});
