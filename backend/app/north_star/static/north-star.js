// Browser behavior only. Prices, history and all demo state live on the server.
(() => {
  const sidebar = document.getElementById('sidebar');
  const openers = [...document.querySelectorAll('[data-menu-open]')];
  const mobile = window.matchMedia('(max-width: 760px)');
  let opener;
  function menu(open) {
    document.body.classList.toggle('sidebar-open', open);
    sidebar.inert = mobile.matches && !open;
    openers.forEach(button => button.setAttribute('aria-expanded', String(open)));
    if (open) { opener = document.activeElement; sidebar.querySelector('a')?.focus(); }
    else opener?.focus();
  }
  openers.forEach(button => button.addEventListener('click', () => menu(true)));
  document.querySelectorAll('[data-menu-close]').forEach(button => button.addEventListener('click', () => menu(false)));
  const syncSidebar = () => { sidebar.inert = mobile.matches && !document.body.classList.contains('sidebar-open'); };
  mobile.addEventListener('change', syncSidebar); syncSidebar();
  const dialog = document.querySelector('.product-dialog');
  if (dialog) {
    document.body.classList.add('dialog-open');
    document.querySelector('.app-layout').inert = true;
    document.querySelector('.mobile-bottom').inert = true;
    dialog.focus();
  }
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      if (dialog) location.href = dialog.querySelector('[data-dialog-close]').href;
      else if (document.body.classList.contains('sidebar-open')) menu(false);
    }
    const container = dialog || (document.body.classList.contains('sidebar-open') ? sidebar : null);
    if (event.key !== 'Tab' || !container) return;
    const controls = [...container.querySelectorAll('a[href],button,input,select,summary')].filter(el => !el.disabled && el.getClientRects().length);
    if (!controls.length) return;
    const first = controls[0], last = controls.at(-1);
    if (event.shiftKey && (document.activeElement === first || document.activeElement === container)) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && (document.activeElement === last || document.activeElement === container)) { event.preventDefault(); first.focus(); }
  });
})();
