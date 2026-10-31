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

  // Source-owned page URLs; the browser manages only fullscreen and image gestures.
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
    const hud = reader?.querySelector('[data-booklet-viewer-hud]');
    const closeButton = hud?.querySelector('[data-booklet-viewer-close]');
    const hudPrev = hud?.querySelector('[data-booklet-viewer-prev]');
    const hudNext = hud?.querySelector('[data-booklet-viewer-next]');
    const hudCount = hud?.querySelector('[data-booklet-viewer-count]');
    const zoomIn = hud?.querySelector('[data-booklet-zoom-in]');
    const zoomOut = hud?.querySelector('[data-booklet-zoom-out]');
    const zoomLevel = hud?.querySelector('[data-booklet-zoom-level]');
    if (!reader || !canvas || !image || !form || !select || !prev || !next ||
        !counter || !toggle || !hud || !closeButton || !hudPrev || !hudNext || !hudCount ||
        !zoomIn || !zoomOut || !zoomLevel) return;
    if (reader.dataset.bookletReady) return;
    const options = [...select.options];
    if (!options.length || options.some(option => !option.dataset.bookletImageUrl)) return;
    let page = Number(select.value);
    if (!Number.isInteger(page) || page < 1 || page > options.length) return;
    let nativeEntered = false;
    let gesture = null;
    let mousePan = null;
    const failedHiResPages = new Set();
    let scale = 1;
    let x = 0;
    let y = 0;
    const maxZoom = 5;
    const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
    const isOpen = () => reader.classList.contains('booklet-viewer-open');
    function syncImageResolution() {
      const option = options[page - 1];
      if (!option) return;
      // Higher resolutions are exposed only from SHA-verified Publitas sizes.
      const high = option.dataset.bookletZoomImageUrl;
      const fallback = option.dataset.bookletImageUrl;
      const desired = scale > 1.01 && high && !failedHiResPages.has(page) ? high : fallback;
      if (image.getAttribute('src') !== desired) image.src = desired;
    }
    image.addEventListener('error', () => {
      const option = options[page - 1];
      if (!option || image.getAttribute('src') !== option.dataset.bookletZoomImageUrl) return;
      failedHiResPages.add(page);
      image.src = option.dataset.bookletImageUrl;
    });
    function applyTransform() {
      const bounds = canvas.getBoundingClientRect();
      const maxX = Math.max(0, (image.offsetWidth * scale - bounds.width) / 2);
      const maxY = Math.max(0, (image.offsetHeight * scale - bounds.height) / 2);
      x = clamp(x, -maxX, maxX);
      y = clamp(y, -maxY, maxY);
      image.style.transform = 'translate(' + x + 'px, ' + y + 'px) scale(' + scale + ')';
      canvas.classList.toggle('is-zoomed', scale > 1.01);
      zoomIn.disabled = scale >= maxZoom - .001;
      zoomOut.disabled = scale <= 1.001;
      zoomLevel.textContent = Math.round(scale * 100) + '%';
      syncImageResolution();
    }
    function resetZoom() {
      scale = 1;
      x = 0;
      y = 0;
      gesture = null;
      mousePan = null;
      canvas.classList.remove('is-panning');
      applyTransform();
    }
    function zoomAt(nextScale, clientX, clientY) {
      const bounds = canvas.getBoundingClientRect();
      const cx = bounds.left + bounds.width / 2;
      const cy = bounds.top + bounds.height / 2;
      const next = clamp(nextScale, 1, maxZoom);
      x = clientX - cx - (clientX - cx - x) * next / scale;
      y = clientY - cy - (clientY - cy - y) * next / scale;
      scale = next;
      if (scale === 1) { x = 0; y = 0; }
      applyTransform();
    }
    function zoomCentered(factor) {
      const bounds = canvas.getBoundingClientRect();
      zoomAt(scale * factor, bounds.left + bounds.width / 2, bounds.top + bounds.height / 2);
    }
    function navigate(number, updateUrl = true) {
      if (!Number.isInteger(number) || number < 1 || number > options.length) return;
      if (number !== page) resetZoom();
      page = number;
      select.value = String(number);
      image.src = options[number - 1].dataset.bookletImageUrl;
      // A page change always begins with the verified standard image.
      image.alt = 'Netto buklets, ' + number + '. lapa no ' + options.length;
      counter.textContent = String(number);
      hudCount.textContent = number + ' / ' + options.length;
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
      hudPrev.disabled = number === 1;
      hudNext.disabled = number === options.length;
      if (updateUrl) {
        const url = new URL(location.href);
        url.searchParams.set('page', String(number));
        if (url.href !== location.href) history.replaceState(history.state, '', url.href);
      }
    }
    function close() {
      if (!isOpen()) return;
      reader.classList.remove('booklet-viewer-open');
      document.body.classList.remove('booklet-viewer-active');
      canvas.setAttribute('aria-label', 'Atvērt Netto bukletu pilnekrānā');
      toggle.setAttribute('aria-expanded', 'false');
      hud.hidden = true;
      resetZoom();
      if (document.fullscreenElement === reader) document.exitFullscreen().catch(() => {});
      nativeEntered = false;
      toggle.focus({ preventScroll:true });
    }
    function open() {
      if (isOpen()) return;
      reader.classList.add('booklet-viewer-open');
      document.body.classList.add('booklet-viewer-active');
      canvas.setAttribute('aria-label', 'Netto buklets. Pietuvini ar plus/mīnus pogām, peles ritentiņu vai diviem pirkstiem; šķirsti ar bultiņām.');
      toggle.setAttribute('aria-expanded', 'true');
      hud.hidden = false;
      resetZoom();
      closeButton.focus({ preventScroll:true });
      // Native fullscreen may reject; the full-viewport overlay still works.
      if (document.fullscreenEnabled && reader.requestFullscreen) {
        reader.requestFullscreen({ navigationUI: 'hide' }).catch(() => {});
      }
    }
    for (const [link, delta] of [[prev, -1], [next, 1]]) {
      link.addEventListener('click', event => {
        if (!isOpen()) return;
        event.preventDefault();
        navigate(page + delta);
      });
    }
    for (const [button, delta] of [[hudPrev, -1], [hudNext, 1]]) {
      button.addEventListener('click', () => navigate(page + delta));
    }
    form.addEventListener('submit', event => {
      if (!isOpen()) return;
      event.preventDefault();
      navigate(Number(select.value));
    });
    toggle.hidden = false;
    toggle.addEventListener('click', open);
    closeButton.addEventListener('click', close);
    // One click opens the cover; clicks within the reader are reserved for verified product hotspots.
    image.addEventListener('click', () => { if (!isOpen()) open(); });
    zoomIn.addEventListener('click', () => zoomCentered(1.5));
    zoomOut.addEventListener('click', () => zoomCentered(1 / 1.5));
    // Prevent native page scrolling only inside the active booklet canvas.
    canvas.addEventListener('wheel', event => {
      if (!isOpen()) return;
      if (event.cancelable) event.preventDefault();
      const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? canvas.clientHeight : 1;
      const delta = Math.max(-180, Math.min(180, event.deltaY * unit));
      if (delta) zoomAt(scale * Math.exp(-delta / 320), event.clientX, event.clientY);
    }, { passive:false });
    // Drag with the mouse only while enlarged; touch keeps its existing pinch/pan behavior.
    canvas.addEventListener('pointerdown', event => {
      if (!isOpen() || event.pointerType !== 'mouse' || event.button !== 0 ||
          scale <= 1.01 || event.target !== image) return;
      mousePan = { id:event.pointerId, startX:event.clientX, startY:event.clientY, x, y };
      canvas.setPointerCapture(event.pointerId);
      canvas.classList.add('is-panning');
    });
    canvas.addEventListener('pointermove', event => {
      if (!mousePan || mousePan.id !== event.pointerId) return;
      x = mousePan.x + event.clientX - mousePan.startX;
      y = mousePan.y + event.clientY - mousePan.startY;
      applyTransform();
    });
    function stopMousePan(event) {
      if (!mousePan || mousePan.id !== event.pointerId) return;
      mousePan = null;
      canvas.classList.remove('is-panning');
      if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
    }
    canvas.addEventListener('pointerup', stopMousePan);
    canvas.addEventListener('pointercancel', stopMousePan);
    canvas.addEventListener('keydown', event => {
      if (!isOpen() && (event.key === 'Enter' || event.key === ' ')) {
        event.preventDefault();
        open();
      }
    });
    reader.addEventListener('fullscreenchange', () => {
      if (document.fullscreenElement === reader) nativeEntered = true;
      else if (nativeEntered) close();
    });
    const point = touch => ({ x: touch.clientX, y: touch.clientY });
    const middle = (a, b) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });
    const distance = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
    canvas.addEventListener('touchstart', event => {
      if (!isOpen()) return;
      if (event.touches.length >= 2) {
        const a = point(event.touches[0]), b = point(event.touches[1]);
        const focus = middle(a, b);
        const rect = canvas.getBoundingClientRect();
        const center = { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
        gesture = {
          type: 'pinch', distance: Math.max(1, distance(a, b)), scale,
          anchorX: (focus.x - center.x - x) / scale,
          anchorY: (focus.y - center.y - y) / scale,
        };
      } else if (event.touches.length === 1 && !gesture) {
        gesture = { type: scale > 1.01 ? 'pan' : 'swipe',
          origin: point(event.touches[0]), x, y };
      }
    }, { passive:true });
    canvas.addEventListener('touchmove', event => {
      if (!isOpen() || !gesture) return;
      if (gesture.type === 'pinch' && event.touches.length >= 2) {
        event.preventDefault();
        const a = point(event.touches[0]), b = point(event.touches[1]);
        const focus = middle(a, b);
        const rect = canvas.getBoundingClientRect();
        scale = clamp(gesture.scale * distance(a, b) / gesture.distance, 1, maxZoom);
        x = focus.x - (rect.left + rect.width / 2) - gesture.anchorX * scale;
        y = focus.y - (rect.top + rect.height / 2) - gesture.anchorY * scale;
        if (scale === 1) { x = 0; y = 0; }
        applyTransform();
      } else if (gesture.type === 'pan' && event.touches.length === 1) {
        event.preventDefault();
        x = gesture.x + event.touches[0].clientX - gesture.origin.x;
        y = gesture.y + event.touches[0].clientY - gesture.origin.y;
        applyTransform();
      } else if (gesture.type === 'swipe' && event.touches.length === 1) {
        event.preventDefault();
      }
    }, { passive:false });
    canvas.addEventListener('touchend', event => {
      if (!isOpen() || !gesture) return;
      if (gesture.type === 'swipe' && event.touches.length === 0 && event.changedTouches.length === 1) {
        const dx = event.changedTouches[0].clientX - gesture.origin.x;
        const dy = event.changedTouches[0].clientY - gesture.origin.y;
        if (Math.abs(dx) >= 45 && Math.abs(dx) > Math.abs(dy) * 1.3) navigate(page + (dx < 0 ? 1 : -1));
      }
      gesture = null; // Do not turn the remaining finger of a pinch into a swipe.
    }, { passive:true });
    canvas.addEventListener('touchcancel', () => { gesture = null; }, { passive:true });
    reader.addEventListener('keydown', event => {
      if (!isOpen()) return;
      if (event.key === 'Escape') { event.stopPropagation(); close(); return; }
      // Arrow keys must also work when the viewer close/control buttons have focus.
      if (event.target.closest('select,input')) return;
      if (event.key === '0') { event.preventDefault(); resetZoom(); return; }
      if (event.key === '+' || event.key === '=') {
        event.preventDefault();
        zoomCentered(1.5);
        return;
      }
      if (event.key === '-' || event.key === '_') {
        event.preventDefault();
        zoomCentered(1 / 1.5);
        return;
      }
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
      event.preventDefault();
      if (scale <= 1.01) navigate(page + (event.key === 'ArrowRight' ? 1 : -1));
    });
    window.addEventListener('resize', () => { if (isOpen()) applyTransform(); });
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
