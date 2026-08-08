import * as api from "./core/api.js";
import * as dates from "./core/dates.js";
import * as dom from "./core/dom.js";
import * as storage from "./core/storage.js";
import * as weeklyPayloadBridge from "./core/weekly-payload-bridge.js";
import * as deals from "./features/deals.js";
import * as dailySpecials from "./features/daily-specials.js";
import * as catalog from "./features/catalog.js";
import * as details from "./features/details.js";
import * as shoppingList from "./features/shopping-list.js";
import * as navigation from "./ui/navigation.js";
import * as overlays from "./ui/overlays.js";
import * as reviewRefresh from "./ui/review-refresh.js";
import * as filters from "./ui/filters.js";
import * as status from "./ui/status.js";
import { initWeeklyOverview } from "./features/weekly.js";
import { BOOTSTRAP_CONTRACT, bootstrapUi } from "./bootstrap.js";

// Kept through W3 because ui_bundle.py and immutable-release checks still pin
// this reviewed application identity marker. W5 owns marker archaeology cleanup.
export const PRODUCTION_BUNDLE_IDENTITY = "HERMES_UI_SCRIPT_OPEN:";
export const core = Object.freeze({ api, dates, dom, storage, weeklyPayloadBridge });
export const features = Object.freeze({ deals, dailySpecials, catalog, details, shoppingList });
export const ui = Object.freeze({ navigation, overlays, reviewRefresh, filters, status });
export { BOOTSTRAP_CONTRACT, bootstrapUi, initWeeklyOverview };

// The weekly compact-payload compatibility bridge must be installed before the
// weekly module performs its first fetch. Both are part of the same W3 bundle.
if (typeof window !== "undefined" && typeof document !== "undefined") {
  weeklyPayloadBridge.installWeeklyPayloadBridge(window);
  bootstrapUi();
}
