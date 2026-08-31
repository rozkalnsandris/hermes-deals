import test from "node:test";
import assert from "node:assert/strict";

class FakeClassList {
  constructor() { this.values = new Set(); }
  add(...names) { names.forEach((name) => this.values.add(name)); }
  remove(...names) { names.forEach((name) => this.values.delete(name)); }
  contains(name) { return this.values.has(name); }
}

class FakeHTMLElement {
  constructor(id = "") {
    this.id = id;
    this.classList = new FakeClassList();
    this.attrs = new Map();
    this.inert = false;
    this.focusables = [];
    this.childrenById = new Map();
    this.parent = null;
  }
  setAttribute(name, value) { this.attrs.set(name, String(value)); }
  getAttribute(name) { return this.attrs.get(name) ?? null; }
  hasAttribute(name) { return this.attrs.has(name); }
  querySelector(selector) { return selector.startsWith("#") ? this.childrenById.get(selector.slice(1)) || null : null; }
  querySelectorAll() { return this.focusables; }
  contains(node) { return node === this || this.focusables.includes(node) || node?.parent === this; }
  focus() { globalThis.document.activeElement = this; }
}

function panel(id, closeId) {
  const value = new FakeHTMLElement(id);
  const close = new FakeHTMLElement(closeId);
  close.parent = value;
  value.childrenById.set(closeId, close);
  value.focusables = [close];
  return { value, close };
}

async function withFakeDom(run) {
  const previous = {
    HTMLElement: globalThis.HTMLElement,
    HTMLInputElement: globalThis.HTMLInputElement,
    HTMLTextAreaElement: globalThis.HTMLTextAreaElement,
    HTMLSelectElement: globalThis.HTMLSelectElement,
    document: globalThis.document,
    requestAnimationFrame: globalThis.requestAnimationFrame,
  };
  globalThis.HTMLElement = FakeHTMLElement;
  globalThis.HTMLInputElement = class extends FakeHTMLElement {};
  globalThis.HTMLTextAreaElement = class extends FakeHTMLElement {};
  globalThis.HTMLSelectElement = class extends FakeHTMLElement {};
  const body = new FakeHTMLElement("body");
  const listeners = [];
  globalThis.document = {
    activeElement: null,
    body,
    addEventListener(type, listener, capture) { listeners.push({ type, listener, capture }); },
  };
  globalThis.requestAnimationFrame = (callback) => callback();
  try {
    await run({ listeners });
  } finally {
    Object.assign(globalThis, previous);
  }
}

test("drawer starts inert, opens into focus, and restores its invoker on close", async () => {
  await withFakeDom(async () => {
    const { initOverlays } = await import("../src/ui/overlays.js");
    const drawer = panel("listDrawer", "closeList");
    const product = panel("detail", "closeDetail");
    const deal = panel("dealDetail", "closeDealDetail");
    const scrim = new FakeHTMLElement("scrim");
    const confirm = new FakeHTMLElement("clearListConfirm");
    const cancel = new FakeHTMLElement("cancelClearList");
    const accept = new FakeHTMLElement("confirmClearList");
    const invoker = new FakeHTMLElement("openList");
    document.activeElement = invoker;

    const controller = initOverlays({
      listDrawer: drawer.value,
      detail: product.value,
      dealDetail: deal.value,
      scrim,
      clearListConfirm: confirm,
      cancelClearList: cancel,
      confirmClearList: accept,
      renderList() {},
    });

    assert.equal(drawer.value.inert, true);
    assert.equal(drawer.value.getAttribute("aria-hidden"), "true");
    controller.openDrawer(invoker);
    assert.equal(drawer.value.inert, false);
    assert.equal(drawer.value.getAttribute("aria-hidden"), "false");
    assert.equal(document.activeElement, drawer.close);

    controller.closeOverlays();
    assert.equal(drawer.value.inert, true);
    assert.equal(drawer.value.getAttribute("aria-hidden"), "true");
    assert.equal(document.activeElement, invoker);
  });
});

test("detail overlays expose modal semantics and trap keyboard focus", async () => {
  await withFakeDom(async () => {
    const { initOverlays, openAccessibleOverlay } = await import("../src/ui/overlays.js");
    const drawer = panel("listDrawer", "closeList");
    const product = panel("detail", "closeDetail");
    const second = new FakeHTMLElement("detailAction");
    second.parent = product.value;
    product.value.focusables.push(second);
    const deal = panel("dealDetail", "closeDealDetail");
    const scrim = new FakeHTMLElement("scrim");
    const confirm = new FakeHTMLElement("clearListConfirm");
    const cancel = new FakeHTMLElement("cancelClearList");
    const accept = new FakeHTMLElement("confirmClearList");

    const controller = initOverlays({
      listDrawer: drawer.value,
      detail: product.value,
      dealDetail: deal.value,
      scrim,
      clearListConfirm: confirm,
      cancelClearList: cancel,
      confirmClearList: accept,
      renderList() {},
    });

    assert.equal(product.value.getAttribute("role"), "dialog");
    assert.equal(product.value.getAttribute("aria-modal"), "true");
    openAccessibleOverlay({ panel: product.value, scrim, focusTarget: product.close });
    assert.equal(document.activeElement, product.close);

    document.activeElement = second;
    let prevented = false;
    controller.trapActiveOverlayFocus({ key: "Tab", shiftKey: false, preventDefault() { prevented = true; } });
    assert.equal(prevented, true);
    assert.equal(document.activeElement, product.close);

    document.activeElement = product.close;
    prevented = false;
    controller.trapActiveOverlayFocus({ key: "Tab", shiftKey: true, preventDefault() { prevented = true; } });
    assert.equal(prevented, true);
    assert.equal(document.activeElement, second);
  });
});
