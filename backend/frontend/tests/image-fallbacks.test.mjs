import assert from "node:assert/strict";
import test from "node:test";

import {
  handleImageLoadError,
  imageFallbackDescriptor,
  installImageFallbacks,
} from "../src/ui/image-fallbacks.js";

function classList(...names) {
  const values = new Set(names);
  return { contains: (name) => values.has(name) };
}

function fakeDocument() {
  return {
    createElement(tagName) {
      return { tagName: String(tagName).toUpperCase(), className: "", textContent: "" };
    },
  };
}

test("image fallback descriptors keep existing UI placeholder semantics", () => {
  assert.deepEqual(
    imageFallbackDescriptor({ classList: classList("media") }),
    { parentClass: "media", tagName: "div", className: "media-placeholder", text: "Attēls nav pieejams" },
  );
  assert.deepEqual(
    imageFallbackDescriptor({ classList: classList("daily-special-media") }),
    { parentClass: "daily-special-media", tagName: "div", className: "daily-special-placeholder", text: "Attēls nav pieejams" },
  );
  assert.deepEqual(
    imageFallbackDescriptor({ classList: classList("weekly-product-media") }),
    { parentClass: "weekly-product-media", tagName: "span", className: "weekly-product-placeholder", text: "Nav attēla" },
  );
  assert.equal(imageFallbackDescriptor({ classList: classList("unrelated") }), null);
});

test("failed retailer images are replaced instead of leaving a broken image", () => {
  let replacement = null;
  const image = {
    tagName: "img",
    classList: classList(),
    parentElement: { classList: classList("media") },
    replaceWith(value) { replacement = value; },
  };

  assert.equal(handleImageLoadError(image, fakeDocument()), true);
  assert.equal(replacement.tagName, "DIV");
  assert.equal(replacement.className, "media-placeholder");
  assert.equal(replacement.textContent, "Attēls nav pieejams");
});

test("failed project logo restores the inline reviewed brand mark", () => {
  const inlineMark = { hidden: true };
  const image = {
    tagName: "IMG",
    hidden: false,
    classList: classList("project-logo"),
    parentElement: { querySelector: (selector) => selector === "svg[hidden]" ? inlineMark : null },
  };

  assert.equal(handleImageLoadError(image, fakeDocument()), true);
  assert.equal(image.hidden, true);
  assert.equal(inlineMark.hidden, false);
});

test("image error listener is installed in capture phase for dynamic images", () => {
  const doc = fakeDocument();
  let listener = null;
  let capture = null;
  const root = {
    ownerDocument: doc,
    addEventListener(type, handler, options) {
      assert.equal(type, "error");
      listener = handler;
      capture = options;
    },
  };
  let replacement = null;
  const image = {
    tagName: "IMG",
    classList: classList(),
    parentElement: { classList: classList("detail-image") },
    replaceWith(value) { replacement = value; },
  };

  assert.equal(installImageFallbacks(root), true);
  assert.equal(capture, true);
  listener({ target: image });
  assert.equal(replacement.className, "detail-placeholder");
  assert.equal(replacement.textContent, "Attēls nav pieejams");
});
