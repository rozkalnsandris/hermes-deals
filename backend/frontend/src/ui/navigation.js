import { addDaysIso, todayLocal } from "../core/dates.js";

export const FEATURE_KEYS = ["app", "coupon", "discount", "image"];

export function viewQuery(state) {
  const params = new URLSearchParams();
  params.set("mode", state.mode === "canonical" ? "canonical" : "deals");
  params.set("date", String(state.date || ""));
  const query = String(state.query || "").trim();
  if (query) params.set("q", query);
  if (state.retailer) params.set("retailer", state.retailer);
  if (state.sort && state.sort !== "name") params.set("sort", state.sort);
  if (state.dealView === "upcoming") params.set("view", "upcoming");
  if (state.currentOnly) params.set("current", "1");
  if (state.comparisonOnly) params.set("comparison", "1");
  for (const key of FEATURE_KEYS) if (state.features?.[key]) params.set(key, "1");
  return params.toString();
}

export function parseViewQuery(search, defaults = {}) {
  const params = new URLSearchParams(search || "");
  const features = { ...(defaults.features || {}) };
  for (const key of FEATURE_KEYS) if (params.has(key)) features[key] = params.get(key) === "1";
  return {
    mode: params.has("mode") ? (params.get("mode") === "canonical" ? "canonical" : "deals") : (defaults.mode || "deals"),
    date: params.has("date") ? params.get("date") || defaults.date || "" : defaults.date || "",
    query: params.has("q") ? params.get("q") || "" : defaults.query || "",
    retailer: params.has("retailer") ? params.get("retailer") || "" : defaults.retailer || "",
    sort: params.has("sort") ? params.get("sort") || "name" : defaults.sort || "name",
    dealView: params.has("view") ? (params.get("view") === "upcoming" ? "upcoming" : "current") : (defaults.dealView || "current"),
    currentOnly: params.has("current") ? params.get("current") === "1" : Boolean(defaults.currentOnly),
    comparisonOnly: params.has("comparison") ? params.get("comparison") === "1" : Boolean(defaults.comparisonOnly),
    features,
  };
}

export function dateFromOffset(offset, today = todayLocal()) {
  return addDaysIso(today, Number(offset));
}

export function initNavigation(app) {
  const {
    getState,
    applyState,
    pathname = () => location.pathname,
    replaceState = (url) => history.replaceState(null, "", url),
    locationSearch = () => location.search,
  } = app;

  function syncUrl() {
    const query = viewQuery(getState());
    replaceState(`${pathname()}?${query}`);
    return query;
  }

  function restoreUrl() {
    const next = parseViewQuery(locationSearch(), getState());
    applyState(next);
    return next;
  }

  return Object.freeze({ syncUrl, restoreUrl });
}
