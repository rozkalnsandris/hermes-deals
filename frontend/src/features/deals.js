import { esc } from "../core/dom.js";

export const PAGE_SIZE = 12;
export const DEAL_SORTS = new Set(["name", "price_asc", "price_desc", "newest", "discount_desc"]);
export const EURO = new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" });

export function retailerName(chain) {
  return {
    aldi_nord: "ALDI Nord",
    edeka: "EDEKA",
    lidl: "Lidl",
    netto: "Netto",
  }[chain] || chain;
}

export function rawPackage(deal) {
  return deal.package_text_raw || "Iepakojums nav norādīts";
}

export function isUnitBasis(deal) {
  return ["unit_price_only", "example_total_plus_unit", "app_example_total_plus_unit"].includes(deal.pricing_mode || "");
}

export function unitBasisMeta(deal, { euro = EURO } = {}) {
  if (!isUnitBasis(deal)) return "";
  const parts = [];
  if (deal.unit_price_eur != null) {
    parts.push(`${euro.format(Number(deal.unit_price_eur))}${deal.unit_label ? ` / ${esc(deal.unit_label)}` : ""}`);
  }
  if (deal.regular_unit_price_eur != null) {
    parts.push(`parasti ${euro.format(Number(deal.regular_unit_price_eur))}${deal.unit_label ? ` / ${esc(deal.unit_label)}` : ""}`);
  }
  if (deal.example_weight_g != null) parts.push(`piemērs ~${Number(deal.example_weight_g).toLocaleString("lv-LV")} g`);
  return parts.length ? `<div>${parts.join(" · ")}</div>` : "";
}

export function dealPrimaryPrice(deal, { euro = EURO } = {}) {
  if (deal.pricing_mode === "unit_price_only" && deal.unit_price_eur != null) {
    return [`${euro.format(Number(deal.unit_price_eur))}${deal.unit_label ? ` / ${esc(deal.unit_label)}` : ""}`, "Cena pēc svara"];
  }
  if (deal.pricing_mode === "app_example_total_plus_unit") {
    return [`ca. ${euro.format(Number(deal.price_eur))}`, "Lidl Plus piemēra cena"];
  }
  if (deal.pricing_mode === "example_total_plus_unit") {
    return [`ca. ${euro.format(Number(deal.price_eur))}`, "Piemēra cena"];
  }
  return [euro.format(Number(deal.price_eur)), "retailer cena"];
}

export function dealListId(deal) {
  return `deal:${deal.offer_candidate_id}`;
}

export function rawDealCard(deal, { items = {}, euro = EURO } = {}) {
  const listId = dealListId(deal);
  const inList = Boolean(items[listId]);
  const primary = dealPrimaryPrice(deal, { euro });
  const regular = deal.regular_price_eur != null ? `<div class="regular">${euro.format(Number(deal.regular_price_eur))}</div>` : "";
  const flags = `${deal.canonical_comparable ? `<span class="badge good">Salīdzināms</span>` : `<span class="badge">Retailer deal</span>`}${deal.requires_app ? `<span class="badge warn">App</span>` : ""}${deal.coupon_required ? `<span class="badge warn">Kupons</span>` : ""}`;
  const listLabel = inList ? "Sarakstā ✓" : "Sarakstam +";
  const listTitle = inList ? "Piedāvājums jau ir iepirkumu sarakstā" : "Pievienot piedāvājumu iepirkumu sarakstam";
  const media = deal.source_image_url
    ? `<div class="media"><img src="${esc(deal.source_image_url)}" alt="${esc(deal.product_name_raw)}" loading="lazy"></div>`
    : `<div class="media"><div class="media-placeholder">H</div></div>`;
  return `<article class="card reference-product-card" data-deal-id="${esc(deal.offer_candidate_id)}">${media}<div class="card-main"><h2 class="product-name">${esc(deal.product_name_raw)}</h2><div class="brand-name">${esc(deal.brand_raw || retailerName(deal.source_chain))}</div><span class="package">${esc(rawPackage(deal))}</span><div class="badge-row">${flags}</div></div><div class="price-block"><div class="price">${primary[0]}</div>${regular}<div class="price-note">${primary[1]}</div></div><div class="product-footer"><span>${esc(retailerName(deal.source_chain))}</span><span class="product-chevron">›</span></div><div class="actions"><button class="btn raw-detail" type="button" aria-label="Atvērt piedāvājuma detaļas">Detaļas</button><button class="btn primary deal-list-add ${inList ? "active" : ""}" type="button" aria-label="${esc(listTitle)}" title="${esc(listTitle)}">${listLabel}</button></div></article>`;
}

export function dealsUrl({
  asOf,
  sort = "name",
  page = 1,
  pageSize = PAGE_SIZE,
  dealView = "current",
  query = "",
  selectedRetailer = "",
  features = {},
} = {}) {
  const safeSort = DEAL_SORTS.has(sort) ? sort : "name";
  const safePage = Math.max(1, Number(page) || 1);
  const params = new URLSearchParams({
    as_of: String(asOf || ""),
    sort: safeSort,
    limit: String(pageSize),
    offset: String((safePage - 1) * pageSize),
    view: dealView === "upcoming" ? "upcoming" : "current",
  });
  const q = String(query || "").trim();
  if (q) params.set("q", q);
  if (selectedRetailer) params.set("retailer", selectedRetailer);
  if (features.app) params.set("app_only", "true");
  if (features.coupon) params.set("coupon_only", "true");
  if (features.discount) params.set("discount_only", "true");
  if (features.image) params.set("image_only", "true");
  return `/api/v1/deals/current?${params.toString()}`;
}

export function paginationItems(page, totalPages) {
  const out = [];
  for (let candidate = 1; candidate <= totalPages; candidate += 1) {
    if (candidate === 1 || candidate === totalPages || Math.abs(candidate - page) <= 2) out.push(candidate);
    else if (out[out.length - 1] !== "…") out.push("…");
  }
  return out;
}

export function dealPageSummary(payload, { dealView = "current", formatDate = (value) => value } = {}) {
  const upcoming = dealView === "upcoming";
  const total = Number(payload?.available_count || 0);
  const start = Number(payload?.offset || 0);
  const count = Number(payload?.count || 0);
  const end = start + count;
  const noun = upcoming ? "drīzumā gaidāmiem" : "aktuāliem";
  return total
    ? `${start + 1}–${end} no ${total} ${noun} piedāvājumiem · ${formatDate(payload?.as_of)}`
    : `0 ${upcoming ? "drīzumā gaidāmu" : "aktuālu"} piedāvājumu · ${formatDate(payload?.as_of)}`;
}

export function initCurrentDeals(app) {
  const {
    fetchJson,
    fmtDate,
    grid,
    summary,
    pagination,
    search,
    sort,
    getAsOf,
    getDealView,
    getSelectedRetailer,
    getFeatureState,
    getItems,
    emptyState,
    bindRawDeals,
    bindEmptyActions,
    updateControlRoomStatus,
    updateFilterCounts,
    updateReviewSearchHint,
    gridErrorState,
    bindGridRetry,
    scrollTarget,
  } = app;

  let currentPage = 1;
  let currentDealData = null;
  let dealCache = new Map();

  function currentUrl() {
    return dealsUrl({
      asOf: getAsOf(),
      sort: sort.value,
      page: currentPage,
      dealView: getDealView(),
      query: search.value,
      selectedRetailer: getSelectedRetailer(),
      features: getFeatureState(),
    });
  }

  function renderPagination(totalItems) {
    const totalPages = Math.max(1, Math.ceil(totalItems / PAGE_SIZE));
    if (totalItems <= PAGE_SIZE) {
      pagination.innerHTML = "";
      return;
    }
    currentPage = Math.min(Math.max(1, currentPage), totalPages);
    const middle = paginationItems(currentPage, totalPages).map((page) =>
      page === "…"
        ? `<span class="page-ellipsis">…</span>`
        : `<button type="button" class="page-btn${page === currentPage ? " active" : ""}" data-page="${page}" ${page === currentPage ? 'aria-current="page"' : ""}>${page}</button>`).join("");
    pagination.innerHTML = `<button type="button" class="page-btn" data-page="1" ${currentPage === 1 ? "disabled" : ""} aria-label="Pirmā lapa">⇤</button><button type="button" class="page-btn" data-page="${currentPage - 1}" ${currentPage === 1 ? "disabled" : ""} aria-label="Iepriekšējā lapa">←</button>${middle}<button type="button" class="page-btn" data-page="${currentPage + 1}" ${currentPage === totalPages ? "disabled" : ""} aria-label="Nākamā lapa">→</button><button type="button" class="page-btn" data-page="${totalPages}" ${currentPage === totalPages ? "disabled" : ""} aria-label="Pēdējā lapa">⇥</button>`;
    pagination.querySelectorAll("button[data-page]").forEach((button) => button.addEventListener("click", async () => {
      const next = Number(button.dataset.page);
      if (!Number.isFinite(next) || next < 1 || next > totalPages || next === currentPage) return;
      currentPage = next;
      await load({ resetPage: false });
      scrollTarget?.scrollIntoView({ behavior: "smooth", block: "start" });
    }));
  }

  function render() {
    const payload = currentDealData;
    if (!payload) {
      pagination.innerHTML = "";
      return;
    }
    const items = payload.deals || [];
    const view = getDealView();
    summary.textContent = dealPageSummary(payload, { dealView: view, formatDate: fmtDate });
    grid.innerHTML = items.length
      ? items.map((deal) => rawDealCard(deal, { items: getItems() })).join("")
      : emptyState(view === "upcoming" ? "Šim filtram nav drīzumā gaidāmu piedāvājumu." : "Šim filtram nav aktuālu piedāvājumu.");
    bindRawDeals();
    bindEmptyActions();
    renderPagination(Number(payload.available_count || 0));
    updateControlRoomStatus(payload);
  }

  async function load({ resetPage = true, isCurrent = () => true } = {}) {
    if (resetPage) currentPage = 1;
    grid.innerHTML = `<div class="empty"><span class="loading"></span>Ielādēju…</div>`;
    pagination.innerHTML = "";
    try {
      const payload = await fetchJson(currentUrl());
      if (!isCurrent()) return false;
      currentDealData = payload;
      dealCache = new Map((payload.deals || []).map((deal) => [deal.offer_candidate_id, deal]));
      updateFilterCounts(payload);
      render();
      await updateReviewSearchHint(payload, isCurrent);
      return isCurrent();
    } catch (error) {
      if (!isCurrent()) return false;
      pagination.innerHTML = "";
      currentDealData = null;
      summary.textContent = "Dati īslaicīgi nav pieejami";
      grid.innerHTML = gridErrorState(error);
      bindGridRetry();
      return false;
    }
  }

  return Object.freeze({
    load,
    render,
    currentUrl,
    getCurrentPage: () => currentPage,
    getCurrentDealData: () => currentDealData,
    getDealCache: () => dealCache,
  });
}
