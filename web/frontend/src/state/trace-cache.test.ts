import { describe, it, expect } from 'vitest';
import { TraceCache } from './trace-cache';

describe('TraceCache', () => {
  it('evicts least recently used entries within a byte limit', () => {
    const cache = new TraceCache<string>(12);
    cache.set('a', '123'); cache.set('b', '456');
    expect(cache.get('a')).toBe('123');
    cache.set('c', '789');
    expect(cache.get('b')).toBeUndefined();
    expect(cache.get('a')).toBe('123');
    cache.set('huge', 'x'.repeat(100));
    expect(cache.get('huge')).toBeUndefined();
    cache.clear(); expect(cache.get('a')).toBeUndefined();
  });
});
