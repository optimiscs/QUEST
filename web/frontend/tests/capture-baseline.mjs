// Run once against the pre-migration service using the shared synthetic fixture.
import { chromium } from '@playwright/test';
import fs from 'node:fs/promises';
const fixture = await fs.readFile(new URL('../../tests/fixtures/viewer.json', import.meta.url), 'utf8');
const browser = await chromium.launch({ executablePath: process.env.VIEWER_BROWSER_EXECUTABLE });
for (const [name, viewport] of Object.entries({ desktop: { width: 1440, height: 1000 }, mobile: { width: 390, height: 844 } })) {
  const page = await browser.newPage({ viewport });
  await page.route('**/data/traces.json', route => route.fulfill({ contentType: 'application/json', body: fixture }));
  await page.route('**/datasets/index.json', route => route.fulfill({ json: { datasets: [] } }));
  await page.route('**/api/workspace-status', route => route.fulfill({ json: { datasets: {} } }));
  await page.goto(process.env.VIEWER_LEGACY_URL + '/trace-viewer-zh/');
  await page.locator('.log-row').first().waitFor(); await page.evaluate(() => document.fonts.ready);
  for (const mode of ['trajectory', 'overview']) {
    if (mode === 'overview') await page.locator('#tabOverview').click();
    await page.screenshot({ path: new URL(`./visual/${name}-${mode}.png`, import.meta.url).pathname, animations: 'disabled' });
  }
  await page.close();
}
await browser.close();
