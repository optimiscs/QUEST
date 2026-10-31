from inference.session_stats import aggregate_policy_stats


def test_aggregate_usage_with_cache_and_last_context():
    def end(prompt, output, cache, ttft):
        return {'api_response': {'usage': {'prompt_tokens': prompt, 'completion_tokens': output,
                    'prompt_tokens_details': {'cached_tokens': cache}}}, 'ttft_seconds': ttft}
    first, last = end(100, 10, 60, .3), end(200, 20, 150, .5)
    last['context_measurement'] = {'capacityTokens': 1000, 'systemTokens': 10}
    result = aggregate_policy_stats([({}, first), ({}, last)])
    assert result['usage'] == {'inputTokens': 300, 'outputTokens': 30, 'totalTokens': 330,
                               'cachedInputTokens': 210, 'uncachedInputTokens': 90,
                               'cacheMeasuredInputTokens': 300, 'cacheSamples': 2, 'usageSamples': 2}
    assert result['ttftSeconds'] == .4 and result['ttftSamples'] == 2
    assert result['context'] == {'usedTokens': 200, 'capacityTokens': 1000,
                                  'systemTokens': 10, 'breakdownEstimated': True}


def test_missing_fields_not_counted_as_zero():
    rows = [({}, {'api_response': {'usage': {'prompt_tokens': 10, 'completion_tokens': 2}}}),
            ({}, {'api_response': {'usage': None}})]
    result = aggregate_policy_stats(rows)
    assert 'usage' not in result and 'context' not in result and 'ttftSeconds' not in result
    assert result['completedCalls'] == 2


def test_partial_cache_reports_coverage_without_guessing_old_calls():
    rows = [({}, {'api_response': {'usage': {'prompt_tokens': 100, 'completion_tokens': 2}}}),
            ({}, {'api_response': {'usage': {'prompt_tokens': 200, 'completion_tokens': 4,
                                             'prompt_tokens_details': {'cached_tokens': 150}}}})]
    usage = aggregate_policy_stats(rows)['usage']
    assert (usage['cacheSamples'], usage['usageSamples']) == (1, 2)
    assert (usage['cacheMeasuredInputTokens'], usage['cachedInputTokens'], usage['uncachedInputTokens']) == (200, 150, 50)
