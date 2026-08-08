import { $, esc } from "../core/dom.js";
import { UiApiError, apiErrorReference } from "../core/api.js";
import { retailerName } from "../features/deals.js";

export function gridErrorState(error) {
  const message = error instanceof UiApiError ? error.message : "Datus neizdevās ielādēt.";
  const reference = apiErrorReference(error);
  return `<div class="error" role="alert"><div>${esc(message)}</div>${reference ? `<div class="muted">${esc(reference)}</div>` : ""}<div class="empty-actions"><button class="btn" type="button" data-grid-retry>Mēģināt vēlreiz</button></div></div>`;
}

export function setHealthState(health, state, text) {
  health.classList.toggle("ok", state === "ok");
  health.setAttribute("data-health-state", state);
  health.setAttribute("role", "status");
  health.setAttribute("aria-live", "polite");
  health.setAttribute("aria-atomic", "true");
  health.textContent = text;
}

export async function loadHealth(fetchJson, health = $("health")) {
  setHealthState(health, "loading", "API pārbaude…");
  try {
    const payload = await fetchJson("/api/health");
    setHealthState(health, "ok", `API ${payload.version} · ${payload.phase}`);
    return true;
  } catch {
    setHealthState(health, "error", "API kļūda");
    return false;
  }
}

export async function loadOverview(fetchJson, asOf) {
  const payload = await fetchJson(`/api/v1/ui/overview?as_of=${encodeURIComponent(asOf)}`);
  $("statProducts").textContent = payload.total_products;
  $("statCurrent").textContent = payload.products_with_current_offers;
  $("statOffers").textContent = payload.current_offer_count;
  $("statCompare").textContent = payload.comparison_ready_products;
  $("scopeNote").textContent = `${payload.retailer_count} canonical veikali · ${payload.timezone}`;
  return payload;
}

export function updateControlRoomStatus(payload, { mode, asOf, fmtDate }) {
  const target = $("dailyStatusText");
  if (mode === "canonical") {
    target.textContent = "Drošais salīdzināšanas skats rāda tikai apstiprinātas produktu identitātes.";
    return;
  }
  const current = Number(payload?.availability_counts?.current || payload?.available_count || 0);
  const upcoming = Number(payload?.availability_counts?.upcoming || 0);
  target.textContent = `${current} aktuāli piedāvājumi · ${upcoming} drīzumā · ${fmtDate(asOf)}`;
}

export function updateFilterCounts(payload, { dealView }) {
  const availability = payload.retailer_availability || {};
  for (const chain of ["aldi_nord", "edeka", "lidl", "netto"]) {
    const element = document.querySelector(`[data-count-for="${chain}"]`);
    if (!element) continue;
    const detail = availability[chain] || {};
    const primary = (payload.retailer_counts || {})[chain] || 0;
    if (dealView === "upcoming") {
      element.textContent = `(${primary})`;
    } else {
      const parts = [String(primary)];
      if (detail.upcoming) parts.push(`+${detail.upcoming}`);
      if (detail.unknown) parts.push(`?${detail.unknown}`);
      element.textContent = `(${parts.join(" · ")})`;
    }
  }
  for (const key of ["app", "coupon", "discount", "image"]) {
    const element = document.querySelector(`[data-feature-count="${key}"]`);
    if (element) element.textContent = `(${(payload.feature_counts || {})[key] || 0})`;
  }
  const counts = payload.availability_counts || {};
  $("availabilityNote").textContent = `Jaunākie aktīvie bukleti: aktuāli ${counts.current || 0} · + drīzumā ${counts.upcoming || 0} · ? bez derīguma datuma ${counts.unknown || 0}. “Aktuāli” joprojām nozīmē tikai piedāvājumus ar pierādītu derīguma periodu.`;
}

export async function updateReviewSearchHint(fetchJson, payload, query, isCurrent = () => true) {
  const target = $("reviewSearchHint");
  if (!isCurrent()) return;
  target.hidden = true;
  target.innerHTML = "";
  const q = String(query || "").trim();
  if (!q || (payload?.deals || []).length) return;
  try {
    const review = await fetchJson("/api/v1/review-items?source_chain=lidl&limit=500");
    if (!isCurrent()) return;
    const needle = q.toLocaleLowerCase("de-DE");
    const labels = {
      pending: "gaida pārbaudi",
      draft: "labots, vēl nav publicēts",
      needs_followup: "jāpārbauda vēl",
      approved: "publicēts",
      rejected: "noraidīts",
    };
    const matches = (review.items || []).filter((item) => {
      const effective = item.effective_payload || {};
      const name = effective.product_name || effective.product_name_raw || "";
      return String(name).toLocaleLowerCase("de-DE").includes(needle);
    });
    if (!matches.length) return;
    target.hidden = false;
    target.innerHTML = `Pārskatīšanas rinda: ${matches.slice(0, 3).map((item) => {
      const effective = item.effective_payload || {};
      const name = effective.product_name || effective.product_name_raw || "Piedāvājums";
      return `<strong>${esc(name)}</strong> — ${esc(labels[item.status] || item.status)}`;
    }).join(" · ")}. <a href="/ui/review">Atvērt pārskatīšanu</a>`;
  } catch {
    // Search hint is supplementary and must not turn an empty grid into an error.
  }
}

export function retailerLabel(chain) {
  return retailerName(chain);
}
