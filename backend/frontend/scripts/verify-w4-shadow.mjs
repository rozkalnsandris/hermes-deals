import { createHash } from "node:crypto";
import { readFile, stat, writeFile } from "node:fs/promises";
import { resolve, sep } from "node:path";

const root = resolve(import.meta.dirname, "..");
const dist = resolve(root, "dist-w4");
const manifestPath = resolve(dist, ".vite", "manifest.json");
const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
const entries = Object.entries(manifest).filter(([, value]) => value?.isEntry === true);

if (entries.length !== 1) {
  throw new Error(`expected exactly one W4 manifest entry, found ${entries.length}`);
}

const [entryKey, entry] = entries[0];
if (entryKey !== "src/w4-entry.js") {
  throw new Error(`unexpected W4 manifest entry: ${entryKey}`);
}
if (!Array.isArray(entry.css) || entry.css.length !== 1) {
  throw new Error("W4 entry must emit exactly one CSS asset");
}

const jsPattern = /^assets\/[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{8,}\.js$/;
const cssPattern = /^assets\/[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{8,}\.css$/;
if (!jsPattern.test(entry.file)) {
  throw new Error(`W4 entry JS is not content-hashed: ${entry.file}`);
}
if (!cssPattern.test(entry.css[0])) {
  throw new Error(`W4 entry CSS is not content-hashed: ${entry.css[0]}`);
}

function safeAssetPath(relativePath) {
  const absolute = resolve(dist, relativePath);
  if (!absolute.startsWith(`${dist}${sep}`)) {
    throw new Error(`unsafe W4 manifest path: ${relativePath}`);
  }
  return absolute;
}

async function digest(relativePath, requiredMarker) {
  const absolute = safeAssetPath(relativePath);
  const info = await stat(absolute);
  if (!info.isFile()) {
    throw new Error(`W4 asset is not a regular file: ${relativePath}`);
  }
  const payload = await readFile(absolute);
  const text = payload.toString("utf8");
  if (!text.includes(requiredMarker)) {
    throw new Error(`W4 asset lost required marker: ${requiredMarker}`);
  }
  return {
    path: relativePath,
    bytes: payload.length,
    sha256: createHash("sha256").update(payload).digest("hex"),
  };
}

const js = await digest(entry.file, "w3-behavior-preserving-bootstrap-v1");
const css = await digest(entry.css[0], "HERMES_UI_STYLE_OPEN:");
const manifestBytes = await readFile(manifestPath);
const manifestSha256 = createHash("sha256").update(manifestBytes).digest("hex");
const evidence = {
  result: "PASS",
  version: "w4a-shadow-build-v1",
  base: "/ui/",
  entry: entryKey,
  js,
  css,
  manifest: {
    path: ".vite/manifest.json",
    bytes: manifestBytes.length,
    sha256: manifestSha256,
  },
};

await writeFile(
  resolve(dist, "w4-shadow-build.json"),
  `${JSON.stringify(evidence, null, 2)}\n`,
  "utf8",
);

console.log("W4_SHADOW_BUILD=PASS");
console.log(`W4_SHADOW_JS=${js.path}`);
console.log(`W4_SHADOW_JS_SHA256=${js.sha256}`);
console.log(`W4_SHADOW_CSS=${css.path}`);
console.log(`W4_SHADOW_CSS_SHA256=${css.sha256}`);
console.log(`W4_SHADOW_MANIFEST_SHA256=${manifestSha256}`);
