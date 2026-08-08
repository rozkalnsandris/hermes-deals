import * as api from "./core/api.js";
import * as dates from "./core/dates.js";
import * as dom from "./core/dom.js";
import * as storage from "./core/storage.js";

// W3 starts by making shared browser contracts explicit and buildable without
// changing the currently served production application. Feature extraction is
// layered onto this entrypoint in subsequent commits on the same Draft PR.
export const core = Object.freeze({ api, dates, dom, storage });
