export const STORAGE_KEY = "hermesDeals.shoppingList.v1";
export const UI_PREFS_KEY = "hermesDeals.uiPreferences.v4";
export const VIEW_PREFS_KEY = "hermesDeals.viewPreferences.v5";
export const FILTER_PANEL_KEY = "hermesDeals.filterPanel.v1";
export const REVIEW_REFRESH_KEY = "hermesDealsReviewRefresh";

export const RETAILER_VALUES = ["", "aldi_nord", "edeka", "lidl", "netto"];
export const VIEW_SORT_VALUES = ["name", "price_asc", "price_desc", "newest", "discount_desc", "retailers_desc"];

export function readJson(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw === null ? fallback : JSON.parse(raw);
  } catch {
    return fallback;
  }
}

export function writeJson(key, value) {
  localStorage.setItem(key, JSON.stringify(value));
}

export function normalizeUiPrefs(raw = {}) {
  return {
    compactHome: Boolean(raw?.compactHome),
    cardDensity: raw?.cardDensity === "compact" ? "compact" : "comfortable",
  };
}

export function loadUiPrefs() {
  return normalizeUiPrefs(readJson(UI_PREFS_KEY, {}));
}

export function saveUiPrefs(value) {
  writeJson(UI_PREFS_KEY, normalizeUiPrefs(value));
}

export function normalizeViewPrefs(raw = {}) {
  return {
    mode: raw?.mode === "canonical" ? "canonical" : "deals",
    dealView: raw?.dealView === "upcoming" ? "upcoming" : "current",
    retailer: RETAILER_VALUES.includes(raw?.retailer) ? raw.retailer : "",
    sort: VIEW_SORT_VALUES.includes(raw?.sort) ? raw.sort : "name",
    currentOnly: Boolean(raw?.currentOnly),
    comparisonOnly: Boolean(raw?.comparisonOnly),
    features: {
      app: Boolean(raw?.features?.app),
      coupon: Boolean(raw?.features?.coupon),
      discount: Boolean(raw?.features?.discount),
      image: Boolean(raw?.features?.image),
    },
  };
}

export function loadViewPrefs() {
  return normalizeViewPrefs(readJson(VIEW_PREFS_KEY, {}));
}

export function saveViewPrefs(value) {
  writeJson(VIEW_PREFS_KEY, normalizeViewPrefs(value));
}

export function loadFilterPanelOpen() {
  try {
    const stored = localStorage.getItem(FILTER_PANEL_KEY);
    return stored === null || stored === "open";
  } catch {
    return true;
  }
}

export function saveFilterPanelOpen(open) {
  try {
    localStorage.setItem(FILTER_PANEL_KEY, open ? "open" : "closed");
  } catch {
    // Preference persistence is best-effort; UI state remains usable in-memory.
  }
}
