import { createHash } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { createInterface } from "node:readline/promises";
import { stdin as input, stdout as output } from "node:process";

const SHA_RE = /^[0-9a-f]{40}$/;
const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "[::1]"]);

export function parseOptions(argv) {
  const options = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith("--")) throw new Error(`unexpected argument: ${token}`);
    const key = token.slice(2);
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) throw new Error(`missing value for --${key}`);
    options[key] = value;
    index += 1;
  }
  return options;
}

export function validateOptions(options) {
  const endpoint = new URL(options.endpoint ?? "http://127.0.0.1:9222");
  if (endpoint.protocol !== "http:" || !LOOPBACK_HOSTS.has(endpoint.hostname)) {
    throw new Error("--endpoint must be a loopback http Chrome DevTools endpoint");
  }
  const targetOrigin = new URL(options["target-origin"] ?? "");
  const loopbackHttp = targetOrigin.protocol === "http:" && LOOPBACK_HOSTS.has(targetOrigin.hostname);
  if (!(targetOrigin.protocol === "https:" || loopbackHttp) || targetOrigin.origin !== options["target-origin"]) {
    throw new Error("--target-origin must be one https origin or loopback http origin without path/query/hash");
  }
  if (!SHA_RE.test(options["git-sha"] ?? "")) throw new Error("--git-sha must be 40 lowercase hex chars");
  if (!options.output) throw new Error("--output is required");
  return { endpoint, targetOrigin, gitSha: options["git-sha"], output: resolve(options.output), label: options.label ?? "manual" };
}

export function mergeRanges(ranges) {
  const sorted = ranges.filter(({ start, end }) => Number.isInteger(start) && Number.isInteger(end) && end > start)
    .sort((left, right) => left.start - right.start || left.end - right.end);
  const merged = [];
  for (const range of sorted) {
    const last = merged.at(-1);
    if (!last || range.start > last.end) merged.push({ ...range });
    else last.end = Math.max(last.end, range.end);
  }
  return merged;
}

export function rangeBytes(ranges) {
  return mergeRanges(ranges).reduce((total, range) => total + range.end - range.start, 0);
}

function compactRule(text) {
  return text.replace(/\s+/g, " ").trim().slice(0, 240);
}

export function summarizeSheet({ url, text, usages }) {
  const observed = usages.map(({ startOffset, endOffset }) => ({ start: startOffset, end: endOffset }));
  const used = usages.filter((item) => item.used).map(({ startOffset, endOffset }) => ({ start: startOffset, end: endOffset }));
  return {
    path: new URL(url).pathname,
    sha256: createHash("sha256").update(text).digest("hex"),
    total_bytes: Buffer.byteLength(text),
    observed_rule_bytes: rangeBytes(observed),
    used_rule_bytes: rangeBytes(used),
    rules: usages.map((item) => ({
      start_offset: item.startOffset,
      end_offset: item.endOffset,
      used: Boolean(item.used),
      excerpt: compactRule(text.slice(item.startOffset, item.endOffset)),
    })),
  };
}

function stylesheetAllowed(url, targetOrigin) {
  if (!url) return false;
  const parsed = new URL(url);
  return parsed.origin === targetOrigin.origin;
}

export function normalizeBrowserMetadata(version) {
  const product = version.Browser ?? null;
  const protocolVersion = version["Protocol-Version"] ?? null;
  const userAgent = version["User-Agent"] ?? null;
  if (!product || !protocolVersion || !userAgent) throw new Error("CDP /json/version missing browser metadata");
  return { product, protocol_version: protocolVersion, user_agent: userAgent };
}

async function json(endpoint, path) {
  const response = await fetch(new URL(path, endpoint));
  if (!response.ok) throw new Error(`CDP endpoint ${path} returned ${response.status}`);
  return response.json();
}

function openSession(webSocketUrl) {
  const socket = new WebSocket(webSocketUrl);
  let nextId = 1;
  const pending = new Map();
  const handlers = new Map();
  socket.addEventListener("message", ({ data }) => {
    const message = JSON.parse(String(data));
    if (message.id) {
      const waiter = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) waiter.reject(new Error(message.error.message));
      else waiter.resolve(message.result ?? {});
      return;
    }
    for (const handler of handlers.get(message.method) ?? []) handler(message.params ?? {});
  });
  const ready = new Promise((resolveReady, rejectReady) => {
    socket.addEventListener("open", resolveReady, { once: true });
    socket.addEventListener("error", rejectReady, { once: true });
  });
  return {
    async send(method, params = {}) {
      await ready;
      const id = nextId++;
      const promise = new Promise((resolveSend, rejectSend) => pending.set(id, { resolve: resolveSend, reject: rejectSend }));
      socket.send(JSON.stringify({ id, method, params }));
      return promise;
    },
    on(method, handler) { handlers.set(method, [...(handlers.get(method) ?? []), handler]); },
    close() { socket.close(); },
  };
}

export async function capture(options) {
  const { endpoint, targetOrigin, gitSha, output: outputPath, label } = validateOptions(options);
  const browser = await json(endpoint, "/json/version");
  const targets = await json(endpoint, "/json/list");
  const target = targets.find((item) => item.type === "page" && new URL(item.url).origin === targetOrigin.origin);
  if (!target?.webSocketDebuggerUrl) throw new Error(`no authenticated page target for ${targetOrigin.origin}`);
  const session = openSession(target.webSocketDebuggerUrl);
  const styleSheets = new Map();
  session.on("CSS.styleSheetAdded", ({ header }) => styleSheets.set(header.styleSheetId, header));
  await session.send("DOM.enable");
  await session.send("CSS.enable");
  await session.send("CSS.startRuleUsageTracking");
  const release = await session.send("Runtime.evaluate", { expression: "JSON.stringify({release:document.querySelector(\"meta[name=hermes-ui-release]\")?.content??null,bundle:document.querySelector(\"meta[name=hermes-ui-bundle]\")?.content??null})", returnByValue: true });
  const releaseIdentity = JSON.parse(release.result?.value ?? "{}");
  const prompt = createInterface({ input, output });
  await prompt.question("Exercise Deals/Weekly/List/detail in the attached authenticated browser, then press Enter here... ");
  prompt.close();
  const { ruleUsage = [] } = await session.send("CSS.stopRuleUsageTracking");
  const grouped = new Map();
  for (const usage of ruleUsage) {
    const items = grouped.get(usage.styleSheetId) ?? [];
    items.push(usage);
    grouped.set(usage.styleSheetId, items);
  }

  const sheets = [];
  for (const [styleSheetId, usages] of grouped) {
    const header = styleSheets.get(styleSheetId);
    if (!header || !stylesheetAllowed(header.sourceURL, targetOrigin)) continue;
    const textResult = await session.send("CSS.getStyleSheetText", { styleSheetId });
    sheets.push(summarizeSheet({ url: header.sourceURL, text: textResult.text ?? "", usages }));
  }
  session.close();

  const document = {
    schema_version: 1,
    evidence_kind: "w5c_css_rule_usage",
    label,
    git_sha: gitSha,
    target_origin: targetOrigin.origin,
    browser: normalizeBrowserMetadata(browser),
    release_identity: releaseIdentity,
    privacy: {
      cookies_recorded: false,
      storage_recorded: false,
      request_headers_recorded: false,
      response_bodies_recorded: false,
      query_strings_recorded: false,
    },
    interpretation: {
      unused_means: "not observed used during this captured interaction path",
      globally_dead_claimed: false,
      destructive_cleanup_authorized: false,
    },
    style_sheets: sheets.sort((left, right) => left.path.localeCompare(right.path)),
  };
  await mkdir(dirname(outputPath), { recursive: true });
  await writeFile(outputPath, `${JSON.stringify(document, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
  return document;
}

async function main() {
  const options = parseOptions(process.argv.slice(2));
  const result = await capture(options);
  output.write(`W5C_CSS_COVERAGE=PASS sheets=${result.style_sheets.length} output=${validateOptions(options).output}\n`);
}

const isMain = process.argv[1] && import.meta.url === new URL(`file://${resolve(process.argv[1])}`).href;
if (isMain) {
  main().catch((error) => {
    console.error(`W5C_CSS_COVERAGE=FAIL ${error.message}`);
    process.exitCode = 1;
  });
}
