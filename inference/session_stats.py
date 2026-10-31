"""Aggregate completed policy calls, keeping missing measurements explicit."""

def _count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def aggregate_policy_stats(policies):
    ends = [end for _, end in policies]
    result = {'completedCalls': len(ends)}
    samples = [end['ttft_seconds'] for end in ends
               if isinstance(end.get('ttft_seconds'), (int, float))
               and not isinstance(end['ttft_seconds'], bool) and end['ttft_seconds'] >= 0]
    if samples:
        result.update(ttftSeconds=sum(samples) / len(samples), ttftSamples=len(samples))
    usages = [end.get('api_response', {}).get('usage') if isinstance(end.get('api_response'), dict) else None for end in ends]
    if usages and all(isinstance(u, dict) and _count(u.get('prompt_tokens')) and _count(u.get('completion_tokens')) for u in usages):
        inputs = sum(u['prompt_tokens'] for u in usages)
        outputs = sum(u['completion_tokens'] for u in usages)
        usage = {'inputTokens': inputs, 'outputTokens': outputs, 'totalTokens': inputs + outputs}
        cached = [u['prompt_tokens_details'].get('cached_tokens') if isinstance(u.get('prompt_tokens_details'), dict) else None for u in usages]
        measured = [(v, u['prompt_tokens']) for v, u in zip(cached, usages)
                    if _count(v) and v <= u['prompt_tokens']]
        if measured:
            measured_input = sum(prompt for _, prompt in measured)
            cached_input = sum(value for value, _ in measured)
            usage.update(cachedInputTokens=cached_input, uncachedInputTokens=measured_input-cached_input,
                         cacheMeasuredInputTokens=measured_input, cacheSamples=len(measured), usageSamples=len(usages))
        result['usage'] = usage
    if usages and isinstance(usages[-1], dict) and _count(usages[-1].get('prompt_tokens')):
        context = {'usedTokens': usages[-1]['prompt_tokens']}
        recorded = ends[-1].get('context_measurement')
        if isinstance(recorded, dict):
            context.update({k: v for k, v in recorded.items() if k in ('capacityTokens', 'systemTokens', 'toolTokens', 'messageTokens') and _count(v)})
            if any(k in context for k in ('systemTokens', 'toolTokens', 'messageTokens')):
                context['breakdownEstimated'] = True
        result['context'] = context
    return result
