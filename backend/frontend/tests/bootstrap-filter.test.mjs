import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

import {
  BOOTSTRAP_CONTRACT,
  SEARCH_DEBOUNCE_MS,
  TOAST_DURATION_MS,
} from "../src/bootstrap.js";
import {
  activeFilterLabels,
  normalizeSortForMode,
} from "../src/ui/filters.js";

const root = resolve(import.meta.dirname, "..");

test("bootstrap identity and legacy timing constants remain explicit", () => {
  assert.equal(BOOTSTRAP_CONTRACT, "w3-behavior-preserving-bootstrap-v1");
  assert.equal(SEARCH_DEBOUNCE_MS, 250);
  assert.equal(TOAST_DURATION_MS, 2200);
});

test("mode-specific sort normalization preserves legacy rules", () => {
  assert.equal(normalizeSortForMode("deals", "retailers_desc"), "name");
  assert.equal(normalizeSortForMode("canonical", "newest"), "name");
  assert.equal(normalizeSortForMode("canonical", "discount_desc"), "name");
  assert.equal(normalizeSortForMode("deals", "discount_desc"), "discount_desc");
  assert.equal(normalizeSortForMode("canonical", "retailers_desc"), "retailers_desc");
});

test("filter summary labels preserve current user-visible semantics", () => {
  assert.deepEqual(activeFilterLabels({
    mode: "deals",
    query: " piens ",
    retailer: "lidl",
    sort: "discount_desc",
    dealView: "upcoming",
    currentOnly: false,
    comparisonOnly: false,
    features: { app: true, coupon: true, discount: false, image: true },
  }, "Lielākā atlaide vispirms"), [
    "Meklēšana: piens",
    "Lidl",
    "Lielākā atlaide vispirms",
    "Drīzumā",
    "App",
    "Kupons",
    "Ar attēlu",
  ]);

  assert.deepEqual(activeFilterLabels({
    mode: "canonical",
    query: "",
    retailer: "",
    sort: "name",
    dealView: "current",
    currentOnly: true,
    comparisonOnly: true,
    features: {},
  }), ["Tikai aktuālie", "Tikai salīdzināmi"]);
});

test("bootstrap source preserves legacy startup boundary without auto-loading initial grid", async () => {
  const source = await readFile(resolve(root, "src/bootstrap.js"), "utf8");
  const entry = await readFile(resolve(root, "src/app.js"), "utf8");

  assert.match(source, /async function loadInitialPage\(\)/);
  assert.doesNotMatch(source, /\bvoid\s+loadInitialPage\(\)|\bawait\s+loadInitialPage\(\)/);
  assert.match(source, /initWeeklyOverview\(/);
  assert.match(entry, /bootstrapUi\(\);/);
  assert.match(source, /Promise\.allSettled\(\[\s*loadOverview\(\),\s*loadGrid\(\),\s*dailyController\.load\(\),/s);
});

test("bootstrap source pins mode trust copy, date validation, keyboard and review wiring", async () => {
  const source = await readFile(resolve(root, "src/bootstrap.js"), "utf8");
  for (const marker of [
    "Raw deal nav automātiski tas pats produkts citā veikalā.",
    "Šajā skatā ir tikai apstiprinātie canonical produkti.",
    "Ievadi datumu formātā DD.MM.GGGG",
    'event.key === "/"',
    'event.key !== "Escape"',
    "SEARCH_DEBOUNCE_MS",
    "initReviewRefresh",
    "navigationController.restoreUrl()",
  ]) {
    assert.ok(source.includes(marker), `missing bootstrap marker: ${marker}`);
  }
});
