export function isTypingTarget(target) {
  return target instanceof HTMLInputElement ||
    target instanceof HTMLTextAreaElement ||
    target instanceof HTMLSelectElement ||
    Boolean(target?.isContentEditable);
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

  function openDrawer() {
    listDrawer.classList.add("open");
    scrim.classList.add("open");
    document.body.classList.add("locked");
    renderList();
  }

  function closeOverlays() {
    listDrawer.classList.remove("open");
    detail.classList.remove("open");
    dealDetail.classList.remove("open");
    scrim.classList.remove("open");
    document.body.classList.remove("locked");
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

  return Object.freeze({
    openDrawer,
    closeOverlays,
    openClearListConfirm,
    closeClearListConfirm,
    trapClearListFocus,
  });
}
