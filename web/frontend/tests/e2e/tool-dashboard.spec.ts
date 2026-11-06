import { test, expect } from '@playwright/test';

test('cross-run selection, true zero filter, live polling and saved selection', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  // CI uses synthetic runs; never depend on a local research dataset.
  await page.route('**/api/v1/**', route => {
    const path = new URL(route.request().url()).pathname;
    const run = path.includes('tools-b') ? 'tools-b' : 'tools-a';
    const etag = `"fixture-${run}"`;
    let body;
    if (path === '/api/v1/runs') body = { datasets: [
      { id: 'tools-a', label: 'Checkpoint A' }, { id: 'tools-b', label: 'Checkpoint B' },
    ] };
    else if (path.endsWith('/tool-events')) {
      if (route.request().headers()['if-none-match'] === etag)
        return route.fulfill({ status: 304, headers: { ETag: etag } });
      body = { traceId: 'row0001', revision: run, inProgress: false, events: [
        { step: 1, tool: 'web_search', status: 'success', zeroResults: true, reasons: [], error: '', queries: ['empty query'], elapsedSeconds: 10 },
        { step: 2, tool: 'web_search', status: 'failed', zeroResults: false, reasons: ['超时'], error: 'search_server timeout', queries: ['failed query'], elapsedSeconds: 100 },
      ] };
    } else if (path.endsWith('/traces')) body = { runRevision: run, nextCursor: null,
      items: [{ id: 'row0001', revision: run, topicZh: 'Synthetic question' }] };
    else body = { id: run, revision: run, metadata: {}, run: {}, counts: {} };
    return route.fulfill({ json: body, headers: { ETag: etag } });
  });
  await page.goto('/tool-dashboard.html?dataset=tools-a&trace=row0001');
  await expect(page.locator('#selection-count')).toHaveText('1');
  await expect(page.locator('#sync')).toContainText('同步完成');
  await expect(page.locator('#chart svg')).toBeVisible();
  await page.locator('#status-filter').selectOption('zero');
  await expect(page.locator('#details')).toContainText('成功 · 零结果');
  await expect(page.locator('#details')).not.toContainText('timeout');
  await page.locator('#dataset').selectOption('tools-b');
  await expect(page.locator('#trace-list [data-id="row0001"]')).not.toBeChecked();
  await page.locator('#trace-list [data-id="row0001"]').check();
  await expect(page.locator('#selection-count')).toHaveText('2');
  await expect(page.locator('#sync')).toContainText('同步完成');
  await page.locator('#chart-mode').selectOption('live');
  await expect(page.locator('#chart svg')).toBeVisible();
  const cached = page.waitForResponse(r => r.url().includes('/tool-events') && r.status() === 304);
  await page.locator('#refresh').click();
  await cached;
  await expect(page.locator('#sync')).toContainText('同步完成');
  await page.locator('#status-filter').selectOption('failed');
  await page.locator('[data-reason="超时"]').click();
  await expect(page.locator('#detail-count')).toContainText('超时');
  await expect(page.locator('#details')).toContainText('超时');
  await page.reload();
  await expect(page.locator('#selection-count')).toHaveText('2');
  await expect(page.locator('#sync')).toContainText('同步完成');
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.locator('#clear').click();
  await expect(page.locator('#selection-count')).toHaveText('0');
  await expect(page.locator('#rate')).toHaveText('—');
  expect(errors).toEqual([]);
});
