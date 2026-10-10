// Browser behavior only. Prices, history and all application state live on the server.
(() => {
  const mobile = window.matchMedia('(max-width: 760px)');
  let opener;
  let dialogReturn;
  const sidebar = () => document.getElementById('sidebar');
  const dialog = () => document.querySelector('.product-dialog');
  function menu(open) {
    document.body.classList.toggle('sidebar-open', open);
    sidebar().inert = mobile.matches && !open;
    document.querySelectorAll('[data-menu-open]').forEach(button => button.setAttribute('aria-expanded', String(open)));
    if (open) { opener = document.activeElement; sidebar().querySelector('a')?.focus(); }
    else if (opener?.isConnected) opener.focus();
  }
  function initialize(swapped = false) {
    document.body.classList.remove('sidebar-open');
    sidebar().inert = mobile.matches;
    const detail = dialog();
    document.body.classList.toggle('dialog-open', Boolean(detail));
    document.querySelector('.app-layout').inert = Boolean(detail);
    document.querySelector('.mobile-bottom').inert = Boolean(detail);
    if (detail) detail.focus();
    else if (swapped) {
      const returnLink = dialogReturn && [...document.querySelectorAll('a[href]')].find(link => link.href === dialogReturn);
      (returnLink || document.getElementById('main')).focus({ preventScroll: true });
      dialogReturn = null;
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
    sidebar().inert = mobile.matches && !document.body.classList.contains('sidebar-open');
  });
  document.addEventListener('htmx:beforeRequest', event => {
    if (!dialog()) {
      const link = event.detail.elt.closest('a');
      dialogReturn = link && new URL(link.href).searchParams.has('product') ? link.href : null;
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
    if (event.key === 'Escape') {
      if (detail) detail.querySelector('[data-dialog-close]').click();
      else if (document.body.classList.contains('sidebar-open')) menu(false);
    }
    const container = detail || (document.body.classList.contains('sidebar-open') ? sidebar() : null);
    if (event.key !== 'Tab' || !container) return;
    const controls = [...container.querySelectorAll('a[href],button,input,select,summary')].filter(el => !el.disabled && el.getClientRects().length);
    if (!controls.length) return;
    const first = controls[0], last = controls.at(-1);
    if (event.shiftKey && (document.activeElement === first || document.activeElement === container)) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && (document.activeElement === last || document.activeElement === container)) { event.preventDefault(); first.focus(); }
  });
  initialize();
})();
