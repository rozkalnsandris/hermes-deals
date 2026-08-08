import * as api from "./core/api.js";
import * as dates from "./core/dates.js";
import * as dom from "./core/dom.js";
import * as storage from "./core/storage.js";
import * as deals from "./features/deals.js";
import { initDailySpecials } from "./features/daily-specials.js";
import { initWeeklyOverview } from "./features/weekly.js";

// W3 makes shared browser contracts and large feature boundaries explicit and
// buildable before switching the existing inline production serving path.
export const core = Object.freeze({ api, dates, dom, storage });
export const features = Object.freeze({ deals });
export { initDailySpecials, initWeeklyOverview };
