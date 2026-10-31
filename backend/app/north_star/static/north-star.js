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

  // Swipe over source-verified official page images without refetching the app.
  function initializeBookletSwipe() {
    const reader = document.querySelector('.booklet-swipe');
    const track = reader?.querySelector('[data-booklet-swipe]');
    if (!track || track.dataset.bookletReady) return;
    const slides = [...track.querySelectorAll('[data-booklet-slide]')];
    const form = reader.querySelector('[data-booklet-page-form]');
    const select = form?.querySelector('select[name="page"]');
    const prev = reader.querySelector('[data-booklet-prev]');
    const next = reader.querySelector('[data-booklet-next]');
    const counter = reader.querySelector('[data-booklet-counter]');
    const zoom = reader.querySelector('.booklet-zoom-toggle');
    if (!slides.length || !select || !prev || !next || !counter) return;
    let page = Math.max(1, Math.min(slides.length, Number(track.dataset.bookletSwipe) || 1));
    let frame = 0;
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    const href = number => slides[number - 1].dataset.bookletHref;
    function update(number, address = true) {
      if (number < 1 || number > slides.length) return;
      page = number;
      select.value = String(number);
      counter.textContent = String(number);
      prev.href = href(Math.max(1, number - 1));
      next.href = href(Math.min(slides.length, number + 1));
      for (const [node, disabled] of [[prev, number === 1], [next, number === slides.length]]) {
        node.setAttribute('aria-disabled', String(disabled));
        node.tabIndex = disabled ? -1 : 0;
      }
      if (address) {
        const url = new URL(location.href);
        url.searchParams.set('page', String(number));
        if (url.href !== location.href) history.replaceState(history.state, '', url.href);
      }
    }
    function show(number, smooth = true) {
      if (!Number.isInteger(number) || number < 1 || number > slides.length) return;
      if (zoom?.checked) zoom.checked = false;
      const width = slides[0].getBoundingClientRect().width;
      if (!width) return;
      // CSS scroll-behavior:smooth also applies to scrollTo({behavior:'auto'}).
      // Direct jumps (including initial page 72) must not traverse all pages.
      if (smooth && !reducedMotion.matches && Math.abs(number - page) === 1) {
        track.scrollTo({ left: (number - 1) * width, behavior: 'smooth' });
      } else {
        track.style.scrollBehavior = 'auto';
        track.scrollLeft = (number - 1) * width;
        requestAnimationFrame(() => track.style.removeProperty('scroll-behavior'));
      }
      update(number);
    }
    for (const [node, delta] of [[prev, -1], [next, 1]]) {
      node.addEventListener('click', event => { event.preventDefault(); show(page + delta); });
    }
    form.addEventListener('submit', event => { event.preventDefault(); show(Number(select.value)); });
    track.addEventListener('keydown', event => {
      if (event.target !== track || !['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
      event.preventDefault();
      show(page + (event.key === 'ArrowRight' ? 1 : -1));
    });
    track.addEventListener('scroll', () => {
      if (zoom?.checked || frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        const width = slides[0].getBoundingClientRect().width;
        if (width) update(Math.max(1, Math.min(slides.length, Math.round(track.scrollLeft / width) + 1)));
      });
    }, { passive:true });
    const fullscreen = reader.querySelector('[data-booklet-fullscreen]');
    if (fullscreen && reader.requestFullscreen && document.fullscreenEnabled) {
      fullscreen.hidden = false;
      fullscreen.addEventListener('click', () => {
        if (document.fullscreenElement === reader) document.exitFullscreen();
        else reader.requestFullscreen().catch(() => {});
      });
      reader.addEventListener('fullscreenchange', () => show(page, false));
    }
    track.dataset.bookletReady = 'true';
    update(page, false);
    requestAnimationFrame(() => show(page, false));
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
