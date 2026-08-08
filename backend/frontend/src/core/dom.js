export const $ = (id) => document.getElementById(id);

export function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

export function allowedHttpUrl(value, base = window.location.href) {
  if (!value) return null;
  try {
    const parsed = new URL(String(value), base);
    return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : null;
  } catch {
    return null;
  }
}
