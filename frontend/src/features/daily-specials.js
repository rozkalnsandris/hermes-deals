import { $, esc } from "../core/dom.js";
import { addDaysIso, fmtDate, todayLocal } from "../core/dates.js";

const PREVIEW_LIMIT = 6;
const PAGE_LIMIT = 500;
const MAX_PAGES = 20;
const RETAILER_ORDER = ["netto", "lidl", "aldi_nord", "edeka"];

export function initDailySpecials(app) {
  const {
    fetchJson,
    euro,
    retailerName,
    dealPrimaryPrice,
    openRawDealDetail,
  } = app;

  const section = $("dailySpecialsSection");
  const todayRoot = $("todaySpecials");
  const tomorrowRoot = $("tomorrowSpecials");
  const todayDate = $("todaySpecialDate");
  const tomorrowDate = $("tomorrowSpecialDate");
  const todayCount = $("todaySpecialCount");
  const tomorrowCount = $("tomorrowSpecialCount");
  const statusText = $("dailyStatusText");

  const dealCache = new Map();
  const expanded = { today: false, tomorrow: false };
  let data = { todayIso: "", tomorrowIso: "", today: [], tomorrow: [] };

  function isOneDaySpecialForDate(deal, iso) {
    const base = deal.valid_from === iso && deal.valid_until === iso;
    const appPrice = deal.app_price_eur != null && deal.app_valid_from === iso && deal.app_valid_until === iso;
    return base || appPrice;
  }

  function specialPriceForDate(deal, iso) {
    const base = deal.valid_from === iso && deal.valid_until === iso;
    const appPrice = deal.app_price_eur != null && deal.app_valid_from === iso && deal.app_valid_until === iso;
    if (appPrice && (!base || Number(deal.app_price_eur) <= Number(deal.price_eur ?? Infinity))) {
      return [
        euro.format(Number(deal.app_price_eur)),
        deal.source_chain === "netto" ? "Netto Plus cena" : "Lietotnes cena",
      ];
    }
    if (deal.price_eur != null) return [euro.format(Number(deal.price_eur)), "Akcijas cena"];
    const primary = dealPrimaryPrice(deal);
    return [primary[0], "Akcijas cena"];
  }

  function sortRows(rows) {
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
      ...RETAILER_ORDER,
      ...Array.from(groups.keys()).filter((key) => !RETAILER_ORDER.includes(key)).sort(),
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

  function cardHtml(deal, iso, label) {
    const [price, priceKind] = specialPriceForDate(deal, iso);
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
    const visible = expanded[key] ? rows : rows.slice(0, PREVIEW_LIMIT);
    const remaining = Math.max(0, rows.length - visible.length);
    countEl.textContent = String(rows.length);
    if (!rows.length) {
      root.innerHTML = `<div class="daily-special-empty">${key === "today" ? "Šodien" : "Rīt"} nav atrastu vienas dienas akciju.</div>`;
      return;
    }
    root.innerHTML = visible.map((deal) => cardHtml(deal, iso, label)).join("") +
      (rows.length > PREVIEW_LIMIT
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

  function explicitUrl(iso) {
    return `/api/v1/deals/daily-specials?${new URLSearchParams({ as_of: iso }).toString()}`;
  }

  async function fetchExplicit(iso) {
    const payload = await fetchJson(explicitUrl(iso));
    if (payload.source_contract !== "explicit_immutable_retailer_evidence_only") {
      throw new Error("API neatgrieza pierādītu vienas dienas akciju līgumu");
    }
    return (payload.deals || []).filter((deal) =>
      deal.is_daily_special === true &&
      deal.special_valid_on === iso &&
      deal.special_confidence === "high");
  }

  function legacyCurrentUrl(iso, offset = 0, limit = PAGE_LIMIT) {
    const params = new URLSearchParams({
      as_of: iso,
      view: "current",
      sort: "discount_desc",
      limit: String(limit),
      offset: String(offset),
    });
    return `/api/v1/deals/current?${params.toString()}`;
  }

  async function fetchAllLegacyCurrent(iso) {
    const all = [];
    const seen = new Set();
    let offset = 0;
    let total = null;
    let pages = 0;
    while (pages < MAX_PAGES) {
      const payload = await fetchJson(legacyCurrentUrl(iso, offset));
      const rows = payload.deals || [];
      const reportedTotal = Number(payload.available_count ?? payload.total ?? rows.length);
      if (!Number.isFinite(reportedTotal) || reportedTotal < 0) {
        throw new Error("API neatgrieza derīgu kopējo piedāvājumu skaitu");
      }
      if (total == null) total = reportedTotal;
      else if (reportedTotal !== total) throw new Error("Piedāvājumu skaits mainījās lapošanas laikā");
      for (const deal of rows) {
        const key = String(deal.offer_candidate_id || `${deal.source_chain || ""}:${deal.source_offer_id || ""}:${deal.product_name_raw || ""}:${deal.price_eur ?? ""}`);
        if (!seen.has(key)) {
          seen.add(key);
          all.push(deal);
        }
      }
      pages += 1;
      if (!rows.length || offset + rows.length >= total) break;
      offset += rows.length;
    }
    if (total != null && all.length < total && pages >= MAX_PAGES) {
      throw new Error(`Piedāvājumu lapošana pārsniedza drošības limitu (${MAX_PAGES})`);
    }
    return all;
  }

  async function legacyCurrentDealDailySpecialContract(today, tomorrow) {
    return Promise.all([fetchAllLegacyCurrent(today), fetchAllLegacyCurrent(tomorrow)]);
  }

  async function load() {
    const today = todayLocal();
    const tomorrow = addDaysIso(today, 1);
    data = { todayIso: today, tomorrowIso: tomorrow, today: [], tomorrow: [] };
    todayDate.textContent = fmtDate(today);
    tomorrowDate.textContent = fmtDate(tomorrow);
    todayCount.textContent = "—";
    tomorrowCount.textContent = "—";
    todayRoot.innerHTML = '<div class="daily-special-empty">Ielādēju šodienas īpašos piedāvājumus…</div>';
    tomorrowRoot.innerHTML = '<div class="daily-special-empty">Ielādēju rītdienas īpašos piedāvājumus…</div>';
    dealCache.clear();
    try {
      const [todayDeals, tomorrowDeals] = await Promise.all([fetchExplicit(today), fetchExplicit(tomorrow)]);
      data.today = sortRows(todayDeals);
      data.tomorrow = sortRows(tomorrowDeals);
      for (const deal of [...data.today, ...data.tomorrow]) dealCache.set(String(deal.offer_candidate_id), deal);
      if (statusText) statusText.textContent = "Pierādītas vienas dienas akcijas";
      render();
      return true;
    } catch (error) {
      if (statusText) statusText.textContent = "Vienas dienas akcijas nav pieejamas";
      todayRoot.innerHTML = '<div class="daily-special-empty">Neizdevās ielādēt šodienas vienas dienas akcijas.</div>';
      tomorrowRoot.innerHTML = '<div class="daily-special-empty">Neizdevās ielādēt rītdienas vienas dienas akcijas.</div>';
      throw error;
    }
  }

  return Object.freeze({
    load,
    render,
    isOneDaySpecialForDate,
    legacyCurrentDealDailySpecialContract,
  });
}
