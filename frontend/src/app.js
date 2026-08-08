import * as api from "./core/api.js";
import * as dates from "./core/dates.js";
import * as dom from "./core/dom.js";
import * as storage from "./core/storage.js";
import * as deals from "./features/deals.js";
import * as dailySpecials from "./features/daily-specials.js";
import * as catalog from "./features/catalog.js";
import * as shoppingList from "./features/shopping-list.js";
import * as navigation from "./ui/navigation.js";
import * as overlays from "./ui/overlays.js";
import * as reviewRefresh from "./ui/review-refresh.js";
import { initWeeklyOverview } from "./features/weekly.js";

// W3 makes shared browser contracts and feature boundaries explicit and
// buildable before switching the existing inline production serving path.
export const core = Object.freeze({ api, dates, dom, storage });
export const features = Object.freeze({ deals, dailySpecials, catalog, shoppingList });
export const ui = Object.freeze({ navigation, overlays, reviewRefresh });
export { initWeeklyOverview };
