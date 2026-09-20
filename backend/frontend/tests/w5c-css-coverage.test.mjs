import test from "node:test";
import assert from "node:assert/strict";

import {
  mergeRanges,
  normalizeBrowserMetadata,
  parseOptions,
  rangeBytes,
  summarizeSheet,
  validateOptions,
} from "../scripts/capture-w5c-css-coverage.mjs";

test("coverage option parsing is explicit and deterministic", () => {
  assert.deepEqual(
    parseOptions(["--endpoint", "http://127.0.0.1:9222", "--git-sha", "a".repeat(40), "--target-origin", "https://deals.example", "--output", "/tmp/w5c.json"]),
    {
      endpoint: "http://127.0.0.1:9222",
      "git-sha": "a".repeat(40),
      "target-origin": "https://deals.example",
      output: "/tmp/w5c.json",
    },
  );
});

test("coverage options reject non-loopback debugger and non-origin target", () => {
  assert.throws(() => validateOptions({ endpoint: "http://10.0.0.2:9222", "git-sha": "a".repeat(40), "target-origin": "https://deals.example", output: "/tmp/x" }), /loopback/);
  assert.throws(() => validateOptions({ endpoint: "http://127.0.0.1:9222", "git-sha": "a".repeat(40), "target-origin": "https://deals.example/path", output: "/tmp/x" }), /origin without path/);
  assert.throws(() => validateOptions({ endpoint: "http://127.0.0.1:9222", "git-sha": "a".repeat(40), "target-origin": "http://deals.example", output: "/tmp/x" }), /loopback http origin/);
  assert.equal(validateOptions({ endpoint: "http://127.0.0.1:9222", "git-sha": "a".repeat(40), "target-origin": "http://127.0.0.1:19128", output: "/tmp/x" }).targetOrigin.origin, "http://127.0.0.1:19128");
  assert.throws(() => validateOptions({ endpoint: "http://127.0.0.1:9222", "git-sha": "BAD", "target-origin": "https://deals.example", output: "/tmp/x" }), /40 lowercase/);
});
test("range accounting merges overlap before byte totals", () => {
  assert.deepEqual(mergeRanges([{ start: 0, end: 10 }, { start: 5, end: 15 }, { start: 30, end: 35 }]), [
    { start: 0, end: 15 },
    { start: 30, end: 35 },
  ]);
  assert.equal(rangeBytes([{ start: 0, end: 10 }, { start: 5, end: 15 }, { start: 30, end: 35 }]), 20);
});

test("sheet summary records path/hash/rule usage without query strings", () => {
  const summary = summarizeSheet({
    url: "https://deals.example/assets/app.abc.css?secret=nope",
    text: ".used { color: red; }\n.unused { color: blue; }\n",
    usages: [
      { startOffset: 0, endOffset: 21, used: true },
      { startOffset: 22, endOffset: 47, used: false },
    ],
  });
  assert.equal(summary.path, "/assets/app.abc.css");
  assert.equal(summary.rules.length, 2);
  assert.equal(summary.rules[0].used, true);
  assert.equal(summary.rules[1].used, false);
  assert.match(summary.sha256, /^[0-9a-f]{64}$/);
  assert.ok(!JSON.stringify(summary).includes("secret=nope"));
});

test("browser version metadata uses Chrome DevTools field names", () => {
  assert.deepEqual(normalizeBrowserMetadata({ Browser: "Chrome/140", "Protocol-Version": "1.3", "User-Agent": "UA" }), {
    product: "Chrome/140",
    protocol_version: "1.3",
    user_agent: "UA",
  });
  assert.throws(() => normalizeBrowserMetadata({}), /missing browser metadata/);
});
