import test from 'node:test';
import assert from 'node:assert/strict';
import { loadOverview } from '../src/ui/status.js';

test('overview shows all current retailer offers even without canonical mappings', async () => {
  const elements = new Map();
  globalThis.document = { getElementById(id) {
    if (!elements.has(id)) elements.set(id, { textContent: '' });
    return elements.get(id);
  }};
  const calls = [];
  await loadOverview(async (url) => {
    calls.push(url);
    if (url.startsWith('/api/v1/deals/current?')) return { available_count: 611, count: 1 };
    return { total_products: 7, products_with_current_offers: 0, current_offer_count: 0,
      comparison_ready_products: 0, retailer_count: 0, timezone: 'Europe/Berlin' };
  }, '2026-09-29');
  assert.equal(elements.get('statOffers').textContent, 611);
  assert.equal(elements.get('statCompare').textContent, 0);
  assert.equal(elements.get('statCurrent').textContent, 0);
  assert.ok(calls.includes('/api/v1/deals/current?as_of=2026-09-29&limit=1'));
});
