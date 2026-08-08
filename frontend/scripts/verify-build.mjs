import { createHash } from "node:crypto";
import { readdir, readFile, stat } from "node:fs/promises";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const dist = resolve(root, "dist");

async function walk(path) {
  const entries = [];
  for (const name of (await readdir(path)).sort()) {
    const full = resolve(path, name);
    const info = await stat(full);
    if (info.isDirectory()) entries.push(...await walk(full));
    else entries.push(full);
  }
  return entries;
}

const files = await walk(dist);
const relative = files.map((path) => path.slice(dist.length + 1));
if (relative.length !== 1 || relative[0] !== "app.js") {
  throw new Error(`W3 build must emit exactly dist/app.js; got ${JSON.stringify(relative)}`);
}

const appPath = files[0];
const source = await readFile(appPath, "utf8");
const required = [
  "Europe/Berlin",
  "hermesDeals.shoppingList.v1",
  "hermesDeals.uiPreferences.v4",
  "hermesDeals.viewPreferences.v5",
  "hermesDeals.filterPanel.v1",
  "hermesDealsReviewRefresh",
  "UiApiError",
  "/api/health",
  "/api/v1/ui/overview",
  "/api/v1/review-items?source_chain=lidl&limit=500",
  "/api/v1/deals/current",
  "/api/v1/deals/daily-specials",
  "/api/v1/catalog",
  "/api/v1/ui/basket/compare",
  "/api/v1/canonical-products/",
  "explicit_immutable_retailer_evidence_only",
  "hermes-deals-review",
  "Dati īslaicīgi nav pieejami",
  "Canonical produkts",
  "w3-behavior-preserving-bootstrap-v1",
  "Ievadi datumu formātā DD.MM.GGGG",
];
for (const marker of required) {
  if (!source.includes(marker)) throw new Error(`W3 build missing marker: ${marker}`);
}
if (/sourceMappingURL\s*=/.test(source)) {
  throw new Error("W3 build unexpectedly contains a sourceMappingURL");
}
if (relative.some((name) => name.endsWith(".map"))) {
  throw new Error("W3 build unexpectedly emitted a source-map file");
}
if (/from\s+["']\.\/(?:core|features|ui)\//.test(source)) {
  throw new Error("W3 build retained unresolved source-module imports");
}

const digest = createHash("sha256").update(source).digest("hex");
console.log("HERMES_UI_W3_BUILD=PASS");
console.log(`HERMES_UI_W3_BUILD_BYTES=${Buffer.byteLength(source)}`);
console.log(`HERMES_UI_W3_BUILD_SHA256=${digest}`);
