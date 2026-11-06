"""Fail closed if the served LoRA is absent or indistinguishable from its base."""
import json
import math
import sys
from pathlib import Path
import requests

base = 'http://127.0.0.1:19320'
prompts = ['What is the capital of France?', 'Find the most recent annual report for a company.',
           'What evidence should be checked before answering a research question?']
checks = []
for prompt in prompts:
    results = []
    for model in ('qwen38-bf16-base', 'qwen38-27b'):
        response = requests.post(base + '/v1/chat/completions', json={
            'model': model, 'messages': [{'role': 'user', 'content': prompt}],
            'temperature': 0, 'max_tokens': 1, 'logprobs': True, 'top_logprobs': 1}, timeout=180)
        response.raise_for_status()
        item = response.json()['choices'][0]['logprobs']['content'][0]
        assert isinstance(item['logprob'], (int, float)) and math.isfinite(item['logprob'])
        results.append({'token': item['token'], 'logprob': item['logprob']})
    distinct = results[0]['token'] != results[1]['token'] or abs(results[0]['logprob'] - results[1]['logprob']) > 1e-5
    checks.append({'prompt': prompt, 'base': results[0], 'adapter': results[1], 'different': distinct})
    if distinct:
        break
if not any(c['different'] for c in checks):
    raise RuntimeError('LoRA and base produce indistinguishable logits; evaluation not started')
Path(sys.argv[1]).write_text(json.dumps({'status': 'pass', 'scope': 'LoRA affects logits; not a quality evaluation',
                                       'checks': checks}, indent=2))
print('LoRA logits verification passed', flush=True)
