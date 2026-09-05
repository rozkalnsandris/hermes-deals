export const WEEKLY_RETAILER_KEYS = Object.freeze(["lidl", "aldi_nord", "netto", "edeka"]);
export const WEEKLY_RETAILER_STATE_VALUES = Object.freeze([
  "offers",
  "no_offers",
  "not_published_yet",
  "source_unavailable",
  "stale_data",
  "not_supported",
]);

const STATE_SET = new Set(WEEKLY_RETAILER_STATE_VALUES);
const TRUSTED_EMPTY_SET = new Set(["offers", "no_offers"]);

export function normalizeWeeklyRetailerStates(rows) {
  if (!Array.isArray(rows)) throw new Error("API neatgrieza retailer trust-state sarakstu");
  const byKey = new Map();
  for (const row of rows) {
    if (!row || typeof row !== "object" || Array.isArray(row)) {
      throw new Error("Retailer trust-state ieraksts nav objekts");
    }
    const key = String(row.retailer_key || "");
    if (!WEEKLY_RETAILER_KEYS.includes(key)) {
      throw new Error(`Nezināms weekly retailer trust-state: ${key}`);
    }
    if (byKey.has(key)) throw new Error(`Dublēts weekly retailer trust-state: ${key}`);
    const state = String(row.state || "");
    if (!STATE_SET.has(state)) {
      throw new Error(`Nezināms weekly retailer state: ${state}`);
    }
    const dealCount = row.deal_count;
    if (!Number.isInteger(dealCount) || dealCount < 0) {
      throw new Error(`Nederīgs weekly retailer deal_count: ${key}`);
    }
    const activeDates = Array.isArray(row.active_dates)
      ? row.active_dates.map((value) => String(value))
      : null;
    if (activeDates === null) {
      throw new Error(`Nederīgs weekly retailer active_dates: ${key}`);
    }
    byKey.set(key, Object.freeze({
      ...row,
      retailer_key: key,
      state,
      deal_count: dealCount,
      active_dates: Object.freeze(activeDates),
    }));
  }
  for (const key of WEEKLY_RETAILER_KEYS) {
    if (!byKey.has(key)) throw new Error(`Trūkst weekly retailer trust-state: ${key}`);
  }
  return byKey;
}

export function weeklyRetailerState(byKey, key) {
  return byKey instanceof Map ? byKey.get(key) || null : null;
}

export function weeklyRetailerIsTrustedEmpty(entry) {
  return Boolean(entry && TRUSTED_EMPTY_SET.has(entry.state));
}

export function weeklyRetailerPresentation(entry, retailerLabel = "Veikals") {
  if (!entry) {
    return {
      state: "source_unavailable",
      tone: "unavailable",
      short: "Datu statuss nav pieejams",
      title: `${retailerLabel} dati nav pieejami`,
      detail: "Nedēļas avota statuss nav saņemts; to nevar uzskatīt par apstiprinātu nulles rezultātu.",
      confirmedEmpty: false,
    };
  }
  if (String(entry.reason || "").endsWith("_parse_unavailable")) {
    return {
      state: entry.state,
      tone: "unavailable",
      short: "Avota apstrāde neizdevās",
      title: `${retailerLabel} avota apstrāde neizdevās`,
      detail: "Piedāvājumu neesamība nav apstiprināta.",
      confirmedEmpty: false,
    };
  }
  switch (entry.state) {
    case "offers":
      return {
        state: entry.state,
        tone: "ok",
        short: "Šajā dienā jaunu akciju nav",
        title: `${retailerLabel} šajā dienā jaunas akcijas nesākas`,
        detail: "Nedēļas avots ir pieejams; citās dienās akcijas var būt pieejamas.",
        confirmedEmpty: true,
      };
    case "no_offers":
      return {
        state: entry.state,
        tone: "ok",
        short: "Pārbaudīts: jaunu akciju nav",
        title: `${retailerLabel}: jaunu akciju nav`,
        detail: "Attiecīgās nedēļas avots ir pārbaudīts un tajā nav atbilstošu īpašo akciju.",
        confirmedEmpty: true,
      };
    case "not_published_yet":
      return {
        state: entry.state,
        tone: "pending",
        short: "Vēl nav publicēts",
        title: `${retailerLabel} nedēļas avots vēl nav publicēts`,
        detail: "Piedāvājumu neesamību vēl nevar apstiprināt.",
        confirmedEmpty: false,
      };
    case "stale_data":
      return {
        state: entry.state,
        tone: "stale",
        short: "Dati novecojuši",
        title: `${retailerLabel} dati ir novecojuši`,
        detail: "Pieejamā pārbaudītā kampaņa neaptver izvēlēto nedēļu.",
        confirmedEmpty: false,
      };
    case "not_supported":
      return {
        state: entry.state,
        tone: "unsupported",
        short: "Avots vēl nav atbalstīts",
        title: `${retailerLabel} īpašo akciju avots vēl nav atbalstīts`,
        detail: "Šo stāvokli nedrīkst interpretēt kā nulles piedāvājumu skaitu.",
        confirmedEmpty: false,
      };
    case "source_unavailable":
    default:
      return {
        state: "source_unavailable",
        tone: "unavailable",
        short: "Dati nav pieejami",
        title: `${retailerLabel} dati nav pieejami`,
        detail: "Avotu vai tā pārbaudi neizdevās droši nolasīt; piedāvājumu neesamība nav apstiprināta.",
        confirmedEmpty: false,
      };
  }
}

export function weeklyUnavailableRetailers(byKey, retailerKeys = WEEKLY_RETAILER_KEYS) {
  return retailerKeys
    .map((key) => [key, weeklyRetailerState(byKey, key)])
    .filter(([, entry]) => !weeklyRetailerIsTrustedEmpty(entry));
}

export function weeklyRetailerFreshness(entry) {
  if (!entry) return "";
  return [
    entry.last_verified_campaign && `Pārbaudītā kampaņa: ${entry.last_verified_campaign}`,
    entry.last_verified_valid_from && entry.last_verified_valid_until
      && `${entry.last_verified_valid_from}–${entry.last_verified_valid_until}`,
    entry.last_verified_at && `Pārbaudīts: ${entry.last_verified_at}`,
  ].filter(Boolean).join(" · ");
}
