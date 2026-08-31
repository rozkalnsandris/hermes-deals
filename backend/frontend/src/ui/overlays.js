const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

let overlayReturnFocus = null;

export function isTypingTarget(target) {
  return target instanceof HTMLInputElement ||
    target instanceof HTMLTextAreaElement ||
    target instanceof HTMLSelectElement ||
    Boolean(target?.isContentEditable);
}

function focusableElements(panel) {
  return Array.from(panel?.querySelectorAll?.(FOCUSABLE_SELECTOR) || [])
    .filter((element) => !element.hasAttribute?.("hidden") && element.getAttribute?.("aria-hidden") !== "true");
}

function rememberReturnFocus(invoker = null) {
  if (overlayReturnFocus instanceof HTMLElement) return;
  const candidate = invoker instanceof HTMLElement ? invoker : document.activeElement;
  if (candidate instanceof HTMLElement) overlayReturnFocus = candidate;
}

function setPanelClosed(panel) {
  if (!panel) return;
  panel.classList.remove("open");
  panel.setAttribute("aria-hidden", "true");
  panel.inert = true;
}

function setPanelOpen(panel) {
  if (!panel) return;
  panel.inert = false;
  panel.setAttribute("aria-hidden", "false");
  panel.classList.add("open");
}

export function openAccessibleOverlay({ panel, scrim, invoker = null, focusTarget = null } = {}) {
  if (!panel || !scrim) return false;
  rememberReturnFocus(invoker);
  setPanelOpen(panel);
  scrim.classList.add("open");
  scrim.setAttribute("aria-hidden", "false");
  document.body.classList.add("locked");
  const target = focusTarget || focusableElements(panel)[0] || panel;
  requestAnimationFrame(() => target?.focus?.());
  return true;
}

export function initOverlays(app) {
  const {
    listDrawer,
    detail,
    dealDetail,
    scrim,
    clearListConfirm,
    cancelClearList,
    confirmClearList,
    renderList,
  } = app;

  let clearListReturnFocus = null;

  listDrawer.setAttribute("aria-label", "Ģimenes iepirkumu saraksts");
  detail.setAttribute("role", "dialog");
  detail.setAttribute("aria-modal", "true");
  detail.setAttribute("aria-label", "Produkta detaļas");
  dealDetail.setAttribute("role", "dialog");
  dealDetail.setAttribute("aria-modal", "true");
  dealDetail.setAttribute("aria-label", "Piedāvājuma detaļas");
  detail.setAttribute("tabindex", "-1");
  dealDetail.setAttribute("tabindex", "-1");
  listDrawer.querySelector("#closeList")?.setAttribute("aria-label", "Aizvērt iepirkumu sarakstu");
  detail.querySelector("#closeDetail")?.setAttribute("aria-label", "Aizvērt produkta detaļas");
  dealDetail.querySelector("#closeDealDetail")?.setAttribute("aria-label", "Aizvērt piedāvājuma detaļas");
  scrim.setAttribute("aria-hidden", "true");
  [listDrawer, detail, dealDetail].forEach(setPanelClosed);

  function eventInvoker(value) {
    return value?.currentTarget instanceof HTMLElement ? value.currentTarget : value;
  }

  function openDrawer(eventOrInvoker = null) {
    const invoker = eventInvoker(eventOrInvoker);
    openAccessibleOverlay({
      panel: listDrawer,
      scrim,
      invoker,
      focusTarget: listDrawer.querySelector("#closeList"),
    });
    renderList();
  }

  function closeOverlays({ restoreFocus = true } = {}) {
    [listDrawer, detail, dealDetail].forEach(setPanelClosed);
    scrim.classList.remove("open");
    scrim.setAttribute("aria-hidden", "true");
    document.body.classList.remove("locked");
    if (!restoreFocus) return;
    const target = overlayReturnFocus;
    overlayReturnFocus = null;
    if (target instanceof HTMLElement) target.focus();
  }

  function openClearListConfirm(hasItems) {
    if (!hasItems) return false;
    clearListReturnFocus = document.activeElement;
    clearListConfirm.classList.add("open");
    clearListConfirm.setAttribute("aria-hidden", "false");
    requestAnimationFrame(() => cancelClearList.focus());
    return true;
  }

  function closeClearListConfirm() {
    clearListConfirm.classList.remove("open");
    clearListConfirm.setAttribute("aria-hidden", "true");
    const target = clearListReturnFocus;
    clearListReturnFocus = null;
    if (target instanceof HTMLElement) target.focus();
  }

  function trapClearListFocus(event) {
    if (event.key !== "Tab") return;
    const first = cancelClearList;
    const last = confirmClearList;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function activeOverlay() {
    return [dealDetail, detail, listDrawer].find((panel) => panel.classList.contains("open")) || null;
  }

  function trapActiveOverlayFocus(event) {
    if (event.key !== "Tab" || clearListConfirm.classList.contains("open")) return;
    const panel = activeOverlay();
    if (!panel) return;
    const focusables = focusableElements(panel);
    if (!focusables.length) {
      event.preventDefault();
      panel.focus?.();
      return;
    }
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    const current = document.activeElement;
    if (!panel.contains(current)) {
      event.preventDefault();
      (event.shiftKey ? last : first).focus();
    } else if (event.shiftKey && current === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && current === last) {
      event.preventDefault();
      first.focus();
    }
  }

  document.addEventListener("keydown", trapActiveOverlayFocus, true);

  return Object.freeze({
    openDrawer,
    closeOverlays,
    openClearListConfirm,
    closeClearListConfirm,
    trapClearListFocus,
    trapActiveOverlayFocus,
  });
}
