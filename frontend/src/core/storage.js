export const STORAGE_KEY = "hermesDeals.shoppingList.v1";
export const UI_PREFS_KEY = "hermesDeals.uiPreferences.v4";
export const VIEW_PREFS_KEY = "hermesDeals.viewPreferences.v5";
export const FILTER_PANEL_KEY = "hermesDeals.filterPanel.v1";
export const REVIEW_REFRESH_KEY = "hermesDealsReviewRefresh";

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
