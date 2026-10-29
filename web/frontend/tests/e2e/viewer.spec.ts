import { test, expect } from '@playwright/test';
import { PNG } from 'pngjs';
import pixelmatch from 'pixelmatch';
import fs from 'node:fs/promises';

async function loaded(page) {
  await expect(page.locator('.log-row').first()).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
}

test('click loads one complete trace; cache, search, expand and history work', async ({ page }) => {
  const errors: string[] = [], requests: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => requests.push(request.url()));
  await page.goto('/trace-viewer-zh/');
  await loaded(page);
  expect(requests.filter(url => /\/traces\/[^/?]+(?:\?|$)/.test(url))).toHaveLength(1);
  expect(requests.some(url => /\/datasets\/.*traces\.json/.test(url))).toBe(false);
  expect(await page.locator('[data-search]').count()).toBe(0);
  await page.locator('.log-row summary').first().click();
  await expect(page.locator('.log-row').first()).toHaveAttribute('data-hydrated', '1');
  await page.locator('#traceSearch').fill('nonexistent-b18d5bff-token');
  await expect(page.locator('#searchCount')).toHaveText('0');
  await page.locator('#traceSearch').fill('');
  await expect(page.locator('.log-row').first()).toBeVisible();
  await page.locator('[data-case="1"]').click();
  await expect(page).toHaveURL(/#trace-02$/);
  await page.locator('[data-case="0"]').click();
  await expect(page).toHaveURL(/#trace-01$/);
  expect(requests.filter(url => /\/traces\/trace-01(?:\?|$)/.test(url))).toHaveLength(1);
  await page.goBack();
  await expect(page).toHaveURL(/#trace-02$/);
  await page.locator('#tabOverview').click();
  await expect(page.locator('#overviewView')).toBeVisible();
  await expect(page.locator('[data-site-option="en"]')).toHaveAttribute('href', '/#trace-02/overview');
  expect(errors).toEqual([]);
});

test('a different task update preserves the active event DOM', async ({ page }) => {
  await page.goto('/');
  await loaded(page);
  await page.locator('.log-row summary').first().click();
  await page.evaluate(() => { window.__row = document.querySelector('.log-row'); });
  await page.route('**/api/v1/runs/default-en', async route => {
    const headers = { ...route.request().headers() };
    delete headers['if-none-match'];
    const response = await route.fetch({ headers });
    const info = await response.json();
    info.revision = 'test-updated-revision';
    await route.fulfill({ response, json: info });
  });
  await page.route('**/api/v1/runs/default-en/traces?*', async route => {
    const response = await route.fetch();
    const body = await response.json();
    body.runRevision = 'test-updated-revision';
    body.items[1].topicZh = '另一个任务更新';
    await route.fulfill({ response, json: body });
  });
  await expect(page.locator('[data-case="1"]')).toContainText('另一个任务更新', { timeout: 15000 });
  expect(await page.evaluate(() => window.__row === document.querySelector('.log-row'))).toBe(true);
  await expect(page.locator('.log-row').first()).toHaveAttribute('open', '');
});

test('failed detail request retains the currently displayed trace', async ({ page }) => {
  await page.goto('/'); await loaded(page);
  const title = await page.locator('#contextTitle').textContent();
  await page.route('**/api/v1/runs/default-en/traces/trace-02', route => route.fulfill({ status: 503, body: '{}' }));
  await page.locator('[data-case="1"]').click();
  await expect(page.locator('#toastText')).toContainText('轨迹加载失败');
  await expect(page.locator('#contextTitle')).toHaveText(title!);
  await expect(page.locator('#app')).not.toHaveAttribute('aria-busy');
});

test('desktop and mobile match the original visual baselines', async ({ page }, testInfo) => {
  const fixture = JSON.parse(await fs.readFile(new URL('../../../tests/fixtures/viewer.json', import.meta.url), 'utf8'));
  const summaries = fixture.cases.map(item => ({ id: item.id, index: item.index, topicZh: item.topicZh,
    correct: item.correct, stats: item.stats, durationSeconds: item.durationSeconds, revision: 'fixture' }));
  await page.route('**/api/v1/**', route => {
    const path = new URL(route.request().url()).pathname;
    let body;
    if (path === '/api/v1/runs') body = { datasets: [] };
    else if (path === '/api/v1/workspace-status') body = { datasets: {} };
    else if (/\/traces\/trace-/.test(path)) body = fixture.cases.find(item => path.endsWith('/' + item.id));
    else if (path.endsWith('/traces')) body = { runRevision: 'fixture', items: summaries, nextCursor: null };
    else body = { id: 'default-zh', revision: 'fixture', metadata: { hiddenDefault: true }, run: fixture.run, counts: {} };
    return route.fulfill({ json: body, headers: { ETag: '"fixture"' } });
  });
  for (const [name, viewport] of Object.entries({ desktop: { width: 1440, height: 1000 }, mobile: { width: 390, height: 844 } })) {
    await page.setViewportSize(viewport);
    await page.goto('/trace-viewer-zh/'); await loaded(page);
    for (const mode of ['trajectory', 'overview']) {
      if (mode === 'overview') await page.locator('#tabOverview').click();
      const before = PNG.sync.read(await fs.readFile(new URL(`../visual/${name}-${mode}.png`, import.meta.url)));
      const after = PNG.sync.read(await page.screenshot({ animations: 'disabled' }));
      const diff = new PNG({ width: before.width, height: before.height });
      const changed = pixelmatch(before.data, after.data, diff.data, before.width, before.height, { threshold: 0.1 });
      await testInfo.attach(`${name}-${mode}-difference`, { body: PNG.sync.write(diff), contentType: 'image/png' });
      expect(changed / (before.width * before.height)).toBeLessThan(0.001);
    }
  }
});

test('large IDs resolve directly and request only the selected trace', async ({ page }) => {
  test.skip(!process.env.VIEWER_REAL_DATA, 'Requires the imported historical dataset');
  const details: string[] = [];
  page.on('request', request => { if (/\/traces\/trace-/.test(request.url())) details.push(request.url()); });
  await page.goto('/?dataset=browsecomp-sft-25pct-pool64-20261029-r1#trace-245');
  await loaded(page);
  await expect(page.locator('.task-item.is-active .task-num')).toHaveText('245');
  expect(details).toHaveLength(1);
  expect(details[0]).toContain('/trace-245');
});
