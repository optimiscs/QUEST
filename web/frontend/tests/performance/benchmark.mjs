import { chromium } from '@playwright/test';
const browser = await chromium.launch({ executablePath: process.env.VIEWER_BROWSER_EXECUTABLE });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const base = process.env.VIEWER_E2E_URL || 'http://127.0.0.1:6081';
const results = [];
for (const [name, path] of [
  ['default', '/'],
  ['largest-trace', '/?dataset=browsecomp-sft-25pct-pool64-20261029-r1#trace-245'],
]) {
  await page.goto(base + path);
  await page.locator('.log-row').first().waitFor();
  const result = await page.evaluate(() => ({
    elapsedMs: performance.now(),
    api: performance.getEntriesByType('resource').filter(r => r.name.includes('/api/')).map(r => ({
      url: r.name.split('/api/')[1], durationMs: r.duration, encodedBytes: r.encodedBodySize, decodedBytes: r.decodedBodySize,
    })),
    domNodes: document.querySelectorAll('*').length,
    hydratedRows: document.querySelectorAll('[data-hydrated="1"]').length,
  }));
  results.push({ name, ...result });
}
console.log(JSON.stringify(results, null, 2));
await browser.close();
