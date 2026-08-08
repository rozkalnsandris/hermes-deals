import { $, esc } from "../core/dom.js";
import { STORAGE_KEY, readJson, writeJson } from "../core/storage.js";
import { EURO, dealListId, rawPackage, retailerName } from "./deals.js";

export function normalizeListItem(key, item) {
  if (!item || typeof item !== "object") return null;
  const id = String(item.id || key);
  const kind = item.kind === "deal" ? "deal" : "canonical";
  const quantity = Math.max(1, Math.min(99, Number(item.quantity) || 1));
  const note = String(item.note || "").slice(0, 160);
  return { ...item, id, kind, quantity, note, completed: Boolean(item.completed) };
}

export function normalizeStoredList(raw) {
  if (!raw || Array.isArray(raw) || typeof raw !== "object") return {};
  const out = {};
  for (const [key, item] of Object.entries(raw)) {
    const normalized = normalizeListItem(key, item);
    if (normalized) out[normalized.id] = normalized;
  }
  return out;
}

export function loadShoppingList() {
  return normalizeStoredList(readJson(STORAGE_KEY, {}));
}

export function listEntries(items) {
  return Object.values(items || {}).sort((a, b) =>
    Number(a.completed) - Number(b.completed) || String(a.name).localeCompare(String(b.name), "lv"));
}

export function activeCanonicalEntries(items) {
  return listEntries(items).filter((item) => !item.completed && item.kind === "canonical");
}

export function listEntryMeta(item, { euro = EURO, fmtDate = (value) => value } = {}) {
  if (item.kind === "deal") {
    const parts = [retailerName(item.retailer)];
    if (item.price_eur != null) parts.push(euro.format(Number(item.price_eur)));
    if (item.package_text) parts.push(item.package_text);
    if (item.valid_from || item.valid_until) parts.push(`${fmtDate(item.valid_from)}–${fmtDate(item.valid_until)}`);
    return parts.join(" · ");
  }
  return "Canonical saraksta vienība · pieejama groza salīdzināšanai";
}

export function listCopyText(items, options = {}) {
  return listEntries(items).map((item) =>
    `${item.completed ? "✓" : "☐"} ${item.quantity}× ${item.name}${item.kind === "deal" ? ` — ${listEntryMeta(item, options)}` : ""}${item.note ? ` — Piezīme: ${item.note}` : ""}`,
  ).join("\n");
}

export function basketComparePayload(asOf, items) {
  return {
    as_of: asOf,
    items: activeCanonicalEntries(items).map((item) => ({
      canonical_product_id: item.id,
      quantity: item.quantity,
    })),
  };
}

export function basketComparisonHeadline(result, { euro = EURO } = {}) {
  if (result.comparison_available) {
    return `Salīdzinājums pieejams · zemākais pilnais grozs ${euro.format(Number(result.best_complete_total_eur))}`;
  }
  if (result.complete_retailer_scope_count === 1) return "Pilnu grozu sedz viens veikals";
  return "Pilnu grozu pašlaik nesedz neviens veikals";
}

export function initShoppingList(app) {
  const {
    fetchJson,
    fmtDate,
    euro = EURO,
    getAsOf,
    notify = () => {},
    getDealCache = () => new Map(),
  } = app;

  const state = { items: loadShoppingList() };
  const listRows = $("listRows");
  const listSummary = $("listSummary");
  const listCount = $("listCount");
  const listCountSide = $("listCountSide");
  const basketResults = $("basketResults");
  const clearDone = $("clearDone");
  const compareBasketButton = $("compareBasket");

  function persist() {
    writeJson(STORAGE_KEY, state.items);
    render();
    syncButtons();
  }

  function addCanonical(product) {
    const existing = state.items[product.id];
    state.items[product.id] = {
      id: product.id,
      kind: "canonical",
      name: product.display_name,
      image: product.primary_image_url || null,
      quantity: existing?.quantity || 1,
      note: existing?.note || "",
      completed: existing?.completed || false,
    };
    persist();
  }

  function addDeal(deal) {
    const id = dealListId(deal);
    const existing = state.items[id];
    state.items[id] = {
      id,
      kind: "deal",
      deal_id: deal.offer_candidate_id,
      name: deal.product_name_raw,
      retailer: deal.source_chain,
      store_name: deal.source_store_name || null,
      price_eur: deal.price_eur,
      package_text: rawPackage(deal),
      valid_from: deal.valid_from,
      valid_until: deal.valid_until,
      quantity: existing?.quantity || 1,
      note: existing?.note || "",
      completed: existing?.completed || false,
    };
    persist();
  }

  function setQty(id, delta) {
    const item = state.items[id];
    if (!item) return;
    item.quantity = Math.max(1, Math.min(99, item.quantity + delta));
    persist();
  }

  function setNote(id, value) {
    const item = state.items[id];
    if (!item) return;
    item.note = String(value || "").slice(0, 160);
    persist();
  }

  function toggleDone(id) {
    const item = state.items[id];
    if (!item) return;
    item.completed = !item.completed;
    persist();
  }

  function removeItem(id) {
    delete state.items[id];
    persist();
  }

  function render() {
    const entries = listEntries(state.items);
    const active = entries.filter((item) => !item.completed);
    const remaining = active.length;
    const done = entries.length - remaining;
    const knownTotal = active
      .filter((item) => item.kind === "deal" && Number.isFinite(Number(item.price_eur)))
      .reduce((sum, item) => sum + Number(item.price_eur) * item.quantity, 0);
    const unknownPrice = active.filter((item) => item.kind !== "deal" || !Number.isFinite(Number(item.price_eur))).length;

    if (listCount) listCount.textContent = String(remaining);
    if (listCountSide) listCountSide.textContent = String(remaining);
    if (listSummary) {
      listSummary.innerHTML = entries.length
        ? `<span>${remaining} atlikušas</span><span>${done} nopirktas</span><span>Zināmā summa ${euro.format(knownTotal)}</span><span>${unknownPrice} bez cenas</span>`
        : "";
    }
    if (listRows) {
      listRows.innerHTML = entries.length
        ? entries.map((item) => `<div class="list-row ${item.completed ? "completed" : ""}"><input class="list-check" type="checkbox" data-id="${esc(item.id)}" ${item.completed ? "checked" : ""} aria-label="${item.completed ? "Atzīmēt kā nenopirktu" : "Atzīmēt kā nopirktu"}: ${esc(item.name)}"><div><div class="list-name">${esc(item.name)}</div><div class="list-meta">${esc(listEntryMeta(item, { euro, fmtDate }))}</div><span class="list-kind ${item.kind === "deal" ? "deal" : ""}">${item.kind === "deal" ? "Konkrēts veikala piedāvājums" : "Canonical produkts"}</span><input class="list-note" data-note-id="${esc(item.id)}" value="${esc(item.note || "")}" maxlength="160" placeholder="Piezīme ģimenei…" aria-label="Piezīme: ${esc(item.name)}"><button class="btn remove-item" data-id="${esc(item.id)}" type="button">Noņemt</button></div><div class="qty"><button data-id="${esc(item.id)}" data-delta="-1" type="button">−</button><span>${item.quantity}</span><button data-id="${esc(item.id)}" data-delta="1" type="button">+</button></div></div>`).join("")
        : '<div class="empty">Saraksts ir tukšs. Var pievienot gan konkrētus veikala piedāvājumus, gan canonical produktus.</div>';
      listRows.querySelectorAll(".qty button").forEach((button) => button.addEventListener("click", () => setQty(button.dataset.id, Number(button.dataset.delta))));
      listRows.querySelectorAll(".list-check").forEach((box) => box.addEventListener("change", () => toggleDone(box.dataset.id)));
      listRows.querySelectorAll(".list-note").forEach((input) => input.addEventListener("change", () => setNote(input.dataset.noteId, input.value)));
      listRows.querySelectorAll(".remove-item").forEach((button) => button.addEventListener("click", () => removeItem(button.dataset.id)));
    }
    if (basketResults) basketResults.innerHTML = "";
    if (clearDone) clearDone.disabled = done === 0;
    if (compareBasketButton) compareBasketButton.disabled = activeCanonicalEntries(state.items).length === 0;
  }

  function syncButtons() {
    document.querySelectorAll(".card[data-product-id]").forEach((card) => {
      const button = card.querySelector(".list-add");
      const active = Boolean(state.items[card.dataset.productId]);
      if (!button) return;
      const title = active ? "Produkts jau ir iepirkumu sarakstā" : "Pievienot produktu iepirkumu sarakstam";
      button.classList.toggle("active", active);
      button.textContent = active ? "Sarakstā ✓" : "Sarakstam +";
      button.setAttribute("aria-label", title);
      button.title = title;
    });
    const dealCache = getDealCache();
    document.querySelectorAll(".card[data-deal-id]").forEach((card) => {
      const deal = dealCache.get(card.dataset.dealId);
      const button = card.querySelector(".deal-list-add");
      const active = deal ? Boolean(state.items[dealListId(deal)]) : false;
      if (!button) return;
      const title = active ? "Piedāvājums jau ir iepirkumu sarakstā" : "Pievienot piedāvājumu iepirkumu sarakstam";
      button.classList.toggle("active", active);
      button.textContent = active ? "Sarakstā ✓" : "Sarakstam +";
      button.setAttribute("aria-label", title);
      button.title = title;
    });
  }

  function clearCompleted() {
    for (const item of listEntries(state.items).filter((entry) => entry.completed)) delete state.items[item.id];
    persist();
  }

  function clearAll() {
    state.items = {};
    persist();
    if (basketResults) basketResults.innerHTML = '<div class="empty">Ģimenes saraksts notīrīts.</div>';
  }

  async function copy() {
    const text = listCopyText(state.items, { euro, fmtDate });
    if (!text) {
      if (basketResults) basketResults.innerHTML = '<div class="empty">Saraksts ir tukšs.</div>';
      return false;
    }
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(text);
      else {
        const area = document.createElement("textarea");
        area.value = text;
        area.style.position = "fixed";
        area.style.opacity = "0";
        document.body.appendChild(area);
        area.select();
        document.execCommand("copy");
        area.remove();
      }
      if (basketResults) basketResults.innerHTML = '<div class="empty">Saraksts nokopēts starpliktuvē.</div>';
      return true;
    } catch {
      if (basketResults) basketResults.innerHTML = '<div class="error">Sarakstu neizdevās nokopēt.</div>';
      return false;
    }
  }

  async function compareBasket() {
    const entries = activeCanonicalEntries(state.items);
    const excluded = listEntries(state.items).filter((item) => !item.completed && item.kind !== "canonical").length;
    if (!entries.length) {
      if (basketResults) basketResults.innerHTML = `<div class="empty">Nav nenopirktu canonical produktu salīdzināšanai.${excluded ? ` ${excluded} konkrēti veikala piedāvājumi paliek sarakstā, bet netiek salīdzināti.` : ""}</div>`;
      return false;
    }
    if (basketResults) basketResults.innerHTML = '<div class="empty"><span class="loading"></span>Salīdzinu canonical grozu…</div>';
    try {
      const result = await fetchJson("/api/v1/ui/basket/compare", {
        method: "POST",
        body: JSON.stringify(basketComparePayload(getAsOf(), state.items)),
      });
      const headline = basketComparisonHeadline(result, { euro });
      const excludedNote = excluded ? `<div class="empty">${excluded} konkrēti veikala piedāvājumi nav iekļauti canonical salīdzinājumā.</div>` : "";
      const scopes = (result.retailer_scopes || []).map((scope) => {
        const best = (result.best_complete_scopes || []).some((candidate) => candidate.source_chain === scope.source_chain && candidate.source_store_external_id === scope.source_store_external_id);
        return `<div class="basket-scope ${scope.complete_basket ? "complete" : ""} ${best ? "best" : ""}"><div class="scope-head"><span>${esc(retailerName(scope.source_chain))}</span><span>${euro.format(Number(scope.total_eur))}</span></div><div class="scope-meta">${scope.covered_product_count}/${scope.requested_product_count} produkti ${scope.complete_basket ? "· pilns grozs" : "· daļējs grozs"}</div><div class="scope-lines">${(scope.lines || []).map((line) => `<div class="scope-line"><span>${esc(line.quantity)}× ${esc(line.display_name)}</span><strong>${euro.format(Number(line.line_total_eur))}</strong></div>`).join("")}</div></div>`;
      }).join("");
      if (basketResults) basketResults.innerHTML = `<div class="section-title">${esc(headline)}</div>${excludedNote}${scopes || '<div class="empty">Nav current offer.</div>'}`;
      return true;
    } catch (error) {
      if (basketResults) basketResults.innerHTML = `<div class="error">Groza salīdzinājums neizdevās: ${esc(error.message)}</div>`;
      return false;
    }
  }

  return Object.freeze({
    state,
    persist,
    render,
    syncButtons,
    addCanonical,
    addDeal,
    setQty,
    setNote,
    toggleDone,
    removeItem,
    clearCompleted,
    clearAll,
    copy,
    compareBasket,
    notify,
  });
}
