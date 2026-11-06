import { readdir, readFile } from 'node:fs/promises';
import { basename } from 'node:path';

// The workflow starts the viewer with `uv run ... &`. Its parent holds uv's
// cache lock until the server exits, so leaving it alive breaks post-job pruning.
export default async function stopCiViewer() {
  if (process.env.GITHUB_ACTIONS !== 'true') return;
  const database = process.env.VIEWER_DATABASE_URL || '';
  if (!database.split('?')[0].endsWith('_test')) return;
  const owned: number[] = [];
  for (const entry of await readdir('/proc')) {
    if (!/^\d+$/.test(entry)) continue;
    try {
      const args = (await readFile(`/proc/${entry}/cmdline`, 'utf8')).split('\0').filter(Boolean);
      const port = args.indexOf('--port');
      if (port < 0 || args[port + 1] !== '6081') continue;
      if (!args.includes('quest_viewer.app:create_app') || !args.includes('--factory')) continue;
      if (!args.some(arg => basename(arg) === 'uvicorn')) continue;
      owned.push(Number(entry));
    } catch { /* Process already exited. */ }
  }
  for (const pid of owned) {
    try { process.kill(pid, 'SIGTERM'); } catch { /* Already exited. */ }
  }
  for (let attempt = 0; attempt < 30; attempt++) {
    if (owned.every(pid => { try { process.kill(pid, 0); return false; } catch { return true; } })) return;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  for (const pid of owned) {
    try { process.kill(pid, 'SIGKILL'); } catch { /* Already exited. */ }
  }
}
