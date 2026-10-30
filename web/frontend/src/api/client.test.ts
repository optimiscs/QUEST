import { afterEach, expect, test, vi } from 'vitest';
import { loadRun } from './client';

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
