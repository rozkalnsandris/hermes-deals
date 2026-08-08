import { REVIEW_REFRESH_KEY } from "../core/storage.js";

export const REVIEW_REFRESH_CHANNEL = "hermes-deals-review";
export const REVIEW_REFRESH_DELAY_MS = 180;

export function initReviewRefresh(app) {
  const {
    loadOverview,
    loadGrid,
    windowObject = window,
    documentObject = document,
  } = app;

  const channel = "BroadcastChannel" in windowObject
    ? new windowObject.BroadcastChannel(REVIEW_REFRESH_CHANNEL)
    : null;
  let timer = null;

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      try {
        await Promise.all([loadOverview(), loadGrid(false)]);
      } catch {
        // Refresh is best-effort and must not disturb the current visible state.
      }
    }, REVIEW_REFRESH_DELAY_MS);
  }

  channel?.addEventListener("message", (event) => {
    if (event.data?.type === "review-published") schedule();
  });
  windowObject.addEventListener("storage", (event) => {
    if (event.key === REVIEW_REFRESH_KEY) schedule();
  });
  documentObject.addEventListener("visibilitychange", () => {
    if (!documentObject.hidden) schedule();
  });

  return Object.freeze({ schedule, channel });
}
