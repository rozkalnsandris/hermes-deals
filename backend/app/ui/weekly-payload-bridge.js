(() => {
  "use strict";

  if (window.__hermesWeeklyPayloadBridgeInstalled) return;
  window.__hermesWeeklyPayloadBridgeInstalled = true;

  const LEGACY_PATH = "/api/v1/deals/weekly-specials";
  const UI_PATH = "/api/v1/deals/weekly-specials/ui";
  const UI_CONTRACT = "normalized_unique_deals_by_id_v1";
  const SOURCE_CONTRACT =
    "single_week_query_short_periods_plus_explicit_immutable_daily_evidence";
  const originalFetch = window.fetch.bind(window);

  function normalizedUrl(input) {
    if (typeof input !== "string") return null;
    let url;
    try {
      url = new URL(input, window.location.origin);
    } catch {
      return null;
    }
    if (url.origin !== window.location.origin || url.pathname !== LEGACY_PATH) {
      return null;
    }
    url.pathname = UI_PATH;
    return input.startsWith("http://") || input.startsWith("https://")
      ? url.href
      : `${url.pathname}${url.search}${url.hash}`;
  }

  function reconstruct(payload) {
    if (
      !payload ||
      payload.ui_contract !== UI_CONTRACT ||
      payload.source_contract !== SOURCE_CONTRACT ||
      !Array.isArray(payload.deals) ||
      !Array.isArray(payload.days)
    ) {
      throw new Error("API neatgrieza derīgu normalizētu nedēļas datu līgumu");
    }

    const dealsById = new Map();
    for (const deal of payload.deals) {
      const id = String(deal?.offer_candidate_id || "");
      if (!id || dealsById.has(id)) {
        throw new Error("Nedēļas datu līgumā ir nederīgs vai dublēts piedāvājuma ID");
      }
      dealsById.set(id, deal);
    }

    let reconstructedCount = 0;
    const days = payload.days.map((day) => {
      if (!day || !Array.isArray(day.deal_ids)) {
        throw new Error("Nedēļas datu līgumā trūkst dienas piedāvājumu ID");
      }
      const deals = day.deal_ids.map((rawId) => {
        const deal = dealsById.get(String(rawId));
        if (!deal) {
          throw new Error("Nedēļas datu līgums atsaucas uz nezināmu piedāvājumu");
        }
        return deal;
      });
      reconstructedCount += deals.length;
      return { date: day.date, deals };
    });

    if (Number(payload.count) !== reconstructedCount) {
      throw new Error("Nedēļas datu līguma piedāvājumu skaits nesakrīt");
    }

    return { ...payload, days };
  }

  window.fetch = async function hermesWeeklyPayloadFetch(input, init) {
    const target = normalizedUrl(input);
    if (!target) return originalFetch(input, init);

    const response = await originalFetch(target, init);
    if (!response.ok) return response;

    return new Proxy(response, {
      get(nativeResponse, property) {
        if (property === "json") {
          return async () => reconstruct(await nativeResponse.json());
        }
        const value = Reflect.get(nativeResponse, property, nativeResponse);
        return typeof value === "function" ? value.bind(nativeResponse) : value;
      },
    });
  };
})();
