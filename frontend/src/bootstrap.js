import { fetchJson } from "./core/api.js";
import { $, esc } from "./core/dom.js";
import { fmtDate, isIsoDate, parseLvDate, todayLocal } from "./core/dates.js";
import {
  loadFilterPanelOpen,
  loadUiPrefs,
  loadViewPrefs,
  saveFilterPanelOpen,
  saveUiPrefs,
  saveViewPrefs as persistViewPrefs,
} from "./core/storage.js";
import { EURO, dealListId, dealPrimaryPrice, retailerName } from "./features/deals.js";
import { initCurrentDeals } from "./features/deals.js";
import { initDailySpecials } from "./features/daily-specials.js";
import { initCatalog } from "./features/catalog.js";
import { initDealDetails } from "./features/details.js";
import { initShoppingList, listEntries } from "./features/shopping-list.js";
import { initWeeklyOverview } from "./features/weekly.js";
import {
  applyFilterControls,
  emptyState,
  normalizeSortForMode,
  renderFilterSummary as renderFilterSummaryView,
} from "./ui/filters.js";
import { initNavigation, dateFromOffset } from "./ui/navigation.js";
import { initOverlays, isTypingTarget } from "./ui/overlays.js";
import { initReviewRefresh } from "./ui/review-refresh.js";
import {
  gridErrorState,
  loadHealth as loadHealthView,
  loadOverview as loadOverviewView,
  updateControlRoomStatus as updateControlRoomStatusView,
  updateFilterCounts as updateFilterCountsView,
  updateReviewSearchHint as updateReviewSearchHintView,
} from "./ui/status.js";

export const SEARCH_DEBOUNCE_MS = 250;
export const TOAST_DURATION_MS = 2200;

const DEALS_MODE_HINT = "Raw deal nav automātiski tas pats produkts citā veikalā. Canonical salīdzināšana notiek tikai pēc apstiprinātas identity saites.";
const CANONICAL_MODE_HINT = "Šajā skatā ir tikai apstiprinātie canonical produkti. Te drīkst izmantot cenu vēsturi, groza salīdzinājumu un cross-store semantiku.";

function copyFallback(value) {
  const area = document.createElement("textarea");
  area.value = value;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  const ok = document.execCommand("copy");
  area.remove();
  return ok;
}

export function bootstrapUi() {
  const grid = $("grid");
  const summary = $("summary");
  const health = $("health");
  const asOf = $("asOf");
  const search = $("search");
  const sort = $("sort");
  const currentOnly = $("currentOnly");
  const comparisonOnly = $("comparisonOnly");
  const retailers = $("retailers");
  const scrim = $("scrim");
  const listDrawer = $("listDrawer");
  const detail = $("detail");
  const detailBody = $("detailBody");
  const dealDetail = $("dealDetail");
  const dealDetailBody = $("dealDetailBody");
  const featureFilters = $("featureFilters");
  const dealViewEl = $("dealView");
  const pagination = $("pagination");
  const asOfDisplay = $("asOfDisplay");
  const asOfPicker = $("asOfPicker");
  const asOfPickerButton = $("asOfPickerButton");
  const clearListConfirm = $("clearListConfirm");
  const toggleCompact = $("toggleCompact");
  const toggleDensity = $("toggleDensity");
  const clearSearch = $("clearSearch");
  const refreshView = $("refreshView");
  const shareView = $("shareView");
  const lastUpdated = $("lastUpdated");
  const backToTop = $("backToTop");
  const toast = $("toast");
  const toggleFilters = $("toggleFilters");
  const openListSide = $("openListSide");

  let mode = "deals";
  let dealView = "current";
  let selectedRetailer = "";
  let featureState = { app: false, coupon: false, discount: false, image: false };
  let uiPrefs = loadUiPrefs();
  let gridRequestGeneration = 0;
  let toastTimer = null;
  let searchTimer = null;
  let dealsController;
  let catalogController;
  let dailyController;
  let shoppingController;
  let detailController;
  let overlaysController;
  let navigationController;
  let weeklyController;

  function beginGridRequest() {
    const request = ++gridRequestGeneration;
    return () => request === gridRequestGeneration;
  }

  function setAsOfIso(value) {
    const iso = isIsoDate(value) ? String(value) : todayLocal();
    asOf.value = iso;
    asOfDisplay.value = fmtDate(iso);
    asOfPicker.value = iso;
  }

  function getState() {
    return {
      mode,
      date: asOf.value,
      query: search.value,
      retailer: selectedRetailer,
      sort: sort.value,
      dealView,
      currentOnly: currentOnly.checked,
      comparisonOnly: comparisonOnly.checked,
      features: { ...featureState },
    };
  }

  function applyState(next) {
    mode = next.mode === "canonical" ? "canonical" : "deals";
    dealView = next.dealView === "upcoming" ? "upcoming" : "current";
    selectedRetailer = next.retailer || "";
    featureState = { app: false, coupon: false, discount: false, image: false, ...(next.features || {}) };
    setAsOfIso(next.date || asOf.value || todayLocal());
    search.value = next.query || "";
    sort.value = next.sort || "name";
    sort.value = normalizeSortForMode(mode, sort.value);
    currentOnly.checked = Boolean(next.currentOnly);
    comparisonOnly.checked = Boolean(next.comparisonOnly);
    applyFilterControls(getState());
    updateSearchClear();
  }

  function restoreViewPrefs() {
    const prefs = loadViewPrefs();
    mode = prefs.mode;
    dealView = prefs.dealView;
    selectedRetailer = prefs.retailer;
    sort.value = normalizeSortForMode(mode, prefs.sort);
    currentOnly.checked = prefs.currentOnly;
    comparisonOnly.checked = prefs.comparisonOnly;
    featureState = { ...prefs.features };
  }

  function saveViewPrefs() {
    persistViewPrefs({
      mode,
      dealView,
      retailer: selectedRetailer,
      sort: sort.value,
      currentOnly: currentOnly.checked,
      comparisonOnly: comparisonOnly.checked,
      features: featureState,
    });
  }

  function updateSearchClear() {
    clearSearch.hidden = !search.value;
  }

  function notify(message) {
    clearTimeout(toastTimer);
    toast.textContent = message;
    toast.classList.add("show");
    toastTimer = setTimeout(() => toast.classList.remove("show"), TOAST_DURATION_MS);
  }

  function markUpdated() {
    const now = new Date();
    lastUpdated.dateTime = now.toISOString();
    lastUpdated.textContent = `Atjaunots ${now.toLocaleTimeString("lv-LV", { hour: "2-digit", minute: "2-digit" })}`;
  }

  function applyUiPrefs() {
    document.body.classList.toggle("compact-home", uiPrefs.compactHome);
    document.body.classList.toggle("compact-cards", uiPrefs.cardDensity === "compact");
    toggleCompact.setAttribute("aria-pressed", String(uiPrefs.compactHome));
    toggleCompact.textContent = uiPrefs.compactHome ? "Plašs skats" : "Kompakts skats";
    const compactCards = uiPrefs.cardDensity === "compact";
    toggleDensity.setAttribute("aria-pressed", String(compactCards));
    toggleDensity.textContent = compactCards ? "Ērtas kartītes" : "Kompaktas kartītes";
  }

  function toggleCompactMode() {
    uiPrefs.compactHome = !uiPrefs.compactHome;
    saveUiPrefs(uiPrefs);
    applyUiPrefs();
  }

  function toggleCardDensity() {
    uiPrefs.cardDensity = uiPrefs.cardDensity === "compact" ? "comfortable" : "compact";
    saveUiPrefs(uiPrefs);
    applyUiPrefs();
  }

  function applyFilterPanel(open = loadFilterPanelOpen()) {
    const expanded = Boolean(open);
    $("deals").classList.toggle("filters-collapsed", !expanded);
    toggleFilters.setAttribute("aria-expanded", String(expanded));
    toggleFilters.textContent = expanded ? "Slēpt filtrus⌄" : "Rādīt filtrus⌄";
  }

  function toggleFilterPanel() {
    const open = $("deals").classList.contains("filters-collapsed");
    saveFilterPanelOpen(open);
    applyFilterPanel(open);
  }

  function currentSortLabel() {
    return sort.options[sort.selectedIndex]?.textContent || sort.value;
  }

  function renderFilterSummary() {
    return renderFilterSummaryView(getState(), { onReset: resetFilters, sortLabel: currentSortLabel() });
  }

  function bindEmptyActions() {
    grid.querySelector('[data-empty-action="reset"]')?.addEventListener("click", resetFilters);
  }

  function bindGridRetry() {
    grid.querySelector("[data-grid-retry]")?.addEventListener("click", () => loadGrid(false));
  }

  function updateControlRoomStatus(payload) {
    updateControlRoomStatusView(payload, { mode, asOf: asOf.value, fmtDate });
  }

  function updateFilterCounts(payload) {
    updateFilterCountsView(payload, { dealView });
  }

  function updateReviewSearchHint(payload, isCurrent) {
    return updateReviewSearchHintView(fetchJson, payload, search.value, isCurrent);
  }

  function syncListButtons() {
    shoppingController?.syncButtons();
  }

  function bindRawDeals() {
    document.querySelectorAll(".raw-compare").forEach((button) =>
      button.addEventListener("click", () => catalogController?.openDetail(button.dataset.canonicalId)),
    );
    document.querySelectorAll(".card[data-deal-id]").forEach((card) => {
      const deal = dealsController?.getDealCache().get(card.dataset.dealId);
      card.querySelector(".raw-detail")?.addEventListener("click", () => {
        if (deal) detailController?.openRawDealDetail(deal);
      });
      card.querySelector(".deal-list-add")?.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        if (!deal) return;
        shoppingController.addDeal(deal);
        notify("Piedāvājums pievienots iepirkumu sarakstam");
      });
    });
  }

  function bindCanonicalCards() {
    document.querySelectorAll(".card[data-product-id]").forEach((card) => {
      const product = catalogController?.getCache().get(card.dataset.productId);
      card.querySelector(".detail-btn")?.addEventListener("click", () => {
        if (product) catalogController.openDetail(product.id, product);
      });
      card.querySelector(".list-add")?.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        if (!product) return;
        shoppingController.addCanonical(product);
        notify("Produkts pievienots iepirkumu sarakstam");
      });
    });
  }

  shoppingController = initShoppingList({
    fetchJson,
    fmtDate,
    euro: EURO,
    getAsOf: () => asOf.value,
    notify,
    getDealCache: () => dealsController?.getDealCache() || new Map(),
  });

  detailController = initDealDetails({
    fetchJson,
    fmtDate,
    euro: EURO,
    getAsOf: () => asOf.value,
    getItems: () => shoppingController.state.items,
    addDealToList: shoppingController.addDeal,
    notify,
    scrim,
    dealDetail,
    dealDetailBody,
  });

  dealsController = initCurrentDeals({
    fetchJson,
    fmtDate,
    grid,
    summary,
    pagination,
    search,
    sort,
    getAsOf: () => asOf.value,
    getDealView: () => dealView,
    getSelectedRetailer: () => selectedRetailer,
    getFeatureState: () => featureState,
    getItems: () => shoppingController.state.items,
    emptyState,
    bindRawDeals,
    bindEmptyActions,
    updateControlRoomStatus,
    updateFilterCounts,
    updateReviewSearchHint,
    gridErrorState,
    bindGridRetry,
    scrollTarget: $("deals"),
  });

  catalogController = initCatalog({
    fetchJson,
    fmtDate,
    euro: EURO,
    grid,
    summary,
    search,
    sort,
    currentOnly,
    comparisonOnly,
    getAsOf: () => asOf.value,
    getSelectedRetailer: () => selectedRetailer,
    getItems: () => shoppingController.state.items,
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
    addToList: shoppingController.addCanonical,
    notify,
  });

  dailyController = initDailySpecials({
    fetchJson,
    euro: EURO,
    openRawDealDetail: (deal) => detailController.openRawDealDetail(deal),
  });

  overlaysController = initOverlays({
    listDrawer,
    detail,
    dealDetail,
    scrim,
    clearListConfirm,
    cancelClearList: $("cancelClearList"),
    confirmClearList: $("confirmClearList"),
    renderList: shoppingController.render,
  });

  navigationController = initNavigation({
    getState,
    applyState,
  });

  async function loadOverview() {
    try {
      await loadOverviewView(fetchJson, asOf.value);
      return true;
    } catch {
      return false;
    }
  }

  async function loadGrid(resetPage = true) {
    const isCurrent = beginGridRequest();
    renderFilterSummary();
    if (mode === "deals") return dealsController.load({ resetPage, isCurrent });
    $("reviewSearchHint").hidden = true;
    $("reviewSearchHint").innerHTML = "";
    pagination.innerHTML = "";
    return catalogController.load({ isCurrent });
  }

  async function reloadAll({ markComplete = true } = {}) {
    const results = await Promise.allSettled([
      loadOverview(),
      loadGrid(),
      dailyController.load(),
    ]);
    shoppingController.render();
    const complete = results.every((result) => result.status === "fulfilled" && result.value !== false);
    if (complete && markComplete) markUpdated();
    return complete;
  }

  async function loadInitialPage() {
    const [healthOk, dataOk] = await Promise.all([
      loadHealthView(fetchJson, health),
      reloadAll({ markComplete: false }),
    ]);
    if (healthOk && dataOk) markUpdated();
    return healthOk && dataOk;
  }

  async function refreshAll() {
    if (refreshView.disabled) return;
    refreshView.disabled = true;
    refreshView.setAttribute("aria-busy", "true");
    const old = refreshView.textContent;
    refreshView.textContent = "Atjaunoju…";
    try {
      const [healthOk, dataOk] = await Promise.all([
        loadHealthView(fetchJson, health),
        reloadAll({ markComplete: false }),
      ]);
      if (healthOk && dataOk) {
        markUpdated();
        notify("Dati atjaunoti");
      } else {
        notify("Daļu datu neizdevās atjaunot");
      }
    } finally {
      refreshView.disabled = false;
      refreshView.removeAttribute("aria-busy");
      refreshView.textContent = old;
    }
  }

  async function copyCurrentView() {
    navigationController.syncUrl();
    const value = location.href;
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(value);
      else if (!copyFallback(value)) throw new Error("copy failed");
      notify("Skata saite nokopēta");
    } catch {
      notify("Saiti neizdevās nokopēt");
    }
  }

  function updateModeShell() {
    $("currentToggle").style.display = mode === "canonical" ? "flex" : "none";
    $("comparisonToggle").style.display = mode === "canonical" ? "flex" : "none";
    $("modeHint").textContent = mode === "deals" ? DEALS_MODE_HINT : CANONICAL_MODE_HINT;
    applyFilterControls(getState());
  }

  function switchMode(next) {
    mode = next === "canonical" ? "canonical" : "deals";
    sort.value = normalizeSortForMode(mode, sort.value);
    updateModeShell();
    saveViewPrefs();
    navigationController.syncUrl();
    void loadGrid();
  }

  function resetFilters() {
    search.value = "";
    selectedRetailer = "";
    sort.value = "name";
    currentOnly.checked = false;
    comparisonOnly.checked = false;
    dealView = "current";
    for (const key of Object.keys(featureState)) featureState[key] = false;
    updateSearchClear();
    applyFilterControls(getState());
    saveViewPrefs();
    navigationController.syncUrl();
    renderFilterSummary();
    void reloadAll();
  }

  function clearSearchAndReload() {
    if (!search.value) return;
    search.value = "";
    updateSearchClear();
    navigationController.syncUrl();
    void loadGrid();
    search.focus();
  }

  function commitDisplayDate() {
    const iso = parseLvDate(asOfDisplay.value);
    if (!iso) {
      asOfDisplay.setCustomValidity("Ievadi datumu formātā DD.MM.GGGG");
      asOfDisplay.reportValidity();
      return false;
    }
    asOfDisplay.setCustomValidity("");
    setAsOfIso(iso);
    navigationController.syncUrl();
    void reloadAll();
    if (listDrawer.classList.contains("open") && listEntries(shoppingController.state.items).length) {
      void shoppingController.compareBasket();
    }
    return true;
  }

  function confirmClearAll() {
    shoppingController.clearAll();
    overlaysController.closeClearListConfirm();
  }

  function bindEvents() {
    document.querySelectorAll(".modebtn").forEach((button) =>
      button.addEventListener("click", () => switchMode(button.dataset.mode)),
    );

    dealViewEl.addEventListener("click", (event) => {
      const chip = event.target.closest("[data-deal-view]");
      if (!chip) return;
      dealView = chip.dataset.dealView || "current";
      applyFilterControls(getState());
      saveViewPrefs();
      navigationController.syncUrl();
      void loadGrid();
    });

    retailers.addEventListener("click", (event) => {
      const chip = event.target.closest(".chip");
      if (!chip) return;
      selectedRetailer = chip.dataset.retailer || "";
      applyFilterControls(getState());
      saveViewPrefs();
      navigationController.syncUrl();
      void loadGrid();
    });

    $("retailerSelect")?.addEventListener("change", (event) => {
      selectedRetailer = event.target.value || "";
      applyFilterControls(getState());
      saveViewPrefs();
      navigationController.syncUrl();
      void loadGrid();
    });

    search.addEventListener("input", () => {
      updateSearchClear();
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => {
        navigationController.syncUrl();
        void loadGrid();
      }, SEARCH_DEBOUNCE_MS);
    });
    clearSearch.addEventListener("click", clearSearchAndReload);

    sort.addEventListener("change", () => {
      sort.value = normalizeSortForMode(mode, sort.value);
      saveViewPrefs();
      navigationController.syncUrl();
      void loadGrid();
    });
    currentOnly.addEventListener("change", () => {
      saveViewPrefs();
      navigationController.syncUrl();
      void loadGrid();
    });
    comparisonOnly.addEventListener("change", () => {
      saveViewPrefs();
      navigationController.syncUrl();
      void loadGrid();
    });

    refreshView.addEventListener("click", refreshAll);
    shareView.addEventListener("click", copyCurrentView);
    backToTop.addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));
    window.addEventListener("scroll", () => backToTop.classList.toggle("visible", window.scrollY > 600), { passive: true });

    asOfDisplay.addEventListener("change", commitDisplayDate);
    asOfDisplay.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        commitDisplayDate();
        asOfDisplay.blur();
      }
    });
    asOfPickerButton.addEventListener("click", () => {
      asOfPicker.value = asOf.value;
      try {
        asOfPicker.showPicker();
      } catch {
        asOfPicker.focus();
        asOfPicker.click();
      }
    });
    asOfPicker.addEventListener("change", () => {
      if (!asOfPicker.value) return;
      setAsOfIso(asOfPicker.value);
      asOfDisplay.setCustomValidity("");
      navigationController.syncUrl();
      void reloadAll();
      if (listDrawer.classList.contains("open") && listEntries(shoppingController.state.items).length) {
        void shoppingController.compareBasket();
      }
    });

    toggleCompact.addEventListener("click", toggleCompactMode);
    toggleDensity.addEventListener("click", toggleCardDensity);
    $("openList").addEventListener("click", overlaysController.openDrawer);
    openListSide.addEventListener("click", overlaysController.openDrawer);
    toggleFilters.addEventListener("click", toggleFilterPanel);

    document.querySelectorAll("[data-sidebar-mode]").forEach((button) =>
      button.addEventListener("click", () => {
        switchMode(button.dataset.sidebarMode);
        $("deals")?.scrollIntoView({ behavior: "smooth" });
      }),
    );
    document.querySelectorAll("[data-nav-target]").forEach((link) =>
      link.addEventListener("click", () => {
        document.querySelectorAll(".side-link[data-nav-target]").forEach((item) => item.classList.toggle("active", item === link));
      }),
    );

    $("closeList").addEventListener("click", overlaysController.closeOverlays);
    $("closeDetail").addEventListener("click", overlaysController.closeOverlays);
    $("closeDealDetail").addEventListener("click", overlaysController.closeOverlays);
    scrim.addEventListener("click", overlaysController.closeOverlays);
    $("compareBasket").addEventListener("click", shoppingController.compareBasket);
    $("copyList").addEventListener("click", shoppingController.copy);
    $("clearDone").addEventListener("click", shoppingController.clearCompleted);
    $("clearList").addEventListener("click", () => overlaysController.openClearListConfirm(listEntries(shoppingController.state.items).length > 0));
    $("cancelClearList").addEventListener("click", overlaysController.closeClearListConfirm);
    $("confirmClearList").addEventListener("click", confirmClearAll);
    clearListConfirm.addEventListener("click", (event) => {
      if (event.target === clearListConfirm) overlaysController.closeClearListConfirm();
    });
    clearListConfirm.addEventListener("keydown", overlaysController.trapClearListFocus);

    document.addEventListener("keydown", (event) => {
      if (event.key === "/" && !isTypingTarget(event.target) && !event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault();
        search.focus();
        search.select();
        return;
      }
      if (event.key !== "Escape") return;
      if (document.activeElement === search && search.value) {
        event.preventDefault();
        clearSearchAndReload();
        return;
      }
      if (clearListConfirm.classList.contains("open")) {
        overlaysController.closeClearListConfirm();
        return;
      }
      overlaysController.closeOverlays();
    });

    document.querySelector(".bottom-nav").addEventListener("click", (event) => {
      const button = event.target.closest("button");
      if (!button) return;
      document.querySelectorAll(".bottom-nav button").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      if (button.dataset.target) $(button.dataset.target)?.scrollIntoView({ behavior: "smooth" });
      if (button.dataset.action === "list") overlaysController.openDrawer();
      if (button.dataset.action === "canonical") {
        switchMode("canonical");
        $("deals")?.scrollIntoView({ behavior: "smooth" });
      }
    });

    $("quickDates").addEventListener("click", (event) => {
      const button = event.target.closest("button[data-offset]");
      if (!button) return;
      setAsOfIso(dateFromOffset(button.dataset.offset));
      navigationController.syncUrl();
      void reloadAll();
    });

    featureFilters.addEventListener("click", (event) => {
      const button = event.target.closest(".chip[data-feature]");
      if (!button) return;
      const key = button.dataset.feature;
      featureState[key] = !featureState[key];
      applyFilterControls(getState());
      saveViewPrefs();
      navigationController.syncUrl();
      void loadGrid();
    });

    window.addEventListener("popstate", () => {
      navigationController.restoreUrl();
      saveViewPrefs();
      renderFilterSummary();
      shoppingController.render();
      updateModeShell();
    });
  }

  setAsOfIso(todayLocal());
  restoreViewPrefs();
  navigationController.restoreUrl();
  applyUiPrefs();
  applyFilterPanel();
  renderFilterSummary();
  updateModeShell();
  shoppingController.render();
  bindEvents();

  initReviewRefresh({
    loadOverview,
    loadGrid,
  });

  weeklyController = initWeeklyOverview({
    fetchJson,
    euro: EURO,
    retailerName,
    dealPrimaryPrice,
    openRawDealDetail: (deal) => detailController.openRawDealDetail(deal),
    getSelectedRetailer: () => selectedRetailer,
    setSelectedRetailer: (value) => { selectedRetailer = value || ""; },
    getAsOf: () => asOf.value,
    setAsOfIso,
    syncUrl: navigationController.syncUrl,
    loadGrid,
    saveViewPrefs,
    retailers,
  });

  return Object.freeze({
    loadGrid,
    reloadAll,
    loadInitialPage,
    refreshAll,
    switchMode,
    getState,
    getWeeklyController: () => weeklyController,
  });
}

export const BOOTSTRAP_CONTRACT = "w3-behavior-preserving-bootstrap-v1";
