import { $, esc } from "../core/dom.js";
import { addDaysIso, fmtDate, todayLocal } from "../core/dates.js";
import { EURO, dealPrimaryPrice, retailerName } from "./deals.js";

export const DAILY_SPECIAL_PREVIEW_LIMIT = 6;
export const DAILY_SPECIAL_RETAILER_ORDER = ["netto", "lidl", "aldi_nord", "edeka"];
export const DAILY_SPECIAL_SOURCE_CONTRACT = "explicit_immutable_retailer_evidence_only";

export function isOneDaySpecialForDate(deal, iso) {
  const base = deal.valid_from === iso && deal.valid_until === iso;
  const appPrice = deal.app_price_eur != null && deal.app_valid_from === iso && deal.app_valid_until === iso;
  return base || appPrice;
}

export function specialPriceForDate(deal, iso, { euro = EURO } = {}) {
  const base = deal.valid_from === iso && deal.valid_until === iso;
  const appPrice = deal.app_price_eur != null && deal.app_valid_from === iso && deal.app_valid_until === iso;
  if (appPrice && (!base || Number(deal.app_price_eur) <= Number(deal.price_eur ?? Infinity))) {
    return [euro.format(Number(deal.app_price_eur)), deal.source_chain === "netto" ? "Netto Plus cena" : "Lietotnes cena"];
  }
  if (deal.price_eur != null) return [euro.format(Number(deal.price_eur)), "Akcijas cena"];
  const primary = dealPrimaryPrice(deal, { euro });
  return [primary[0], "Akcijas cena"];
}

export function specialSortRows(rows) {
  const groups = new Map();
  for (const deal of rows.slice().sort((a, b) =>
    (Number(b.discount_percent || 0) - Number(a.discount_percent || 0)) ||
    (Number(a.price_eur ?? Infinity) - Number(b.price_eur ?? Infinity)) ||
    String(a.product_name_raw || "").localeCompare(String(b.product_name_raw || ""), "lv"))) {
    const key = deal.source_chain || "other";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(deal);
  }
  const order = [
    ...DAILY_SPECIAL_RETAILER_ORDER,
    ...Array.from(groups.keys()).filter((key) => !DAILY_SPECIAL_RETAILER_ORDER.includes(key)).sort(),
  ];
  const result = [];
  let remaining = true;
  while (remaining) {
    remaining = false;
    for (const key of order) {
      const group = groups.get(key);
      if (group?.length) {
        result.push(group.shift());
        remaining = true;
      }
    }
  }
  return result;
}

export function explicitDailySpecialsUrl(iso) {
  return `/api/v1/deals/daily-specials?${new URLSearchParams({ as_of: iso }).toString()}`;
}

export async function fetchExplicitDailySpecials(fetchJson, iso) {
  const payload = await fetchJson(explicitDailySpecialsUrl(iso));
  if (payload.source_contract !== DAILY_SPECIAL_SOURCE_CONTRACT) {
    throw new Error("API neatgrieza pierādītu vienas dienas akciju līgumu");
  }
  return (payload.deals || []).filter((deal) =>
    deal.is_daily_special === true &&
    deal.special_valid_on === iso &&
    deal.special_confidence === "high");
}

export async function loadDailySpecialData(fetchJson, today = todayLocal()) {
  const tomorrow = addDaysIso(today, 1);
  const [todayDeals, tomorrowDeals] = await Promise.all([
    fetchExplicitDailySpecials(fetchJson, today),
    fetchExplicitDailySpecials(fetchJson, tomorrow),
  ]);
  return {
    todayIso: today,
    tomorrowIso: tomorrow,
    today: specialSortRows(todayDeals),
    tomorrow: specialSortRows(tomorrowDeals),
  };
}

export function dailySpecialCard(deal, iso, label, { euro = EURO } = {}) {
  const [price, priceKind] = specialPriceForDate(deal, iso, { euro });
  const image = deal.source_image_url
    ? `<img src="${esc(deal.source_image_url)}" alt="${esc(deal.product_name_raw)}" loading="lazy">`
    : '<div class="daily-special-placeholder">Attēls nav pieejams</div>';
  const appActive = deal.app_price_eur != null && deal.app_valid_from === iso && deal.app_valid_until === iso;
  const appBadge = appActive
    ? (deal.source_chain === "netto"
        ? '<span class="daily-special-badge">Netto Plus</span>'
        : '<span class="daily-special-badge">Lietotnē</span>')
    : "";
  return `<article class="daily-special-card" data-special-id="${esc(deal.offer_candidate_id)}" role="button" tabindex="0" aria-label="Atvērt ${esc(deal.product_name_raw)} detaļas"><div class="daily-special-media">${image}</div><div class="daily-special-copy"><div class="daily-special-meta"><span class="daily-special-store">${esc(retailerName(deal.source_chain))}</span>${appBadge}</div><div class="daily-special-name">${esc(deal.product_name_raw)}</div><div class="daily-special-bottom"><span class="daily-special-price">${price}</span><span class="daily-special-validity">${esc(label)}<br>${esc(priceKind)}</span></div></div></article>`;
}

export function initDailySpecials(app) {
  const {
    fetchJson,
    euro = EURO,
    openRawDealDetail,
  } = app;

  const section = $("dailySpecialsSection");
  const todayRoot = $("todaySpecials");
  const tomorrowRoot = $("tomorrowSpecials");
  const todayDate = $("todaySpecialDate");
  const tomorrowDate = $("tomorrowSpecialDate");
  const todayCount = $("todaySpecialCount");
  const tomorrowCount = $("tomorrowSpecialCount");

  let dealCache = new Map();
  const expanded = { today: false, tomorrow: false };
  let data = { todayIso: "", tomorrowIso: "", today: [], tomorrow: [] };

  function bindCards(root) {
    root.querySelectorAll("[data-special-id]").forEach((card) => {
      const open = () => {
        const deal = dealCache.get(card.dataset.specialId);
        if (deal) openRawDealDetail(deal);
      };
      card.addEventListener("click", open);
      card.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          open();
        }
      });
    });
    root.querySelector("[data-special-more]")?.addEventListener("click", (event) => {
      const key = event.currentTarget.dataset.specialMore;
      expanded[key] = !expanded[key];
      render();
    });
  }

  function renderDay(key, iso, rows, root, countEl, label) {
    const visible = expanded[key] ? rows : rows.slice(0, DAILY_SPECIAL_PREVIEW_LIMIT);
    const remaining = Math.max(0, rows.length - visible.length);
    countEl.textContent = String(rows.length);
    if (!rows.length) {
      root.innerHTML = `<div class="daily-special-empty">${key === "today" ? "Šodien" : "Rīt"} nav atrastu vienas dienas akciju.</div>`;
      return;
    }
    root.innerHTML = visible.map((deal) => dailySpecialCard(deal, iso, label, { euro })).join("") +
      (rows.length > DAILY_SPECIAL_PREVIEW_LIMIT
        ? `<button class="daily-special-more" type="button" data-special-more="${key}">${expanded[key] ? "Rādīt mazāk" : `Rādīt vēl ${remaining}`}</button>`
        : "");
    bindCards(root);
  }

  function render() {
    section.hidden = false;
    todayDate.textContent = fmtDate(data.todayIso);
    tomorrowDate.textContent = fmtDate(data.tomorrowIso);
    renderDay("today", data.todayIso, data.today, todayRoot, todayCount, "Spēkā tikai šodien");
    renderDay("tomorrow", data.tomorrowIso, data.tomorrow, tomorrowRoot, tomorrowCount, "Spēkā tikai rīt");
  }

  async function load() {
    const today = todayLocal();
    data = { todayIso: today, tomorrowIso: addDaysIso(today, 1), today: [], tomorrow: [] };
    todayDate.textContent = fmtDate(data.todayIso);
    tomorrowDate.textContent = fmtDate(data.tomorrowIso);
    todayCount.textContent = "—";
    tomorrowCount.textContent = "—";
    todayRoot.innerHTML = '<div class="daily-special-empty">Ielādēju šodienas īpašos piedāvājumus…</div>';
    tomorrowRoot.innerHTML = '<div class="daily-special-empty">Ielādēju rītdienas īpašos piedāvājumus…</div>';
    try {
      data = await loadDailySpecialData(fetchJson, today);
      dealCache = new Map([...data.today, ...data.tomorrow].map((deal) => [deal.offer_candidate_id, deal]));
      render();
      return true;
    } catch {
      todayCount.textContent = "!";
      tomorrowCount.textContent = "!";
      todayRoot.innerHTML = '<div class="daily-special-error">Šodienas īpašās akcijas neizdevās ielādēt.</div>';
      tomorrowRoot.innerHTML = '<div class="daily-special-error">Rītdienas īpašās akcijas neizdevās ielādēt.</div>';
      return false;
    }
  }

  return Object.freeze({
    load,
    render,
    getData: () => data,
    getDealCache: () => dealCache,
  });
}
