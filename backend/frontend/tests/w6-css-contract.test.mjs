import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const stylesUrl = new URL("../../app/ui/styles.css", import.meta.url);

async function styles() {
  return readFile(stylesUrl, "utf8");
}

test("W6 removes global CSS zoom and gives the base mobile nav five bounded columns", async () => {
  const css = await styles();
  assert.doesNotMatch(css, /\bzoom\s*:/i);
  assert.match(css, /\.bottom-nav\{[^}]*grid-template-columns:repeat\(5,minmax\(0,1fr\)\)/);
  assert.match(css, /\.bottom-nav button\{[^}]*min-width:0/);
});

test("W6 reduced-motion covers drawer, scrim, cards and smooth scrolling", async () => {
  const css = await styles();
  const block = css.match(/@media\(prefers-reduced-motion:reduce\)\{([^]*?)\}\s*\/\* Hermes Deals 2\.0 control-room layer \*\//)?.[1] || "";
  assert.match(block, /html\{scroll-behavior:auto\}/);
  assert.match(block, /\.drawer/);
  assert.match(block, /\.scrim/);
  assert.match(block, /\.card/);
  assert.match(block, /transition:none!important/);
  assert.match(block, /transform:none!important/);
});

test("W6 keeps a visible focus indicator for primary interactive controls", async () => {
  const css = await styles();
  assert.match(css, /:where\(button,a\[href\],input,select,textarea,\[tabindex\]:not\(\[tabindex=\"-1\"\]\)\):focus-visible/);
  assert.match(css, /outline:3px solid/);
});
