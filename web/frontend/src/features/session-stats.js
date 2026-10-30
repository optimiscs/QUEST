/** Statistics for the selected trace. Missing measurements remain unknown. */
const valid = value => typeof value === 'number' && Number.isFinite(value) && value >= 0;
const pick = value => valid(value) ? value : null;

export function deriveSessionStats(trace) {
  const stats = trace?.sessionStats || {};
  const usage = stats.usage || {};
  const context = stats.context || {};
  const modelSeconds = pick(stats.modelSeconds) ?? pick(trace?.timing?.model);
  const steps = Array.isArray(trace?.steps) ? trace.steps : [];
  const stepToolTimes = steps.filter(step => step?.tool).map(step => pick(step.tool_seconds));
  const toolSeconds = pick(stats.toolSeconds) ?? (stepToolTimes.length && stepToolTimes.every(value => value !== null)
    ? stepToolTimes.reduce((a, b) => a + b, 0) : null);
  const outputTokens = pick(usage.outputTokens);
  const inputTokens = pick(usage.inputTokens);
  const cached = pick(usage.cachedInputTokens);
  const uncached = pick(usage.uncachedInputTokens) ?? (inputTokens !== null && cached !== null && cached <= inputTokens ? inputTokens - cached : null);
  const total = pick(usage.totalTokens) ?? (inputTokens !== null && outputTokens !== null ? inputTokens + outputTokens : null);
  const capacity = pick(context.capacityTokens);
  const used = pick(context.usedTokens);
  return {
    rounds: pick(trace?.rounds) ?? pick(trace?.stats?.steps),
    events: Array.isArray(trace?.steps) ? steps.reduce((sum, step) => sum + 1 + (step.tool ? 1 : 0), 0) : null,
    modelSeconds, toolSeconds,
    ttftSeconds: pick(stats.ttftSeconds),
    // Total output over model-call wall time is an effective rate, not decode-only throughput.
    tps: pick(stats.outputTokensPerSecond) ?? (outputTokens !== null && modelSeconds > 0 ? outputTokens / modelSeconds : null),
    total, inputTokens, outputTokens, cached, uncached,
    cacheRate: inputTokens > 0 && cached !== null && cached <= inputTokens ? cached / inputTokens : null,
    contextUsed: used, contextCapacity: capacity,
    contextRate: capacity > 0 && used !== null ? used / capacity : null,
    systemTokens: pick(context.systemTokens), toolTokens: pick(context.toolTokens), messageTokens: pick(context.messageTokens),
  };
}

export function compactTokens(value) {
  if (!valid(value)) return '未记录';
  if (value >= 1e6) return `${(value / 1e6).toFixed(1).replace(/\.0$/, '')}M`;
  if (value >= 1e3) return `${(value / 1e3).toFixed(1).replace(/\.0$/, '')}K`;
  return new Intl.NumberFormat('en-US').format(value);
}
