#!/usr/bin/env python3
"""Aggregate completed memory spans, keeping unavailable timings separate."""
import argparse
import glob
import json
import math
from collections import defaultdict


def summarize(values):
    values = sorted(values)
    if not values:
        return {"count": 0, "mean": None, "p50": None, "p95": None}
    def percentile(p):
        return values[max(0, math.ceil(p * len(values)) - 1)]
    return {"count": len(values), "mean": sum(values) / len(values),
            "p50": percentile(.5), "p95": percentile(.95)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('paths', nargs='+', help='event files or glob patterns')
    args = parser.parse_args()
    files = sorted({f for p in args.paths for f in glob.glob(p)})
    if not files:
        parser.error('No event files found')
    samples = defaultdict(list)
    completed = 0
    for path in files:
        with open(path, encoding='utf-8') as file:
            for line in file:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get('event') != 'span_end' or event.get('kind') != 'memory_api':
                    continue
                completed += 1
                response = event.get('api_response') or {}
                usage = response.get('usage') or {}
                metrics = response.get('metrics') or {}
                values = {
                    'client_total_s': event.get('seconds'),
                    'queue_s': (metrics.get('queue_time_ms') / 1000 if metrics.get('queue_time_ms') is not None else None),
                    'scheduled_to_first_token_s': (metrics.get('time_to_first_token_ms') / 1000 if metrics.get('time_to_first_token_ms') is not None else None),
                    'decode_s': (metrics.get('generation_time_ms') / 1000 if metrics.get('generation_time_ms') is not None else None),
                    'prompt_tokens': usage.get('prompt_tokens'),
                    'completion_tokens': usage.get('completion_tokens'),
                    'cached_tokens': (usage.get('prompt_tokens_details') or {}).get('cached_tokens'),
                }
                for key, value in values.items():
                    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                        samples[key].append(value)
    keys = ('client_total_s', 'queue_s', 'scheduled_to_first_token_s', 'decode_s', 'prompt_tokens', 'completion_tokens', 'cached_tokens')
    print(json.dumps({'completed_spans': completed, 'files': len(files),
                      'metrics': {key: summarize(samples[key]) for key in keys}}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
