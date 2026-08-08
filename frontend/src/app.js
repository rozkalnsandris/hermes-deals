import * as api from "./core/api.js";
import * as dates from "./core/dates.js";
import * as dom from "./core/dom.js";
import * as storage from "./core/storage.js";
import { initWeeklyOverview } from "./features/weekly.js";

// W3 starts by making shared browser contracts explicit and buildable without
// changing the currently served production application. The weekly overview is
// the first large feature boundary extracted from the historical monolith.
export const core = Object.freeze({ api, dates, dom, storage });
export { initWeeklyOverview };
