export const WEEKLY_LEGACY_PATH = "/api/v1/deals/weekly-specials";
export const WEEKLY_UI_PATH = "/api/v1/deals/weekly-specials/ui";
export const WEEKLY_UI_CONTRACT = "normalized_unique_deals_by_id_v1";
export const WEEKLY_SOURCE_CONTRACT = "single_week_query_short_periods_plus_explicit_immutable_daily_evidence";

export function normalizeWeeklyPayloadUrl(input, origin) {
  if (typeof input !== "string") return null;
  let url;
  try {
    url = new URL(input, origin);
  } catch {
    return null;
  }
  if (url.origin !== origin || url.pathname !== WEEKLY_LEGACY_PATH) return null;
  url.pathname = WEEKLY_UI_PATH;
  return input.startsWith("http://") || input.startsWith("https://")
    ? url.href
    : `${url.pathname}${url.search}${url.hash}`;
}

export function reconstructWeeklyPayload(payload) {
  if (
    !payload ||
    payload.ui_contract !== WEEKLY_UI_CONTRACT ||
    payload.source_contract !== WEEKLY_SOURCE_CONTRACT ||
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
      if (!deal) throw new Error("Nedēļas datu līgums atsaucas uz nezināmu piedāvājumu");
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

export function installWeeklyPayloadBridge(windowObject = window) {
  if (windowObject.__hermesWeeklyPayloadBridgeInstalled) return false;
  windowObject.__hermesWeeklyPayloadBridgeInstalled = true;

  const originalFetch = windowObject.fetch.bind(windowObject);
  windowObject.fetch = async function hermesWeeklyPayloadFetch(input, init) {
    const target = normalizeWeeklyPayloadUrl(input, windowObject.location.origin);
    if (!target) return originalFetch(input, init);

    const response = await originalFetch(target, init);
    if (!response.ok) return response;

    return new Proxy(response, {
      get(nativeResponse, property) {
        if (property === "json") {
          return async () => reconstructWeeklyPayload(await nativeResponse.json());
        }
        const value = Reflect.get(nativeResponse, property, nativeResponse);
        return typeof value === "function" ? value.bind(nativeResponse) : value;
      },
    });
  };
  return true;
}
