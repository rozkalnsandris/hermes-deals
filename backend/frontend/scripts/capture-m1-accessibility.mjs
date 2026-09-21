#!/usr/bin/env node
import { spawn } from 'node:child_process';
import net from 'node:net';
import { mkdtemp, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

function parseArgs(argv) {
  const options = {
    baseUrl: 'http://127.0.0.1:9190/ui/',
    chromeBin: process.env.CHROME_BIN || 'google-chrome',
    releaseRef: '',
    releaseHtmlSha256: '',
  };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    const value = argv[i + 1];
    if (arg === '--base-url' && value) { options.baseUrl = value; i += 1; }
    else if (arg === '--chrome-bin' && value) { options.chromeBin = value; i += 1; }
    else if (arg === '--release-ref' && value) { options.releaseRef = value; i += 1; }
    else if (arg === '--release-html-sha256' && value) { options.releaseHtmlSha256 = value; i += 1; }
    else if (arg === '--help') options.help = true;
    else throw new Error(`unknown or incomplete option: ${arg}`);
  }
  const url = new URL(options.baseUrl);
  if (!['127.0.0.1', 'localhost', '::1'].includes(url.hostname)) {
    throw new Error('base URL must be loopback-only');
  }
  if (!options.releaseRef || !options.releaseHtmlSha256) {
    throw new Error('--release-ref and --release-html-sha256 are required');
  }
  return options;
}

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function reservePort() {
  return await new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      server.close((error) => error ? reject(error) : resolve(port));
    });
  });
}

async function waitForDebugger(port) {
  for (let i = 0; i < 50; i += 1) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/version`);
      if (response.ok) return response.json();
    } catch {}
    await delay(100);
  }
  throw new Error('Chrome debugger did not become ready');
}

async function connectPage(port) {
  const targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
  const page = targets.find((item) => item.type === 'page');
  if (!page) throw new Error('Chrome page target not found');
  const socket = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.onopen = resolve;
    socket.onerror = reject;
  });
  let id = 0;
  const pending = new Map();
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (!message.id || !pending.has(message.id)) return;
    const { resolve, reject } = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) reject(new Error(message.error.message));
    else resolve(message.result);
  };
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const requestId = ++id;
    pending.set(requestId, { resolve, reject });
    socket.send(JSON.stringify({ id: requestId, method, params }));
  });
  const evaluate = async (expression) => {
    const result = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || 'browser evaluation failed');
    return result.result.value;
  };
  return { socket, send, evaluate };
}

async function navigate(client, url, width, height, mobile) {
  await client.send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile });
  await client.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'no-preference' }] });
  await client.send('Page.navigate', { url });
  await delay(1200);
  const location = await client.evaluate('location.href');
  if (location !== url) throw new Error(`unexpected navigation target: ${location}`);
}

async function captureMobile(client, url) {
  await navigate(client, url, 390, 844, true);
  const initialState = await client.evaluate(`(()=>({
    viewport:[innerWidth,innerHeight],
    bodyZoom:getComputedStyle(document.body).zoom,
    drawerInert:document.getElementById('listDrawer').hasAttribute('inert'),
    drawerHidden:document.getElementById('listDrawer').getAttribute('aria-hidden'),
    bottomLabels:[...document.querySelectorAll('.bottom-nav button span')].map(x=>x.textContent.trim())
  }))()`);
  await dispatchTab(client, false);
  const focusOutline = await client.evaluate(`(()=>{const el=document.activeElement;const s=getComputedStyle(el);return {tag:el?.tagName||'',id:el?.id||'',style:s.outlineStyle,width:s.outlineWidth,color:s.outlineColor}})()`);
  const initial = { ...initialState, focusOutline };
  const drawer = await client.evaluate(`(async()=>{
    const opener=document.querySelector('.bottom-nav [data-action="list"]');
    opener.focus(); opener.click();
    await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
    const d=document.getElementById('listDrawer');
    const opened={open:d.classList.contains('open'),inert:d.hasAttribute('inert'),hidden:d.getAttribute('aria-hidden'),activeId:document.activeElement?.id||''};
    document.getElementById('closeList').click();
    await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
    return {opened,closed:{open:d.classList.contains('open'),inert:d.hasAttribute('inert'),hidden:d.getAttribute('aria-hidden'),focusReturned:document.activeElement===opener}};
  })()`);
  const detail = await client.evaluate(`(async()=>{
    const opener=document.querySelector('.bottom-nav [data-target="deals"]');
    opener.focus();
    const d=document.getElementById('detail');
    d.classList.add('open');
    await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
    const opened={inert:d.hasAttribute('inert'),hidden:d.getAttribute('aria-hidden'),role:d.getAttribute('role'),modal:d.getAttribute('aria-modal'),activeId:document.activeElement?.id||''};
    d.classList.remove('open');
    await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
    return {opened,closed:{inert:d.hasAttribute('inert'),hidden:d.getAttribute('aria-hidden'),focusReturned:document.activeElement===opener}};
  })()`);
  await client.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] });
  const reducedMotion = await client.evaluate(`(()=>{const el=document.querySelector('.bottom-nav button');const s=getComputedStyle(el);return {match:matchMedia('(prefers-reduced-motion: reduce)').matches,transitionDuration:s.transitionDuration,animationDuration:s.animationDuration,scrollBehavior:getComputedStyle(document.documentElement).scrollBehavior}})()`);
  return { initial, drawer, detail, reducedMotion };
}

async function dispatchTab(client, shift = false) {
  const modifiers = shift ? 8 : 0;
  for (const type of ['keyDown', 'keyUp']) {
    await client.send('Input.dispatchKeyEvent', { type, key: 'Tab', code: 'Tab', modifiers, windowsVirtualKeyCode: 9, nativeVirtualKeyCode: 9 });
  }
  await delay(50);
}

async function captureDesktop(client, url) {
  await navigate(client, url, 1365, 768, false);
  const initial = await client.evaluate(`(()=>({viewport:[innerWidth,innerHeight],bodyZoom:getComputedStyle(document.body).zoom,mainCount:document.querySelectorAll('main').length}))()`);
  await client.evaluate(`(()=>{const d=document.getElementById('listDrawer');d.classList.add('open');return true})()`);
  await delay(100);
  const endpoints = await client.evaluate(`(()=>{const d=document.getElementById('listDrawer');const cs=[...d.querySelectorAll('button:not([disabled]),a[href],[tabindex]:not([tabindex="-1"])')].filter(x=>!x.hidden);cs.at(-1).focus();return {first:cs[0]?.id||'',last:cs.at(-1)?.id||''}})()`);
  await dispatchTab(client, false);
  const forward = await client.evaluate(`document.activeElement?.id||''`);
  await dispatchTab(client, true);
  const backward = await client.evaluate(`document.activeElement?.id||''`);
  return { initial, tabTrap: { ...endpoints, forward, backward } };
}

function assertAcceptance(evidence) {
  const m = evidence.mobile;
  const d = evidence.desktop;
  const checks = {
    fiveMobileActions: m.initial.bottomLabels.length === 5,
    initialDrawerInert: m.initial.drawerInert === true && m.initial.drawerHidden === 'true',
    visibleFocus: m.initial.focusOutline.style !== 'none' && m.initial.focusOutline.width !== '0px',
    drawerLifecycle: m.drawer.opened.open === true && m.drawer.opened.inert === false && m.drawer.opened.hidden === 'false' && m.drawer.opened.activeId === 'closeList' && m.drawer.closed.open === false && m.drawer.closed.inert === true && m.drawer.closed.hidden === 'true' && m.drawer.closed.focusReturned === true,
    detailLifecycle: m.detail.opened.inert === false && m.detail.opened.hidden === 'false' && m.detail.opened.role === 'dialog' && m.detail.opened.modal === 'true' && m.detail.opened.activeId === 'closeDetail' && m.detail.closed.inert === true && m.detail.closed.hidden === 'true' && m.detail.closed.focusReturned === true,
    reducedMotion: m.reducedMotion.match === true && m.reducedMotion.scrollBehavior === 'auto',
    oneMainLandmark: d.initial.mainCount === 1,
    tabTrap: d.tabTrap.forward === d.tabTrap.first && d.tabTrap.backward === d.tabTrap.last,
    effectiveZoomOne: m.initial.bodyZoom === '1' && d.initial.bodyZoom === '1',
  };
  const failed = Object.entries(checks).filter(([, value]) => !value).map(([name]) => name);
  return { checks, pass: failed.length === 0, failed };
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.help) return;
  const profile = await mkdtemp(path.join(os.tmpdir(), 'hermes-m1-chrome-'));
  const port = await reservePort();
  const chrome = spawn(options.chromeBin, [
    '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    `--user-data-dir=${profile}`, '--remote-debugging-address=127.0.0.1', `--remote-debugging-port=${port}`, 'about:blank'
  ], { stdio: ['ignore', 'ignore', 'pipe'] });
  let stderr = '';
  chrome.stderr.setEncoding('utf8');
  chrome.stderr.on('data', (chunk) => { stderr += chunk; });
  try {
    const version = await waitForDebugger(port);
    const client = await connectPage(port);
    await client.send('Page.enable'); await client.send('Runtime.enable');
    const evidence = {
      schemaVersion: 1,
      release: { ref: options.releaseRef, htmlSha256: options.releaseHtmlSha256 },
      browser: { product: version.Browser, protocolVersion: version['Protocol-Version'], userAgent: version['User-Agent'] },
      mobile: await captureMobile(client, options.baseUrl),
      desktop: await captureDesktop(client, options.baseUrl),
    };
    evidence.acceptance = assertAcceptance(evidence);
    console.log(JSON.stringify(evidence, null, 2));
    client.socket.close();
    if (!evidence.acceptance.pass) process.exitCode = 1;
  } finally {
    chrome.kill('SIGTERM');
    await rm(profile, { recursive: true, force: true });
  }
}

main().catch((error) => { console.error(error.stack || String(error)); process.exitCode = 1; });
