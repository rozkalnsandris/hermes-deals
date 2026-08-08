import test from "node:test";
import assert from "node:assert/strict";

import {
  activeCanonicalEntries,
  basketComparePayload,
  basketComparisonHeadline,
  listCopyText,
  listEntries,
  normalizeListItem,
  normalizeStoredList,
} from "../src/features/shopping-list.js";

const euro = new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" });
const fmtDate = (value) => ({ "2026-08-08": "08.08.2026", "2026-08-09": "09.08.2026" }[value] || value || "—");

test("shopping-list normalization preserves v1 schema limits", () => {
  assert.equal(normalizeListItem("x", null), null);
  assert.deepEqual(
    normalizeListItem("fallback", { kind: "deal", quantity: 500, note: "x".repeat(200), completed: 1 }),
    {
      kind: "deal",
      quantity: 99,
      note: "x".repeat(160),
      completed: true,
      id: "fallback",
    },
  );
  assert.deepEqual(normalizeStoredList([]), {});
  assert.deepEqual(normalizeStoredList({ a: { name: "Piens", quantity: 0 } }), {
    a: { id: "a", name: "Piens", kind: "canonical", quantity: 1, note: "", completed: false },
  });
});

test("list order keeps active items before completed items", () => {
  const rows = listEntries({
    c: { id: "c", name: "C", completed: true },
    b: { id: "b", name: "B", completed: false },
    a: { id: "a", name: "A", completed: false },
  });
  assert.deepEqual(rows.map((row) => row.id), ["a", "b", "c"]);
});

test("canonical basket payload excludes completed and retailer-deal rows", () => {
  const items = {
    a: { id: "a", kind: "canonical", name: "A", quantity: 2, completed: false },
    b: { id: "b", kind: "canonical", name: "B", quantity: 1, completed: true },
    "deal:c": { id: "deal:c", kind: "deal", deal_id: "c", name: "C", quantity: 3, completed: false },
  };
  assert.deepEqual(activeCanonicalEntries(items).map((row) => row.id), ["a"]);
  assert.deepEqual(basketComparePayload("2026-08-08", items), {
    as_of: "2026-08-08",
    items: [{ canonical_product_id: "a", quantity: 2 }],
  });
});

test("copy text preserves deal metadata, quantity, note and completion markers", () => {
  const items = {
    canonical: { id: "canonical", kind: "canonical", name: "Piens", quantity: 2, note: "2%", completed: false },
    "deal:abc": {
      id: "deal:abc",
      kind: "deal",
      name: "Siers",
      retailer: "lidl",
      price_eur: 1.99,
      package_text: "200 g",
      valid_from: "2026-08-08",
      valid_until: "2026-08-09",
      quantity: 1,
      note: "akcija",
      completed: true,
    },
  };
  assert.equal(
    listCopyText(items, { euro, fmtDate }),
    "☐ 2× Piens — Piezīme: 2%\n✓ 1× Siers — Lidl · 1,99 € · 200 g · 08.08.2026–09.08.2026 — Piezīme: akcija",
  );
});

test("basket headline keeps comparison availability semantics", () => {
  assert.equal(
    basketComparisonHeadline({ comparison_available: true, best_complete_total_eur: 12.5 }, { euro }),
    "Salīdzinājums pieejams · zemākais pilnais grozs 12,50 €",
  );
  assert.equal(
    basketComparisonHeadline({ comparison_available: false, complete_retailer_scope_count: 1 }, { euro }),
    "Pilnu grozu sedz viens veikals",
  );
  assert.equal(
    basketComparisonHeadline({ comparison_available: false, complete_retailer_scope_count: 0 }, { euro }),
    "Pilnu grozu pašlaik nesedz neviens veikals",
  );
});
