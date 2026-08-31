/* HERMES_UI_ACCESSIBILITY_FIXES_V1 */
(() => {
  "use strict";

  const drawer = document.getElementById("listDrawer");
  const productDialog = document.getElementById("detail");
  const dealDialog = document.getElementById("dealDetail");
  const overlays = [drawer, productDialog, dealDialog].filter(Boolean);
  const returnFocus = new WeakMap();
  const wasOpen = new WeakMap();
  const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)");
  const focusableSelector = [
    "a[href]",
    "button:not([disabled])",
    "input:not([disabled])",
    "select:not([disabled])",
    "textarea:not([disabled])",
    "[tabindex]:not([tabindex='-1'])",
  ].join(",");

  function isOpen(node) {
    return node.classList.contains("open");
  }

  function focusable(node) {
    return Array.from(node.querySelectorAll(focusableSelector)).filter((item) => {
      if (!(item instanceof HTMLElement)) return false;
      if (item.closest("[inert]")) return false;
      return !item.hidden && item.getAttribute("aria-hidden") !== "true";
    });
  }

  function configureSemantics(node) {
    node.setAttribute("role", "dialog");
    node.setAttribute("aria-modal", "true");

    if (node === drawer) {
      const title = node.querySelector(".drawer-title");
      if (title) {
        title.id ||= "shoppingListDialogTitle";
        node.setAttribute("aria-labelledby", title.id);
      }
      document.getElementById("closeList")?.setAttribute("aria-label", "Aizvērt iepirkumu sarakstu");
    } else {
      const title = node.querySelector(".detail-head strong");
      if (title) {
        title.id ||= node === productDialog ? "productDialogTitle" : "dealDialogTitle";
        node.setAttribute("aria-labelledby", title.id);
      }
      const closeId = node === productDialog ? "closeDetail" : "closeDealDetail";
      document.getElementById(closeId)?.setAttribute("aria-label", "Aizvērt detaļas");
    }
  }

  function syncOverlay(node, initial = false) {
    const open = isOpen(node);
    const previous = wasOpen.get(node) ?? false;
    wasOpen.set(node, open);

    if (open) {
      node.removeAttribute("inert");
      node.setAttribute("aria-hidden", "false");
      if (!previous) {
        const active = document.activeElement;
        if (active instanceof HTMLElement && !node.contains(active)) returnFocus.set(node, active);
        requestAnimationFrame(() => {
          const target = focusable(node)[0] || node;
          if (target instanceof HTMLElement) {
            if (target === node && !node.hasAttribute("tabindex")) node.setAttribute("tabindex", "-1");
            target.focus({ preventScroll: true });
          }
        });
      }
      return;
    }

    node.setAttribute("inert", "");
    node.setAttribute("aria-hidden", "true");
    if (!initial && previous) {
      const target = returnFocus.get(node);
      returnFocus.delete(node);
      if (target instanceof HTMLElement && target.isConnected) {
        requestAnimationFrame(() => target.focus({ preventScroll: true }));
      }
    }
  }

  for (const node of overlays) {
    configureSemantics(node);
    syncOverlay(node, true);
    new MutationObserver(() => syncOverlay(node)).observe(node, {
      attributes: true,
      attributeFilter: ["class"],
    });
  }

  document.addEventListener(
    "keydown",
    (event) => {
      if (event.key !== "Tab") return;
      const activeOverlay = overlays.find(isOpen);
      if (!activeOverlay) return;
      const controls = focusable(activeOverlay);
      if (!controls.length) {
        event.preventDefault();
        activeOverlay.focus({ preventScroll: true });
        return;
      }
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      } else if (!activeOverlay.contains(document.activeElement)) {
        event.preventDefault();
        first.focus();
      }
    },
    true,
  );

  /* Existing handlers use explicit smooth scrolling. Respect reduced-motion without changing their data/navigation semantics. */
  if (reducedMotion) {
    const nativeScrollIntoView = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = function scrollIntoViewRespectingMotion(options) {
      if (reducedMotion.matches && options && typeof options === "object" && options.behavior === "smooth") {
        return nativeScrollIntoView.call(this, { ...options, behavior: "auto" });
      }
      return nativeScrollIntoView.call(this, options);
    };

    const nativeScrollTo = window.scrollTo.bind(window);
    window.scrollTo = (first, second) => {
      if (reducedMotion.matches && first && typeof first === "object" && first.behavior === "smooth") {
        return nativeScrollTo({ ...first, behavior: "auto" });
      }
      return nativeScrollTo(first, second);
    };
  }
})();
