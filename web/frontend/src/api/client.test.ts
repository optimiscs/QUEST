import { afterEach, expect, test, vi } from 'vitest';
import { loadRun, loadTrace } from './client';

afterEach(() => vi.unstubAllGlobals());

test('retries pagination when a publication crosses page requests', async () => {
  const replies = [
    { id: 'run', revision: 'old', run: {}, metadata: {}, counts: {} },
    { runRevision: 'new', items: [], nextCursor: null },
    { id: 'run', revision: 'new', run: {}, metadata: {}, counts: {} },
    { runRevision: 'new', items: [{ id: 'one', revision: 'v1' }], nextCursor: 1 },
    { runRevision: 'new', items: [{ id: 'two', revision: 'v2' }], nextCursor: null },
  ];
  const fetch = vi.fn(async () => new Response(JSON.stringify(replies.shift()), { status: 200 }));
  vi.stubGlobal('fetch', fetch);
  const result = await loadRun('run');
  expect(result.info.revision).toBe('new');
  expect(result.cases.map(item => item.id)).toEqual(['one', 'two']);
  expect(fetch).toHaveBeenCalledTimes(5);
});

test('detail uses logical revision independently of representation cache version', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({id:'one',steps:[]}), {
    headers:{ETag:'"trace-view-v1-tool-health-v2-data-v1"','X-Trace-Revision':'data-v1'},
  })));
  expect((await loadTrace('run','one',undefined,'data-v1')).id).toBe('one');
});

test('a genuinely changed detail is still rejected', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({id:'one',steps:[]}), {
    headers:{ETag:'"trace-view-v1-tool-health-v2-data-v2"','X-Trace-Revision':'data-v2'},
  })));
  await expect(loadTrace('run','one',undefined,'data-v1')).rejects.toThrow('轨迹正在更新');
});

test('legacy detail responses with an unversioned ETag remain supported', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({id:'one',steps:[]}), {
    headers:{ETag:'"data-v1"'},
  })));
  expect((await loadTrace('run','one',undefined,'data-v1')).id).toBe('one');
});
