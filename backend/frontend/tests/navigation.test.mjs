import test from "node:test";
import assert from "node:assert/strict";

import { dateFromOffset, parseViewQuery, viewQuery } from "../src/ui/navigation.js";
import { REVIEW_REFRESH_CHANNEL, REVIEW_REFRESH_DELAY_MS } from "../src/ui/review-refresh.js";

test("view query preserves public URL parameter names and order", () => {
  assert.equal(
    viewQuery({
      mode: "canonical",
      date: "2026-08-08",
      query: " piens ",
      retailer: "netto",
      sort: "price_asc",
      dealView: "upcoming",
      currentOnly: true,
      comparisonOnly: true,
      features: { app: true, coupon: true, discount: true, image: true },
    }),
    "mode=canonical&date=2026-08-08&q=piens&retailer=netto&sort=price_asc&view=upcoming&current=1&comparison=1&app=1&coupon=1&discount=1&image=1",
  );
});

test("view query parser preserves safe mode and feature semantics", () => {
  assert.deepEqual(
    parseViewQuery("?mode=bad&date=2026-08-08&q=x&retailer=lidl&sort=price_desc&view=upcoming&current=1&comparison=0&app=1"),
    {
      mode: "deals",
      date: "2026-08-08",
      query: "x",
      retailer: "lidl",
      sort: "price_desc",
      dealView: "upcoming",
      currentOnly: true,
      comparisonOnly: false,
      features: { app: true },
    },
  );
});

test("quick-date offsets retain calendar-day behavior", () => {
  assert.equal(dateFromOffset(0, "2026-08-08"), "2026-08-08");
  assert.equal(dateFromOffset(1, "2026-08-08"), "2026-08-09");
  assert.equal(dateFromOffset(-1, "2026-08-08"), "2026-08-07");
});

test("review refresh transport constants remain stable", () => {
  assert.equal(REVIEW_REFRESH_CHANNEL, "hermes-deals-review");
  assert.equal(REVIEW_REFRESH_DELAY_MS, 180);
});
