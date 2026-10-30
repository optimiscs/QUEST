import { describe, expect, it } from 'vitest';
import { deriveSessionStats, compactTokens } from './session-stats';

describe('selected trajectory statistics', () => {
  it('does not invent token, cache, TTFT, or context values for older traces', () => {
    const stats = deriveSessionStats({ rounds: 2, timing: { model: 8 }, steps: [
      { tool: { name: 'search' }, tool_seconds: 3 }, { tool: null, tool_seconds: 0 },
    ] });
    expect(stats).toMatchObject({ rounds: 2, events: 3, modelSeconds: 8, toolSeconds: 3,
      total: null, cacheRate: null, tps: null, ttftSeconds: null, contextRate: null });
    expect(compactTokens(null)).toBe('未记录');
  });
  it('uses recorded token and context values and computes effective throughput', () => {
    const stats = deriveSessionStats({ timing: { model: 10 }, steps: [], sessionStats: {
      toolSeconds: 4, usage: { inputTokens: 1000, cachedInputTokens: 800, outputTokens: 200 },
      context: { usedTokens: 500, capacityTokens: 1000, systemTokens: 50 },
    } });
    expect(stats).toMatchObject({ total: 1200, uncached: 200, cacheRate: 0.8, tps: 20,
      contextRate: 0.5, systemTokens: 50, toolSeconds: 4 });
    expect(compactTokens(1200)).toBe('1.2K');
  });
  it('does not report invalid cached counts or division by zero', () => {
    const stats = deriveSessionStats({ timing: { model: 0 }, steps: [], sessionStats: {
      usage: { inputTokens: 10, cachedInputTokens: 11, outputTokens: 0 },
      context: { usedTokens: 1, capacityTokens: 0 },
    } });
    expect(stats).toMatchObject({ uncached: null, cacheRate: null, tps: null, contextRate: null });
  });
});
