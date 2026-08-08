import * as api from "./core/api.js";
import * as dates from "./core/dates.js";
import * as dom from "./core/dom.js";
import * as storage from "./core/storage.js";
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

export const core = Object.freeze({ api, dates, dom, storage });
export const features = Object.freeze({ deals, dailySpecials, catalog, details, shoppingList });
export const ui = Object.freeze({ navigation, overlays, reviewRefresh, filters, status });
export { BOOTSTRAP_CONTRACT, bootstrapUi, initWeeklyOverview };

// The source entry is now a real browser bootstrap. W3 still does not change
// the production serving path until the built output is explicitly wired into
// ui_bundle.py/Docker and parity gates are green.
if (typeof window !== "undefined" && typeof document !== "undefined") {
  bootstrapUi();
}
