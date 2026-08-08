import { esc } from "../core/dom.js";
import { EURO, retailerName } from "./deals.js";

export const CATALOG_SORTS = new Set(["name", "price_asc", "price_desc", "retailers_desc"]);

export function packageText(product) {
  const parts = [];
  if (product.item_quantity_value != null && product.item_quantity_unit) {
    const value = Number(product.item_quantity_value);
    parts.push(`${Number.isInteger(value) ? value : value.toLocaleString("de-DE")} ${product.item_quantity_unit}`);
  }
  if (product.pack_count != null && product.pack_count !== 1) parts.push(`× ${product.pack_count}`);
  return parts.length ? parts.join(" ") : "Iepakojums nav zināms";
}

export function statusInfo(product) {
  if (product.comparison_status === "multi_store_comparison") return ["good", `Salīdzinājums pieejams · ${product.retailer_count} veikali`];
  if (product.comparison_status === "single_current_offer") return ["warn", "Viens aktuāls veikala piedāvājums"];
  return ["", "Šajā datumā nav aktuāla piedāvājuma"];
}

export function offerHtml(offer, { euro = EURO, fmtDate = (value) => value } = {}) {
  const flags = `${offer.requires_app ? '<span class="badge warn">Lietotne</span>' : ""}${offer.coupon_required ? '<span class="badge warn">Kupons</span>' : ""}${offer.app_price_eur != null ? `<span class="badge warn">App ${euro.format(Number(offer.app_price_eur))}</span>` : ""}`;
  return `<div class="offer"><div><div class="offer-store">${esc(retailerName(offer.source_chain))}${offer.source_store_name ? ` · ${esc(offer.source_store_name)}` : ""}</div><div class="offer-meta">Derīgs ${esc(fmtDate(offer.valid_from))}–${esc(fmtDate(offer.valid_until))}</div><div class="badge-row">${flags}</div></div><div class="offer-price">${euro.format(Number(offer.price_eur))}</div></div>`;
}

export function canonicalCard(product, { items = {}, euro = EURO } = {}) {
  const [cls, text] = statusInfo(product);
  const price = product.lowest_price_eur == null ? '<span class="muted">—</span>' : euro.format(Number(product.lowest_price_eur));
  const inList = Boolean(items[product.id]);
  const stores = Number(product.retailer_count || 0);
  const listLabel = inList ? "Sarakstā ✓" : "Sarakstam +";
  const listTitle = inList ? "Produkts jau ir iepirkumu sarakstā" : "Pievienot produktu iepirkumu sarakstam";
  const media = product.primary_image_url
    ? `<div class="media"><img src="${esc(product.primary_image_url)}" alt="${esc(product.display_name)}" loading="lazy"></div>`
    : '<div class="media"><div class="media-placeholder">H</div></div>';
  return `<article class="card reference-product-card" data-product-id="${esc(product.id)}">${media}<div class="card-main"><h2 class="product-name">${esc(product.display_name)}</h2><div class="brand-name">${esc(product.brand_display || product.brand_normalized || "")}</div><span class="package">${esc(packageText(product))}</span><div class="badge-row"><span class="badge ${cls}">${esc(text)}</span></div></div><div class="price-block"><div class="price">${price}</div><div class="price-note">${product.comparison_available ? "zemākā current cena" : "current cena"}</div></div><div class="product-footer"><span>${stores} ${stores === 1 ? "veikals" : "veikali"}</span><span class="product-chevron">›</span></div><div class="actions"><button class="btn detail-btn" type="button" aria-label="Atvērt produkta detaļas">Detaļas</button><button class="btn primary list-add ${inList ? "active" : ""}" type="button" aria-label="${esc(listTitle)}" title="${esc(listTitle)}">${listLabel}</button></div></article>`;
}

export function canonicalUrl({
  asOf,
  sort = "name",
  query = "",
  selectedRetailer = "",
  currentOnly = false,
  comparisonOnly = false,
} = {}) {
  const params = new URLSearchParams({
    as_of: String(asOf || ""),
    sort: CATALOG_SORTS.has(sort) ? sort : "name",
  });
  const q = String(query || "").trim();
  if (q) params.set("q", q);
  if (selectedRetailer) params.set("retailer", selectedRetailer);
  if (currentOnly) params.set("current_only", "true");
  if (comparisonOnly) params.set("comparison_only", "true");
  return `/api/v1/catalog?${params.toString()}`;
}

export function canonicalDetailUrls(id, asOf) {
  return [
    `/api/v1/canonical-products/${id}`,
    `/api/v1/canonical-products/${id}/current-offers?as_of=${encodeURIComponent(asOf)}`,
    `/api/v1/canonical-products/${id}/price-history?limit=60`,
  ];
}

export function chartSvg(rows) {
  if (rows.length < 2) return '<div class="muted">Grafikam vajag vismaz divus novērojumus.</div>';
  const sorted = [...rows].sort((a, b) => new Date(a.collected_at) - new Date(b.collected_at));
  const prices = sorted.map((row) => Number(row.price_eur));
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const span = max - min || 1;
  const width = 640;
  const height = 150;
  const padding = 14;
  const points = prices.map((price, index) =>
    `${(padding + (index / (prices.length - 1)) * (width - padding * 2)).toFixed(1)},${(height - padding - ((price - min) / span) * (height - padding * 2)).toFixed(1)}`,
  ).join(" ");
  return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Cenu vēstures grafiks"><polyline points="${points}" fill="none" stroke="currentColor" stroke-width="3"></polyline>${points.split(" ").map((point) => { const [x, y] = point.split(","); return `<circle cx="${x}" cy="${y}" r="4" fill="currentColor"></circle>`; }).join("")}</svg>`;
}

export function detailImageHtml(url, name) {
  return url
    ? `<div class="detail-image"><img src="${esc(url)}" alt="${esc(name)}"></div>`
    : '<div class="detail-image"><div class="detail-placeholder"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="3"></rect><circle cx="9" cy="10" r="2"></circle><path d="m5 17 4-4 3 3 3-3 4 4"></path></svg><span>Attēls nav pieejams</span></div></div>';
}

export function detailHistoryHtml(rows, unavailableCopy = "", { euro = EURO, fmtDate = (value) => value } = {}) {
  const observations = rows || [];
  if (!observations.length) {
    return `<section class="detail-section detail-history"><h3 class="detail-section-title">Cenu vēsture</h3><p class="detail-section-copy">Iepriekšējo cenu novērojumi palīdz novērtēt, vai pašreizējā cena tiešām ir izdevīga.</p><div class="detail-empty-note">${esc(unavailableCopy || "Šim produktam vēl nav pietiekami daudz cenu novērojumu.")}</div></section>`;
  }
  return `<section class="detail-section detail-history"><h3 class="detail-section-title">Cenu vēsture · ${observations.length} novērojumi</h3><p class="detail-section-copy">Grafiks un pēdējie novērojumi ir balstīti saglabātajā canonical cenu vēsturē.</p><div class="chart">${chartSvg(observations)}</div><div class="history-table">${observations.slice(0, 16).map((row) => `<div class="history-row"><span>${esc(retailerName(row.source_chain))}</span><span class="muted">${esc(fmtDate(row.valid_from))}–${esc(fmtDate(row.valid_until))}</span><strong>${euro.format(Number(row.price_eur))}</strong></div>`).join("")}</div></section>`;
}

export function detailComparisonHtml(offers, emptyCopy = "", options = {}) {
  const rows = offers || [];
  return `<section class="detail-section detail-comparison"><h3 class="detail-section-title">Veikalu cenu salīdzinājums</h3><p class="detail-section-copy">Salīdzinājums tiek rādīts tikai apstiprinātai canonical produkta identitātei izvēlētajā datumā.</p>${rows.length ? `<div class="detail-offers">${rows.map((offer) => offerHtml(offer, options)).join("")}</div>` : `<div class="detail-empty-note">${esc(emptyCopy || "Šajā datumā nav salīdzināmu veikalu cenu.")}</div>`}</section>`;
}

export function initCatalog(app) {
  const {
    fetchJson,
    fmtDate,
    euro = EURO,
    grid,
    summary,
    search,
    sort,
    currentOnly,
    comparisonOnly,
    getAsOf,
    getSelectedRetailer,
    getItems,
    emptyState,
    bindEmptyActions,
    bindCanonicalCards,
    syncListButtons,
    updateControlRoomStatus,
    gridErrorState,
    bindGridRetry,
    scrim,
    detail,
    detailBody,
    addToList,
    notify,
  } = app;

  let cache = new Map();

  function currentUrl() {
    return canonicalUrl({
      asOf: getAsOf(),
      sort: sort.value,
      query: search.value,
      selectedRetailer: getSelectedRetailer(),
      currentOnly: currentOnly.checked,
      comparisonOnly: comparisonOnly.checked,
    });
  }

  async function load({ isCurrent = () => true } = {}) {
    try {
      const payload = await fetchJson(currentUrl());
      if (!isCurrent()) return false;
      updateControlRoomStatus(null);
      cache = new Map((payload.products || []).map((product) => [product.id, product]));
      summary.textContent = `${payload.count} canonical produkti · ${fmtDate(payload.as_of)}`;
      grid.innerHTML = (payload.products || []).length
        ? payload.products.map((product) => canonicalCard(product, { items: getItems(), euro })).join("")
        : emptyState("Šim filtram nav canonical produktu.");
      bindCanonicalCards();
      bindEmptyActions();
      syncListButtons();
      return true;
    } catch (error) {
      if (!isCurrent()) return false;
      summary.textContent = "Dati īslaicīgi nav pieejami";
      grid.innerHTML = gridErrorState(error);
      bindGridRetry();
      return false;
    }
  }

  async function openDetail(id, seed = null) {
    scrim.classList.add("open");
    detail.classList.add("open");
    document.body.classList.add("locked");
    detailBody.innerHTML = '<div class="empty"><span class="loading"></span>Ielādēju produkta detaļas…</div>';
    try {
      const [metaUrl, currentUrlValue, historyUrl] = canonicalDetailUrls(id, getAsOf());
      const [meta, current, history] = await Promise.all([
        fetchJson(metaUrl),
        fetchJson(currentUrlValue),
        fetchJson(historyUrl),
      ]);
      const rows = history.observations || [];
      const offers = current.offers || [];
      const image = seed?.primary_image_url || offers.find((offer) => offer.source_image_url)?.source_image_url || null;
      const product = { ...meta, primary_image_url: image, current_offers: offers };
      const lowest = offers.length ? Math.min(...offers.map((offer) => Number(offer.price_eur))) : null;
      detailBody.innerHTML = `<div class="detail-shell"><div class="detail-grid">${detailImageHtml(image, meta.display_name)}<div class="detail-content"><h2>${esc(meta.display_name)}</h2><div class="detail-sub">${esc(meta.brand_display || meta.brand_normalized || "Zīmols nav norādīts")} · ${esc(packageText(meta))}</div><div class="detail-price-hero"><div class="detail-price-value">${lowest == null ? "—" : euro.format(lowest)}</div><div class="detail-price-note">${offers.length ? "zemākā aktuālā cena" : "šajā datumā nav aktuālas cenas"}</div></div><div class="detail-facts"><div class="detail-fact"><span>Statuss</span><strong>Canonical produkts</strong></div><div class="detail-fact"><span>Veikali</span><strong>${offers.length}</strong></div></div><div class="detail-actions"><button class="btn primary detail-add" type="button">${getItems()[id] ? "Sarakstā ✓" : "Pievienot sarakstam"}</button></div></div></div>${detailComparisonHtml(offers, "", { euro, fmtDate })}${detailHistoryHtml(rows, "", { euro, fmtDate })}</div>`;
      detailBody.querySelector(".detail-add")?.addEventListener("click", (event) => {
        event.preventDefault();
        addToList(product);
        event.currentTarget.textContent = "Sarakstā ✓";
        notify("Produkts pievienots iepirkumu sarakstam");
      });
      return true;
    } catch (error) {
      detailBody.innerHTML = `<div class="error">Neizdevās ielādēt detaļas: ${esc(error.message)}</div>`;
      return false;
    }
  }

  return Object.freeze({
    load,
    openDetail,
    currentUrl,
    getCache: () => cache,
  });
}
