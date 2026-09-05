import { $, esc } from "../core/dom.js";
import { addDaysIso, todayLocal } from "../core/dates.js";
import {
  normalizeWeeklyRetailerStates,
  weeklyRetailerFreshness,
  weeklyRetailerPresentation,
  weeklyUnavailableRetailers,
} from "./weekly-trust-state.js";

const WEEKLY_RETAILER_ORDER = ["lidl", "aldi_nord", "netto", "edeka"];
const WEEKLY_DAY_NAMES = ["Svētdiena", "Pirmdiena", "Otrdiena", "Trešdiena", "Ceturtdiena", "Piektdiena", "Sestdiena"];
const WEEKLY_DAY_LOCATIVE = ["svētdien", "pirmdien", "otrdien", "trešdien", "ceturtdien", "piektdien", "sestdien"];
const WEEKLY_PREVIEW_LIMIT = 3;
const WEEKLY_CACHE_LIMIT = 4;
const WEEKLY_SPECIAL_MAX_DAYS = 3;

export function initWeeklyOverview(app) {
  const {
    fetchJson,
    euro,
    retailerName,
    dealPrimaryPrice,
    openRawDealDetail,
    getSelectedRetailer,
    setSelectedRetailer,
    getAsOf,
    setAsOfIso,
    syncUrl,
    loadGrid,
    saveViewPrefs,
    retailers,
  } = app;

  const weeklyState = {
    weekStart: "",
    selectedDate: "",
    cache: new Map(),
    rowsByDate: new Map(),
    retailerStates: new Map(),
    dealById: new Map(),
    failedDates: new Set(),
    loadingDates: new Set(),
    requestToken: 0,
  };

  const weeklyDays = $("weeklyDays");
  const weeklyRange = $("weeklyRange");
  const weeklyHeaderRange = $("weeklyHeaderRange");
  const weeklyDateInput = $("weeklyDateInput");
  const weeklyRetailer = $("weeklyRetailer");
  const weeklyStoreGroups = $("weeklyStoreGroups");
  const weeklyContinuing = $("weeklyContinuing");
  const weeklyContinuingList = $("weeklyContinuingList");
  const retailerSelect = $("retailerSelect");

  function weeklyIsoFromDate(date) {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  }

  function weeklyDateFromIso(iso) {
    const [year, month, day] = String(iso).split("-").map(Number);
    return new Date(year, month - 1, day, 12, 0, 0, 0);
  }

  function weeklyBerlinToday() {
    return todayLocal();
  }

  function weeklyMonday(iso) {
    const date = weeklyDateFromIso(iso);
    const day = date.getDay() || 7;
    date.setDate(date.getDate() - (day - 1));
    return weeklyIsoFromDate(date);
  }

  function weeklyDates(start) {
    return Array.from({ length: 7 }, (_, index) => addDaysIso(start, index));
  }

  function weeklyShortDate(iso) {
    const date = weeklyDateFromIso(iso);
    return `${String(date.getDate()).padStart(2, "0")}.${String(date.getMonth() + 1).padStart(2, "0")}.${date.getFullYear()}`;
  }

  function weeklyLongDate(iso) {
    const date = weeklyDateFromIso(iso);
    return `${WEEKLY_DAY_LOCATIVE[date.getDay()]}, ${weeklyShortDate(iso)}`;
  }

  function weeklyWeekday(iso) {
    return WEEKLY_DAY_NAMES[weeklyDateFromIso(iso).getDay()];
  }

  function weeklyCap(value) {
    return value ? value.charAt(0).toUpperCase() + value.slice(1) : value;
  }

  function weeklyRangeText(start) {
    const dates = weeklyDates(start);
    return `${weeklyShortDate(dates[0])}–${weeklyShortDate(dates[6])}`;
  }

  function weeklySpanDays(start, end) {
    if (!start || !end || end < start) return null;
    const [sy, sm, sd] = start.split("-").map(Number);
    const [ey, em, ed] = end.split("-").map(Number);
    return Math.floor((Date.UTC(ey, em - 1, ed) - Date.UTC(sy, sm - 1, sd)) / 86400000) + 1;
  }

  function weeklyWindowPriority(kind) {
    return kind === "explicit" ? 0 : kind === "app" ? 1 : 2;
  }

  function weeklySpecialWindows(deal) {
    const windows = [];
    const add = (start, end, kind) => {
      const span = weeklySpanDays(start, end);
      if (span && span <= WEEKLY_SPECIAL_MAX_DAYS) windows.push({ start, end, kind, span });
    };
    if (deal.is_daily_special === true && deal.special_valid_on && deal.special_confidence === "high") {
      add(deal.special_valid_on, deal.special_valid_on, "explicit");
    }
    if (deal.source_chain !== "netto") {
      add(deal.valid_from, deal.valid_until, "base");
      add(deal.app_valid_from, deal.app_valid_until, "app");
    }
    const byRange = new Map();
    for (const window of windows) {
      const key = `${window.start}:${window.end}`;
      const current = byRange.get(key);
      if (!current || weeklyWindowPriority(window.kind) < weeklyWindowPriority(current.kind)) {
        byRange.set(key, window);
      }
    }
    return Array.from(byRange.values()).sort(
      (a, b) => a.start.localeCompare(b.start) || a.end.localeCompare(b.end) || weeklyWindowPriority(a.kind) - weeklyWindowPriority(b.kind),
    );
  }

  function weeklyWindowForStart(deal, iso) {
    return weeklySpecialWindows(deal).find((window) => window.start === iso) || null;
  }

  function weeklyWindowForActive(deal, iso) {
    return weeklySpecialWindows(deal).find((window) => window.start <= iso && iso <= window.end) || null;
  }

  function weeklyStartDate(deal, iso = "") {
    const window = iso ? weeklyWindowForStart(deal, iso) : weeklySpecialWindows(deal)[0];
    return window?.start || null;
  }

  function weeklyEndDate(deal, iso = "") {
    const window = iso
      ? weeklyWindowForStart(deal, iso) || weeklyWindowForActive(deal, iso)
      : weeklySpecialWindows(deal)[0];
    return window?.end || null;
  }

  function weeklyIsSingleDay(deal, iso = "") {
    const window = iso
      ? weeklyWindowForStart(deal, iso) || weeklyWindowForActive(deal, iso)
      : weeklySpecialWindows(deal)[0];
    return Boolean(window && window.start === window.end);
  }

  function weeklyUnique(rows) {
    const seen = new Set();
    return rows.filter((deal) => {
      const key = String(deal.offer_candidate_id || `${deal.source_chain}:${deal.source_store_external_id || ""}:${deal.source_offer_id || ""}`);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }

  function weeklyFilter(rows) {
    const selectedRetailer = getSelectedRetailer();
    return weeklyUnique((rows || []).filter((deal) => !selectedRetailer || deal.source_chain === selectedRetailer));
  }

  function weeklyStartsFor(iso) {
    return weeklyFilter((weeklyState.rowsByDate.get(iso) || []).filter((deal) => weeklyWindowForStart(deal, iso)));
  }

  function weeklyContinuingFor(iso) {
    return weeklyFilter((weeklyState.rowsByDate.get(iso) || []).filter((deal) => {
      const window = weeklyWindowForActive(deal, iso);
      return window && window.start < iso;
    }));
  }

  function weeklySort(rows) {
    return rows.slice().sort(
      (a, b) =>
        (Number(b.discount_percent || 0) - Number(a.discount_percent || 0)) ||
        (Number(a.price_eur ?? Infinity) - Number(b.price_eur ?? Infinity)) ||
        String(a.product_name_raw || "").localeCompare(String(b.product_name_raw || ""), "lv"),
    );
  }

  function weeklyPrice(deal, iso) {
    const appActive = deal.app_price_eur != null && deal.app_valid_from && deal.app_valid_until && deal.app_valid_from <= iso && iso <= deal.app_valid_until;
    if (appActive && Number(deal.app_price_eur) <= Number(deal.price_eur ?? Infinity)) {
      return euro.format(Number(deal.app_price_eur));
    }
    return dealPrimaryPrice(deal)[0];
  }

  function weeklyValidity(deal, iso) {
    const start = weeklyStartDate(deal, iso);
    const end = weeklyEndDate(deal, iso);
    if (!start) return "Datums nav zināms";
    if (start === end) return weeklyShortDate(start);
    return `${weeklyShortDate(start)}–${weeklyShortDate(end || start)}`;
  }

  function weeklyBundleUrl(start) {
    const params = new URLSearchParams({ week_start: start });
    return `/api/v1/deals/weekly-specials?${params.toString()}`;
  }

  async function weeklyFetchWeek(start) {
    const payload = await fetchJson(weeklyBundleUrl(start));
    if (payload.week_start !== start || !Array.isArray(payload.days)) {
      throw new Error("API neatgrieza derīgu nedēļas datu līgumu");
    }
    const dates = weeklyDates(start);
    if (payload.days.length !== dates.length || new Set(payload.days.map((day) => day?.date)).size !== dates.length
      || payload.days.some((day) => !day || !dates.includes(day.date) || !Array.isArray(day.deals))) {
      throw new Error("Nedēļas datos trūkst derīgas dienas; nulles rezultātu nevar apstiprināt");
    }
    const rowsByDate = new Map((payload.days || []).map((day) => [day.date, weeklyUnique(day.deals || [])]));
    let retailerStates;
    try {
      retailerStates = normalizeWeeklyRetailerStates(payload.retailers);
    } catch {
      // Keep visible offers, but missing/invalid metadata cannot confirm an empty day.
      retailerStates = new Map();
    }
    return { rowsByDate, retailerStates };
  }

  function weeklyRememberCache(start, bundle) {
    weeklyState.cache.set(start, bundle);
    while (weeklyState.cache.size > WEEKLY_CACHE_LIMIT) {
      weeklyState.cache.delete(weeklyState.cache.keys().next().value);
    }
  }

  function weeklyRenderLoading(start) {
    weeklyRange.textContent = weeklyRangeText(start);
    weeklyHeaderRange.textContent = weeklyRangeText(start);
    weeklyDateInput.value = weeklyState.selectedDate;
    weeklyDays.innerHTML = weeklyDates(start).map((iso) =>
      `<button class="weekly-day${iso === weeklyState.selectedDate ? " selected" : ""}" type="button" disabled><span class="weekly-day-name">${esc(weeklyCap(weeklyWeekday(iso)))}</span><span class="weekly-day-date">${esc(weeklyShortDate(iso))}</span><span class="weekly-no-deals">Ielādēju…</span></button>`,
    ).join("");
    weeklyStoreGroups.innerHTML = '<div class="weekly-loading">Ielādēju nedēļas piedāvājumus…</div>';
  }

  async function loadWeeklyOverview(targetIso = getAsOf() || weeklyBerlinToday(), force = false) {
    const start = weeklyMonday(targetIso);
    const token = ++weeklyState.requestToken;
    const dates = weeklyDates(start);
    weeklyState.weekStart = start;
    weeklyState.selectedDate = targetIso;
    weeklyRetailer.value = getSelectedRetailer();
    if (!force && weeklyState.cache.has(start)) {
      Object.assign(weeklyState, weeklyState.cache.get(start));
      weeklyState.failedDates = new Set();
      weeklyState.loadingDates = new Set();
      renderWeeklyOverview();
      return;
    }
    weeklyState.rowsByDate = new Map();
    weeklyState.retailerStates = new Map();
    weeklyState.failedDates = new Set();
    weeklyState.loadingDates = new Set(dates);
    weeklyRenderLoading(start);
    try {
      const bundle = await weeklyFetchWeek(start);
      if (token !== weeklyState.requestToken) return;
      Object.assign(weeklyState, bundle);
      weeklyState.loadingDates = new Set();
      weeklyRememberCache(start, bundle);
      renderWeeklyOverview();
    } catch {
      if (token !== weeklyState.requestToken) return;
      weeklyState.rowsByDate = new Map(dates.map((iso) => [iso, []]));
      weeklyState.failedDates = new Set(dates);
      weeklyState.loadingDates = new Set();
      renderWeeklyOverview();
    }
  }

  function weeklyShownRetailers() {
    return getSelectedRetailer() ? [getSelectedRetailer()] : WEEKLY_RETAILER_ORDER;
  }

  function weeklyTrust(retailer) {
    return weeklyRetailerPresentation(weeklyState.retailerStates.get(retailer), retailerName(retailer));
  }

  function weeklyDayChip(retailer, count) {
    const trust = weeklyTrust(retailer);
    return `<span class="weekly-store-chip weekly-trust-chip" data-retailer-color="${esc(retailer)}" data-weekly-state="${esc(trust.state)}">${esc(retailerName(retailer))}: ${count || esc(trust.short)}</span>`;
  }

  function renderWeeklyDays() {
    const today = weeklyBerlinToday();
    weeklyRange.textContent = weeklyRangeText(weeklyState.weekStart);
    weeklyHeaderRange.textContent = weeklyRangeText(weeklyState.weekStart);
    weeklyDateInput.value = weeklyState.selectedDate;
    weeklyDays.innerHTML = weeklyDates(weeklyState.weekStart).map((iso) => {
      const rows = weeklyStartsFor(iso);
      const counts = {};
      for (const deal of rows) counts[deal.source_chain] = (counts[deal.source_chain] || 0) + 1;
      const chips = weeklyShownRetailers().map((key) => weeklyDayChip(key, counts[key] || 0)).join("");
      const pending = weeklyState.loadingDates.has(iso);
      const dayBody = pending
        ? '<span class="weekly-no-deals">Ielādēju…</span>'
        : weeklyState.failedDates.has(iso)
          ? '<span class="weekly-no-deals">Neizdevās ielādēt</span>'
          : chips;
      return `<button class="weekly-day${iso === weeklyState.selectedDate ? " selected" : ""}${iso === today ? " today" : ""}" data-weekly-date="${iso}" type="button" aria-pressed="${iso === weeklyState.selectedDate}" ${pending ? "disabled" : ""}><span class="weekly-day-name">${esc(weeklyCap(weeklyWeekday(iso)))}</span><span class="weekly-day-date">${esc(weeklyShortDate(iso))}</span><span class="weekly-day-chips">${dayBody}</span></button>`;
    }).join("");
    weeklyDays.querySelectorAll("[data-weekly-date]").forEach((button) =>
      button.addEventListener("click", () => selectWeeklyDate(button.dataset.weeklyDate)),
    );
  }

  function weeklyProductHtml(deal, iso) {
    weeklyState.dealById.set(String(deal.offer_candidate_id), deal);
    const image = deal.source_image_url
      ? `<img src="${esc(deal.source_image_url)}" alt="${esc(deal.product_name_raw)}" loading="lazy">`
      : '<span class="weekly-product-placeholder">Nav attēla</span>';
    const brand = deal.brand_raw || retailerName(deal.source_chain);
    const single = weeklyIsSingleDay(deal, iso);
    const startTag = iso === weeklyBerlinToday() ? "Sākas šodien" : "Sākas šajā dienā";
    const appActive = deal.app_price_eur != null && deal.app_valid_from && deal.app_valid_until && deal.app_valid_from <= iso && iso <= deal.app_valid_until;
    const appTag = appActive
      ? `<span class="weekly-product-tag single">${deal.source_chain === "netto" ? "Netto Plus" : "Lietotne"}</span>`
      : "";
    const depositTag = deal.deposit_eur != null
      ? `<span class="weekly-product-tag">Pfand ${euro.format(Number(deal.deposit_eur))}</span>`
      : "";
    return `<button class="weekly-product" data-weekly-deal-id="${esc(deal.offer_candidate_id)}" type="button"><span class="weekly-product-media">${image}</span><span class="weekly-product-copy"><span class="weekly-product-brand">${esc(brand)}</span><span class="weekly-product-name">${esc(deal.product_name_raw)}${deal.package_text_raw ? ` · ${esc(deal.package_text_raw)}` : ""}</span><span class="weekly-product-tags"><span class="weekly-product-tag ${single ? "single" : "start"}">${single ? "Tikai šo dienu" : startTag}</span><span class="weekly-product-tag">${esc(weeklyValidity(deal, iso))}</span>${appTag}${depositTag}</span></span><span class="weekly-product-price">${weeklyPrice(deal, iso)}</span></button>`;
  }

  function weeklyStoreCard(retailer, rows, iso) {
    const sorted = weeklySort(rows);
    const preview = sorted.slice(0, WEEKLY_PREVIEW_LIMIT);
    const freshness = weeklyRetailerFreshness(weeklyState.retailerStates.get(retailer));
    const content = preview.length
      ? `<div class="weekly-products">${preview.map((deal) => weeklyProductHtml(deal, iso)).join("")}</div>`
      : `<div class="weekly-store-empty">Šajā dienā nav jaunu ${esc(retailerName(retailer))} akciju.</div>`;
    return `<article class="weekly-store-card"><div class="weekly-store-head"><span><i class="weekly-store-dot ${esc(retailer)}"></i>${esc(retailerName(retailer))}</span><span class="weekly-store-count">${rows.length}</span></div>${freshness ? `<small class="weekly-trust-freshness">${esc(freshness)}</small>` : ""}${content}<button class="weekly-store-footer" data-weekly-open-retailer="${esc(retailer)}" type="button" ${rows.length ? "" : "disabled"}>${rows.length ? `Skatīt visus ${rows.length} piedāvājumus →` : "Nav jaunu piedāvājumu"}</button></article>`;
  }

  function weeklyInactiveRetailersHtml(retailerKeys) {
    if (!retailerKeys.length) return "";
    return `<div class="weekly-inactive-retailers" role="note"><div class="weekly-inactive-retailers-copy">Veikalu datu statuss</div><div class="weekly-inactive-retailers-list">${retailerKeys.map((retailer) => {
      const trust = weeklyTrust(retailer);
      const freshness = weeklyRetailerFreshness(weeklyState.retailerStates.get(retailer));
      return `<span class="weekly-inactive-chip weekly-trust-chip" data-weekly-state="${esc(trust.state)}"><i class="weekly-store-dot ${esc(retailer)}"></i><span>${esc(retailerName(retailer))}: ${esc(trust.short)}${freshness ? `<small class="weekly-trust-freshness">${esc(freshness)}</small>` : ""}</span></span>`;
    }).join("")}</div></div>`;
  }

  function bindWeeklyProducts() {
    document.querySelectorAll("[data-weekly-deal-id]").forEach((button) =>
      button.addEventListener("click", () => {
        const deal = weeklyState.dealById.get(String(button.dataset.weeklyDealId));
        if (deal) openRawDealDetail(deal);
      }),
    );
    document.querySelectorAll("[data-weekly-open-retailer]").forEach((button) =>
      button.addEventListener("click", () => openWeeklyRetailer(button.dataset.weeklyOpenRetailer)),
    );
  }

  function weeklyNextActiveDate(iso) {
    return weeklyDates(weeklyState.weekStart).find((candidate) => candidate > iso && weeklyStartsFor(candidate).length);
  }

  function weeklyEmptyDayHtml(iso) {
    const unavailable = weeklyUnavailableRetailers(weeklyState.retailerStates, weeklyShownRetailers());
    if (unavailable.length) {
      return `<div class="weekly-empty-day"><div class="weekly-empty-day-copy"><div class="weekly-empty-day-title">Piedāvājumu dati nav pilnīgi</div><div class="weekly-empty-day-text">Piedāvājumu neesamību visiem izvēlētajiem veikaliem vēl nevar apstiprināt.</div></div></div>${weeklyInactiveRetailersHtml(weeklyShownRetailers())}`;
    }
    const nextIso = weeklyNextActiveDate(iso);
    const selectedRetailer = getSelectedRetailer();
    const subject = selectedRetailer ? `${retailerName(selectedRetailer)} īstermiņa akcijas` : "Īstermiņa akcijas";
    const nextCopy = nextIso ? `Nākamās sākas ${weeklyLongDate(nextIso)}.` : "Šajā nedēļā vēlāk jaunu akciju sākumu nav.";
    const action = nextIso
      ? `<button class="weekly-empty-day-action" data-weekly-empty-next="${esc(nextIso)}" type="button">Skatīt ${esc(weeklyShortDate(nextIso))} piedāvājumus →</button>`
      : "";
    return `<div class="weekly-empty-day"><div class="weekly-empty-day-icon" aria-hidden="true">✓</div><div class="weekly-empty-day-copy"><div class="weekly-empty-day-title">${esc(subject)} šajā dienā nesākas</div><div class="weekly-empty-day-text">${esc(nextCopy)}</div></div>${action}</div>${weeklyInactiveRetailersHtml(weeklyShownRetailers())}`;
  }

  function renderWeeklyDetail() {
    const iso = weeklyState.selectedDate;
    if (weeklyState.loadingDates.has(iso)) {
      $("weeklyDetailTitle").textContent = `Ielādēju ${weeklyLongDate(iso)} piedāvājumus…`;
      weeklyStoreGroups.classList.remove("is-empty");
      weeklyStoreGroups.innerHTML = '<div class="weekly-loading">Ielādēju izvēlētās dienas piedāvājumus…</div>';
      weeklyContinuing.hidden = true;
      return;
    }
    if (weeklyState.failedDates.has(iso)) {
      $("weeklyDetailTitle").textContent = `${weeklyLongDate(iso)} dati nav pieejami`;
      weeklyStoreGroups.classList.remove("is-empty");
      weeklyStoreGroups.innerHTML = '<div class="weekly-error">Šīs dienas piedāvājumus neizdevās ielādēt. Pārējās nedēļas dienas paliek pieejamas.</div>';
      weeklyContinuing.hidden = true;
      return;
    }

    const rows = weeklyStartsFor(iso);
    const groups = new Map();
    for (const deal of rows) {
      if (!groups.has(deal.source_chain)) groups.set(deal.source_chain, []);
      groups.get(deal.source_chain).push(deal);
    }
    $("weeklyDetailTitle").textContent = rows.length
      ? `Sākas ${weeklyLongDate(iso)}`
      : `${weeklyCap(weeklyWeekday(iso))}, ${weeklyShortDate(iso)}`;
    weeklyStoreGroups.classList.toggle("is-empty", !rows.length);
    weeklyStoreGroups.classList.remove("has-compact-empty");

    if (rows.length) {
      const selectedRetailer = getSelectedRetailer();
      const retailersToShow = selectedRetailer ? [selectedRetailer] : WEEKLY_RETAILER_ORDER;
      const activeRetailers = retailersToShow.filter((retailer) => (groups.get(retailer) || []).length);
      const inactiveRetailers = retailersToShow.filter((retailer) => !activeRetailers.includes(retailer));
      const cards = activeRetailers.map((retailer) => weeklyStoreCard(retailer, groups.get(retailer) || [], iso)).join("");
      const compact = inactiveRetailers.length ? weeklyInactiveRetailersHtml(inactiveRetailers) : "";
      weeklyStoreGroups.classList.toggle("has-compact-empty", activeRetailers.length > 0 && inactiveRetailers.length > 0);
      weeklyStoreGroups.innerHTML = cards + compact;
    } else {
      weeklyStoreGroups.innerHTML = weeklyEmptyDayHtml(iso);
    }

    const continuing = weeklySort(weeklyContinuingFor(iso)).slice(0, 4);
    weeklyContinuing.hidden = !continuing.length;
    weeklyContinuingList.innerHTML = continuing.map((deal) => {
      weeklyState.dealById.set(String(deal.offer_candidate_id), deal);
      const image = deal.source_image_url
        ? `<img src="${esc(deal.source_image_url)}" alt="${esc(deal.product_name_raw)}" loading="lazy">`
        : "<span></span>";
      return `<button class="weekly-continuing-item" data-weekly-deal-id="${esc(deal.offer_candidate_id)}" type="button">${image}<span><span class="weekly-continuing-name">${esc(deal.product_name_raw)}</span><span class="weekly-continuing-meta">${esc(retailerName(deal.source_chain))} · līdz ${esc(weeklyShortDate(weeklyEndDate(deal, iso) || iso))}</span></span><span class="weekly-continuing-price">${weeklyPrice(deal, iso)}</span></button>`;
    }).join("");

    weeklyStoreGroups.querySelector("[data-weekly-empty-next]")?.addEventListener("click", (event) =>
      selectWeeklyDate(event.currentTarget.dataset.weeklyEmptyNext),
    );
    bindWeeklyProducts();
  }

  function renderWeeklySummary() {
    if (weeklyState.loadingDates.size) {
      $("weeklyBusiest").textContent = "Ielādēju…";
      $("weeklySingleDay").textContent = "—";
      $("weeklyRetailerCount").textContent = "—";
      $("weeklyNextActivity").textContent = "Ielādēju…";
      return;
    }
    const dates = weeklyDates(weeklyState.weekStart);
    const counts = dates.map((iso) => [iso, weeklyStartsFor(iso).length]);
    const busiest = counts.slice().sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))[0];
    const allStarts = dates.flatMap((iso) => weeklyStartsFor(iso).map((deal) => ({ deal, iso })));
    const singleCount = weeklyUnique(allStarts.filter((entry) => weeklyIsSingleDay(entry.deal, entry.iso)).map((entry) => entry.deal)).length;
    const retailerCount = new Set(allStarts.map((entry) => entry.deal.source_chain)).size;
    const next = counts.find(([iso, count]) => iso > weeklyState.selectedDate && count > 0);
    const incomplete = weeklyState.failedDates.size > 0 || weeklyUnavailableRetailers(weeklyState.retailerStates, weeklyShownRetailers()).length > 0;
    $("weeklyBusiest").textContent = busiest && busiest[1] ? weeklyCap(weeklyWeekday(busiest[0])) : incomplete ? "Dati nepilnīgi" : "Nav jaunu akciju";
    $("weeklySingleDay").textContent = singleCount || !incomplete ? String(singleCount) : "—";
    $("weeklyRetailerCount").textContent = retailerCount || !incomplete ? String(retailerCount) : "—";
    $("weeklyNextActivity").textContent = next ? weeklyCap(weeklyWeekday(next[0])) : incomplete ? "Dati nepilnīgi" : "Šonedēļ nav";
  }

  function renderWeeklyOverview() {
    weeklyState.dealById.clear();
    weeklyRetailer.value = getSelectedRetailer();
    renderWeeklyDays();
    renderWeeklyDetail();
    renderWeeklySummary();
  }

  function syncWeeklyRetailer(value) {
    setSelectedRetailer(value || "");
    weeklyRetailer.value = getSelectedRetailer();
    if (retailerSelect) retailerSelect.value = getSelectedRetailer();
    retailers.querySelectorAll(".chip").forEach((chip) =>
      chip.classList.toggle("active", (chip.dataset.retailer || "") === getSelectedRetailer()),
    );
    saveViewPrefs();
    syncUrl();
    renderWeeklyOverview();
  }

  function selectWeeklyDate(iso) {
    weeklyState.selectedDate = iso;
    setAsOfIso(iso);
    syncUrl();
    renderWeeklyOverview();
  }

  async function openWeeklyDeals(retailer = "") {
    if (retailer) syncWeeklyRetailer(retailer);
    $("grid").innerHTML = '<div class="empty"><span class="loading"></span>Ielādēju piedāvājumus…</div>';
    $("deals")?.scrollIntoView({ behavior: "smooth", block: "start" });
    await loadGrid();
  }

  function openWeeklyRetailer(retailer) {
    void openWeeklyDeals(retailer);
  }

  function moveWeekly(delta) {
    const target = addDaysIso(weeklyState.weekStart, delta * 7);
    setAsOfIso(target);
    syncUrl();
    loadWeeklyOverview(target);
  }

  function goWeeklyToday() {
    const today = weeklyBerlinToday();
    setAsOfIso(today);
    syncUrl();
    loadWeeklyOverview(today);
    $("home")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  $("weeklyPrevious").addEventListener("click", () => moveWeekly(-1));
  $("weeklyNext").addEventListener("click", () => moveWeekly(1));
  $("weeklyCurrent").addEventListener("click", goWeeklyToday);
  $("weeklyNavToday").addEventListener("click", goWeeklyToday);
  $("weeklyNavDeals").addEventListener("click", () => void openWeeklyDeals());
  $("weeklyShowAll").addEventListener("click", () => void openWeeklyDeals());
  weeklyRetailer.addEventListener("change", () => syncWeeklyRetailer(weeklyRetailer.value));
  $("weeklyDateButton").addEventListener("click", () => {
    weeklyDateInput.value = weeklyState.selectedDate;
    try {
      weeklyDateInput.showPicker();
    } catch {
      weeklyDateInput.focus();
      weeklyDateInput.click();
    }
  });
  weeklyDateInput.addEventListener("change", () => {
    if (!weeklyDateInput.value) return;
    const target = weeklyDateInput.value;
    setAsOfIso(target);
    syncUrl();
    loadWeeklyOverview(target);
  });
  retailerSelect?.addEventListener("change", () => setTimeout(() => {
    weeklyRetailer.value = getSelectedRetailer();
    renderWeeklyOverview();
  }, 0));
  retailers.addEventListener("click", (event) => {
    if (!event.target.closest(".chip")) return;
    setTimeout(() => {
      weeklyRetailer.value = getSelectedRetailer();
      renderWeeklyOverview();
    }, 0);
  });
  window.addEventListener("popstate", () => setTimeout(() => loadWeeklyOverview(getAsOf() || weeklyBerlinToday()), 0));

  loadWeeklyOverview(getAsOf() || weeklyBerlinToday());

  return Object.freeze({
    load: loadWeeklyOverview,
    render: renderWeeklyOverview,
  });
}
