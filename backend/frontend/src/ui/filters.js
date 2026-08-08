import { $, esc } from "../core/dom.js";
import { retailerName } from "../features/deals.js";

export function normalizeSortForMode(mode, value) {
  if (mode === "deals" && value === "retailers_desc") return "name";
  if (mode === "canonical" && ["newest", "discount_desc"].includes(value)) return "name";
  return value || "name";
}

export function activeFilterLabels(state, sortLabel = state.sort) {
  const labels = [];
  if (String(state.query || "").trim()) labels.push(`Meklēšana: ${String(state.query).trim()}`);
  if (state.retailer) labels.push(retailerName(state.retailer));
  if (state.sort !== "name") labels.push(sortLabel || state.sort);
  if (state.mode === "deals" && state.dealView === "upcoming") labels.push("Drīzumā");
  for (const [key, label] of Object.entries({ app: "App", coupon: "Kupons", discount: "Atlaide", image: "Ar attēlu" })) {
    if (state.features?.[key]) labels.push(label);
  }
  if (state.mode === "canonical" && state.currentOnly) labels.push("Tikai aktuālie");
  if (state.mode === "canonical" && state.comparisonOnly) labels.push("Tikai salīdzināmi");
  return labels;
}

export function renderFilterSummary(state, { onReset, sortLabel = state.sort } = {}) {
  const labels = activeFilterLabels(state, sortLabel);
  const target = $("filterSummary");
  target.innerHTML = labels.length
    ? `<span class="filter-label">Aktīvie filtri</span>${labels.map((label) => `<span class="filter-token">${esc(label)}</span>`).join("")}<button class="reset-filters" id="resetFilters" type="button">Notīrīt filtrus</button>`
    : '<span class="muted">Nav papildu filtru.</span>';
  $("resetFilters")?.addEventListener("click", onReset);
  const count = $("activeFilterCount");
  if (count) count.textContent = `${labels.length} aktīvi`;
  return labels;
}

export function applyFilterControls(state) {
  document.querySelectorAll(".modebtn").forEach((button) =>
    button.classList.toggle("active", button.dataset.mode === state.mode),
  );
  $("retailers").querySelectorAll(".chip").forEach((chip) =>
    chip.classList.toggle("active", (chip.dataset.retailer || "") === state.retailer),
  );
  if ($("retailerSelect")) $("retailerSelect").value = state.retailer;
  $("featureFilters").querySelectorAll(".chip").forEach((chip) =>
    chip.classList.toggle("active", Boolean(state.features?.[chip.dataset.feature])),
  );
  $("dealView").querySelectorAll("[data-deal-view]").forEach((chip) =>
    chip.classList.toggle("active", chip.dataset.dealView === state.dealView),
  );
  document.querySelectorAll("[data-sidebar-mode]").forEach((button) =>
    button.classList.toggle("active", button.dataset.sidebarMode === state.mode),
  );
}

export function emptyState(message) {
  return `<div class="empty"><div>${esc(message)}</div><div class="empty-actions"><button class="btn" type="button" data-empty-action="reset">Notīrīt filtrus</button><a class="btn" href="/ui/review">Atvērt pārskatīšanu</a></div></div>`;
}
