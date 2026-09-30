const IMAGE_FALLBACKS = Object.freeze([
  Object.freeze({ parentClass: "media", tagName: "div", className: "media-placeholder", text: "Attēls nav pieejams" }),
  Object.freeze({ parentClass: "daily-special-media", tagName: "div", className: "daily-special-placeholder", text: "Attēls nav pieejams" }),
  Object.freeze({ parentClass: "weekly-product-media", tagName: "span", className: "weekly-product-placeholder", text: "Nav attēla" }),
  Object.freeze({ parentClass: "detail-image", tagName: "div", className: "detail-placeholder", text: "Attēls nav pieejams" }),
]);

export function imageFallbackDescriptor(parent) {
  if (!parent?.classList?.contains) return null;
  return IMAGE_FALLBACKS.find((candidate) => parent.classList.contains(candidate.parentClass)) || null;
}

export function handleImageLoadError(image, doc = document) {
  if (!image || String(image.tagName || "").toUpperCase() !== "IMG") return false;

  if (image.classList?.contains?.("project-logo")) {
    image.hidden = true;
    const inlineMark = image.parentElement?.querySelector?.("svg[hidden]");
    if (inlineMark) inlineMark.hidden = false;
    return true;
  }

  const fallback = imageFallbackDescriptor(image.parentElement);
  if (!fallback || !image.replaceWith || !doc?.createElement) return false;

  const replacement = doc.createElement(fallback.tagName);
  replacement.className = fallback.className;
  replacement.textContent = fallback.text;
  image.replaceWith(replacement);
  return true;
}

export function installImageFallbacks(root = document) {
  if (!root?.addEventListener) return false;
  root.addEventListener("error", (event) => {
    handleImageLoadError(event.target, root.ownerDocument || root);
  }, true);
  return true;
}
