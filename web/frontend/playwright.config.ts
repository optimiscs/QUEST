import { defineConfig } from '@playwright/test';
import { resolve } from 'node:path';
export default defineConfig({
  testDir: 'tests/e2e',
  outputDir: '../../workspace/viewer/test-results',
  timeout: 60000,
  workers: 1,
  use: { launchOptions: { executablePath: process.env.VIEWER_BROWSER_EXECUTABLE, env: { ...process.env, FONTCONFIG_FILE: resolve('tests/fontconfig.conf') } }, baseURL: process.env.VIEWER_E2E_URL || 'http://127.0.0.1:6081', viewport: { width: 1440, height: 1000 } },
});
