// Browser behavior only. Prices, history and all application state live on the server.
(() => {
  const mobile = window.matchMedia('(max-width: 760px)');
  let opener;
  let dialogReturn;
  let dialogScrollY;
  const sidebar = () => document.getElementById('sidebar');
  const dialog = () => document.querySelector('.product-dialog');
  function syncOverlayState() {
    const node = sidebar();
    const detailOpen = Boolean(dialog());
    const menuOpen = mobile.matches && document.body.classList.contains('sidebar-open') && !detailOpen;
    if (!menuOpen) document.body.classList.remove('sidebar-open');

    node.inert = detailOpen || (mobile.matches && !menuOpen);
    if (menuOpen) {
      node.setAttribute('role', 'dialog');
      node.setAttribute('aria-modal', 'true');
    } else {
      node.removeAttribute('role');
      node.removeAttribute('aria-modal');
    }

    const backgroundInert = menuOpen || detailOpen;
    document.querySelector('.skip-link').inert = backgroundInert;
    document.querySelector('.workspace').inert = backgroundInert;
    document.querySelector('.mobile-bottom').inert = backgroundInert;
    document.querySelector('.app-layout').inert = detailOpen;
    document.querySelectorAll('[data-menu-open]').forEach(button => button.setAttribute('aria-expanded', String(menuOpen)));
    return { menuOpen, detailOpen };
  }
  function menu(open, { restoreFocus = true } = {}) {
    const shouldOpen = Boolean(open && mobile.matches && !dialog());
    document.body.classList.toggle('sidebar-open', shouldOpen);
    const state = syncOverlayState();
    if (state.menuOpen) {
      opener = document.activeElement;
      sidebar().querySelector('a[href],button')?.focus();
      return;
    }
    const returnTarget = opener;
    opener = null;
    if (restoreFocus && returnTarget?.isConnected && returnTarget.getClientRects().length) returnTarget.focus();
  }

  // Show exactly one SHA-verified image; page URLs remain server-owned.
  function initializeBookletSwipe() {
    const reader = document.querySelector('.booklet-swipe');
    const canvas = reader?.querySelector('[data-booklet-swipe]');
    const image = canvas?.querySelector('[data-booklet-image]');
    const form = reader?.querySelector('[data-booklet-page-form]');
    const select = form?.querySelector('select[name="page"]');
    const prev = reader?.querySelector('[data-booklet-prev]');
    const next = reader?.querySelector('[data-booklet-next]');
    const counter = reader?.querySelector('[data-booklet-counter]');
    const toggle = reader?.querySelector('[data-booklet-fullscreen]');
    const zoom = reader?.querySelector('.booklet-zoom-toggle');
    if (!reader || !canvas || !image || !form || !select || !prev || !next || !counter || !toggle) return;
    if (reader.dataset.bookletReady) return;
    const options = [...select.options];
    if (!options.length || options.some(option => !option.dataset.bookletImageUrl)) return;
    let page = Number(select.value);
    if (!Number.isInteger(page) || page < 1 || page > options.length) return;
    let touchStart = null;
    let nativeEntered = false;
    function navigate(number, updateUrl = true) {
      if (!Number.isInteger(number) || number < 1 || number > options.length) return;
      page = number;
      select.value = String(number);
      image.src = options[number - 1].dataset.bookletImageUrl;
      image.alt = 'Netto buklets, ' + number + '. lapa no ' + options.length;
      counter.textContent = String(number);
      for (const [link, target, disabled] of [
        [prev, Math.max(1, number - 1), number === 1],
        [next, Math.min(options.length, number + 1), number === options.length],
      ]) {
        const url = new URL(link.href, location.href);
        url.searchParams.set('page', String(target));
        link.href = url.pathname + url.search;
        link.setAttribute('aria-disabled', String(disabled));
        link.tabIndex = disabled ? -1 : 0;
      }
      if (zoom) zoom.checked = false;
      if (updateUrl) {
        const url = new URL(location.href);
        url.searchParams.set('page', String(number));
        if (url.href !== location.href) history.replaceState(history.state, '', url.href);
      }
    }
    function close() {
      reader.classList.remove('booklet-viewer-open');
      document.body.classList.remove('booklet-viewer-active');
      toggle.setAttribute('aria-expanded', 'false');
      toggle.textContent = '⛶ Pilnekrāns';
      if (document.fullscreenElement === reader) document.exitFullscreen().catch(() => {});
      nativeEntered = false;
      toggle.focus({ preventScroll:true });
    }
    function open() {
      reader.classList.add('booklet-viewer-open');
      document.body.classList.add('booklet-viewer-active');
      toggle.setAttribute('aria-expanded', 'true');
      toggle.textContent = '× Aizvērt pilnekrānu';
      canvas.focus({ preventScroll:true });
      // The fixed viewport overlay works even when iOS denies native fullscreen.
      if (document.fullscreenEnabled && reader.requestFullscreen) reader.requestFullscreen().catch(() => {});
    }
    for (const [link, delta] of [[prev, -1], [next, 1]]) {
      link.addEventListener('click', event => {
        if (!reader.classList.contains('booklet-viewer-open')) return;
        event.preventDefault();
        navigate(page + delta);
      });
    }
    form.addEventListener('submit', event => {
      if (!reader.classList.contains('booklet-viewer-open')) return;
      event.preventDefault();
      navigate(Number(select.value));
    });
    toggle.hidden = false;
    toggle.addEventListener('click', () => {
      if (reader.classList.contains('booklet-viewer-open')) close();
      else open();
    });
    reader.addEventListener('fullscreenchange', () => {
      if (document.fullscreenElement === reader) nativeEntered = true;
      else if (nativeEntered) close();
    });
    canvas.addEventListener('touchstart', event => {
      if (!reader.classList.contains('booklet-viewer-open') || event.touches.length !== 1 || zoom?.checked) return;
      touchStart = { x:event.touches[0].clientX, y:event.touches[0].clientY };
    }, { passive:true });
    canvas.addEventListener('touchend', event => {
      if (!touchStart || !reader.classList.contains('booklet-viewer-open') || event.changedTouches.length !== 1) return;
      const dx = event.changedTouches[0].clientX - touchStart.x;
      const dy = event.changedTouches[0].clientY - touchStart.y;
      touchStart = null;
      if (Math.abs(dx) >= 45 && Math.abs(dx) > Math.abs(dy) * 1.3) navigate(page + (dx < 0 ? 1 : -1));
    }, { passive:true });
    reader.addEventListener('keydown', event => {
      if (!reader.classList.contains('booklet-viewer-open')) return;
      if (event.key === 'Escape') { event.stopPropagation(); close(); return; }
      if (event.target.closest('select,button,input')) return;
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
      event.preventDefault();
      navigate(page + (event.key === 'ArrowRight' ? 1 : -1));
    });
    reader.dataset.bookletReady = 'true';
    navigate(page, false);
  }
  function initialize(swapped = false) {
    document.body.classList.remove('sidebar-open');
    opener = null;
    const state = syncOverlayState();
    initializeBookletSwipe();
    const detail = dialog();
    const urgentMessage = document.querySelector('[data-notice-focus], [data-error-focus]');
    document.body.classList.toggle('dialog-open', state.detailOpen);
    if (urgentMessage) urgentMessage.focus({ preventScroll: true });
    else if (detail) detail.focus();
    else if (swapped) {
      const returnLink = dialogReturn && [...document.querySelectorAll('a[href]')].find(link => link.href === dialogReturn);
      (returnLink || document.getElementById('main')).focus({ preventScroll: true });
      if (returnLink && Number.isFinite(dialogScrollY)) window.scrollTo(0, dialogScrollY);
      dialogReturn = null;
      dialogScrollY = null;
    }
  }
  document.addEventListener('error', event => {
    if (event.target.matches?.('.product-picture img')) event.target.remove();
  }, true);
  document.addEventListener('click', event => {
    if (event.target.closest('[data-menu-open]')) menu(true);
    if (event.target.closest('[data-menu-close]')) menu(false);
  });
  mobile.addEventListener('change', () => {
    if (!mobile.matches) {
      document.body.classList.remove('sidebar-open');
      opener = null;
      syncOverlayState();
      return;
    }
    if (sidebar().contains(document.activeElement) && !document.body.classList.contains('sidebar-open')) {
      document.querySelector('[data-menu-open]')?.focus();
    }
    syncOverlayState();
  });
  document.addEventListener('htmx:beforeRequest', event => {
    if (!dialog()) {
      const link = event.detail.elt.closest('a');
      const opensDetail = link && new URL(link.href).searchParams.has('product');
      dialogReturn = opensDetail ? link.href : null;
      dialogScrollY = opensDetail ? window.scrollY : null;
    }
  });
  document.addEventListener('htmx:afterSwap', event => {
    if (event.detail.target.id === 'home-content') initialize(true);
  });
  // A failed incremental GET falls back to the ordinary document/error page.
  // POST forms are deliberately not boosted, so writes are never retried here.
  function documentFallback(event) {
    const config = event.detail.requestConfig;
    if (config?.verb !== 'get') return;
    const url = new URL(event.detail.pathInfo?.finalRequestPath || config.path, location.href);
    if (url.origin === location.origin && /^\/ui\/home\/?$/.test(url.pathname)) location.assign(url.href);
  }
  document.addEventListener('htmx:responseError', documentFallback);
  document.addEventListener('htmx:sendError', documentFallback);
  document.addEventListener('keydown', event => {
    const detail = dialog();
    const menuOpen = mobile.matches && document.body.classList.contains('sidebar-open');
    if (event.key === 'Escape') {
      if (detail) detail.querySelector('[data-dialog-close]').click();
      else if (menuOpen) menu(false);
    }
    const container = detail || (menuOpen ? sidebar() : null);
    if (event.key !== 'Tab' || !container) return;
    const controls = [...container.querySelectorAll('a[href],button,input,select,summary')].filter(el => !el.disabled && el.getClientRects().length);
    if (!controls.length) return;
    const first = controls[0], last = controls.at(-1);
    if (event.shiftKey && (document.activeElement === first || document.activeElement === container)) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && (document.activeElement === last || document.activeElement === container)) { event.preventDefault(); first.focus(); }
  });
  initialize();
})();
