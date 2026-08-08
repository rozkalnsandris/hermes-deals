import { esc } from "../core/dom.js";
import {
  detailComparisonHtml,
  detailHistoryHtml,
  detailImageHtml,
} from "./catalog.js";
import {
  EURO,
  dealListId,
  dealPrimaryPrice,
  rawPackage,
  retailerName,
} from "./deals.js";

export function rawDealDetailUrls(deal, asOf) {
  const canonicalId = deal.canonical_product_id || deal.canonical_id || null;
  if (!canonicalId) return [];
  return [
    `/api/v1/canonical-products/${canonicalId}/current-offers?as_of=${encodeURIComponent(asOf)}`,
    `/api/v1/canonical-products/${canonicalId}/price-history?limit=60`,
  ];
}

export function rawDealDetailStatus(deal) {
  const canonicalId = deal.canonical_product_id || deal.canonical_id || null;
  if (canonicalId) return "Canonical identitāte apstiprināta";
  if (deal.canonical_comparable) return "Canonical salīdzināms";
  return "Tikai retailer deal";
}

export function initDealDetails(app) {
  const {
    fetchJson,
    fmtDate,
    euro = EURO,
    getAsOf,
    getItems,
    addDealToList,
    notify,
    scrim,
    dealDetail,
    dealDetailBody,
  } = app;

  async function openRawDealDetail(deal) {
    scrim.classList.add("open");
    dealDetail.classList.add("open");
    document.body.classList.add("locked");
    dealDetailBody.innerHTML = '<div class="empty"><span class="loading"></span>Ielādēju piedāvājuma detaļas…</div>';

    const primary = dealPrimaryPrice(deal, { euro });
    const inList = Boolean(getItems()[dealListId(deal)]);
    const canonicalId = deal.canonical_product_id || deal.canonical_id || null;
    let canonicalOffers = [];
    let historyRows = [];
    let historyCopy = "Cenu vēsture būs pieejama pēc tam, kad šis retailer piedāvājums būs droši sasaistīts ar canonical produktu.";

    if (canonicalId) {
      try {
        const [currentUrl, historyUrl] = rawDealDetailUrls(deal, getAsOf());
        const [current, history] = await Promise.all([
          fetchJson(currentUrl),
          fetchJson(historyUrl),
        ]);
        canonicalOffers = current.offers || [];
        historyRows = history.observations || [];
        historyCopy = "Šim canonical produktam vēl nav saglabātu cenu novērojumu.";
      } catch (error) {
        historyCopy = `Canonical cenu vēsturi neizdevās ielādēt: ${error.message}`;
      }
    }

    const regular = deal.regular_price_eur != null
      ? euro.format(Number(deal.regular_price_eur))
      : "Nav norādīta";
    const status = rawDealDetailStatus(deal);
    const sourceLink = deal.source_url
      ? `<a class="btn" href="${esc(deal.source_url)}" target="_blank" rel="noopener">Atvērt avotu</a>`
      : "";
    const comparisonEmpty = canonicalId
      ? "Šajā datumā nav citu aktuālu veikalu cenu."
      : "Salīdzinājums nav pieejams, jo retailer piedāvājumam nav apstiprinātas canonical identitātes.";

    dealDetailBody.innerHTML = `<div class="detail-shell"><div class="detail-grid">${detailImageHtml(deal.source_image_url, deal.product_name_raw)}<div class="detail-content"><h2>${esc(deal.product_name_raw)}</h2><div class="detail-sub">${esc(deal.brand_raw || retailerName(deal.source_chain))} · ${esc(rawPackage(deal))}</div><div class="detail-price-hero"><div class="detail-price-value">${primary[0]}</div><div class="detail-price-note">${esc(primary[1])}</div></div><div class="detail-facts"><div class="detail-fact"><span>Veikals</span><strong>${esc(retailerName(deal.source_chain))}</strong></div><div class="detail-fact"><span>Derīgums</span><strong>${esc(fmtDate(deal.valid_from))}–${esc(fmtDate(deal.valid_until))}</strong></div><div class="detail-fact"><span>Parastā cena</span><strong>${esc(regular)}</strong></div><div class="detail-fact"><span>Statuss</span><strong>${esc(status)}</strong></div></div><div class="detail-actions"><button class="btn primary deal-detail-add" type="button">${inList ? "Sarakstā ✓" : "Pievienot sarakstam"}</button>${sourceLink}</div></div></div>${detailComparisonHtml(canonicalOffers, comparisonEmpty, { euro, fmtDate })}${detailHistoryHtml(historyRows, historyCopy, { euro, fmtDate })}</div>`;

    dealDetailBody.querySelector(".deal-detail-add")?.addEventListener("click", (event) => {
      event.preventDefault();
      addDealToList(deal);
      event.currentTarget.textContent = "Sarakstā ✓";
      notify("Piedāvājums pievienots iepirkumu sarakstam");
    });
    return true;
  }

  return Object.freeze({ openRawDealDetail });
}
