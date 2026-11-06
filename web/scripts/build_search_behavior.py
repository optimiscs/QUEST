#!/usr/bin/env python3
"""Build a compact search-behaviour dataset from the trace viewer runs."""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import re
import statistics
import sys
import unicodedata
from pathlib import Path

BASE = Path('/root/autodl-tmp/Quest/web/trace-viewer')
OUT = Path('/root/autodl-tmp/Quest/web/search-behavior/data.json')
NEAR = 0.75
EXTEND = 0.30
STOP = set('a an the and or of to in for on with at by from is are was were be been it this that these those as into about what which who how when where why'.split())
TOKEN_RE = re.compile(r'[a-z0-9]+|[\u4e00-\u9fff]+')


def norm_text(value):
    value = unicodedata.normalize('NFKC', str(value or '')).lower()
    value = value.replace('“', '"').replace('”', '"').replace('’', "'").replace('‘', "'")
    value = re.sub(r'\s+', ' ', value)
    return value.strip()


def tokens_of(value):
    return [t for t in TOKEN_RE.findall(norm_text(value)) if t not in STOP]


def jaccard(left, right):
    if not left or not right:
        return 0.0
    inter = len(left & right)
    union = len(left | right)
    return inter / union if union else 0.0


def status_of(case):
    if case.get('inProgress'):
        return 'running'
    if case.get('interrupted'):
        return 'interrupted'
    if case.get('correct') is True:
        return 'pass'
    if case.get('correct') is False:
        return 'fail'
    return 'unscored'


def behaviour_for(total, repeat_rate, new_rate, extend_rate):
    if total <= 1:
        return 'single'
    if repeat_rate >= 0.45 and new_rate < 0.35:
        return 'repeat'
    if repeat_rate < 0.30 and (new_rate + extend_rate) >= 0.70:
        return 'expand'
    return 'mixed'


def process_case(case: dict, run: dict):
    records = []
    for step in sorted(case.get('steps') or [], key=lambda x: x.get('n', 0)):
        tool = step.get('tool') or {}
        for q in tool.get('queries') or []:
            text = str(q.get('query') or '').strip()
            if not text:
                continue
            records.append({
                'round': step.get('n', 0),
                'q': text,
                'results': int(q.get('count') or 0),
                'seconds': round(float(q.get('seconds') or 0), 2),
            })
    if not records:
        return None

    seen_norm = set()
    seen_tokens = set()
    best_counts = {}
    counts = {'start': 0, 'new': 0, 'extend': 0, 'near': 0, 'exact': 0}
    cases_queries = []

    for index, record in enumerate(records, 1):
        text = record['q']
        key = norm_text(text)
        tokens = set(tokens_of(text))
        exact = key in seen_norm
        max_sim = 0.0
        related = None
        for previous in cases_queries:
            sim = jaccard(tokens, previous['tokenSet'])
            if sim > max_sim:
                max_sim = sim
                related = previous['index']
        if index == 1:
            category = 'start'
        elif exact:
            category = 'exact'
        elif max_sim >= NEAR:
            category = 'near'
        elif max_sim >= EXTEND:
            category = 'extend'
        else:
            category = 'new'
        new_terms = []
        for token in tokens_of(text):
            if token not in seen_tokens and token not in new_terms:
                new_terms.append(token)
            if len(new_terms) >= 8:
                break
        query = {
            'index': index,
            'round': record['round'],
            'q': text[:600],
            'results': record['results'],
            'seconds': record['seconds'],
            'category': category,
            'similarity': round(max_sim, 3),
            'related': related,
            'newTerms': new_terms,
        }
        counts[category] += 1
        cases_queries.append({**query, 'tokenSet': tokens})
        if key not in best_counts:
            best_counts[key] = 0
        best_counts[key] += 1
        seen_norm.add(key)
        seen_tokens |= tokens

    total = len(cases_queries)
    follow = max(0, total - 1)
    exact_near = counts['exact'] + counts['near']
    repeat_rate = exact_near / follow if follow else 0.0
    new_rate = counts['new'] / follow if follow else 0.0
    extend_rate = counts['extend'] / follow if follow else 0.0
    unique = len(best_counts)
    behaviour = behaviour_for(total, repeat_rate, new_rate, extend_rate)
    max_repeat = max(best_counts.values()) if best_counts else 1
    status = status_of(case)
    question = str(case.get('question') or '')
    topic = str(case.get('topic') or case.get('id') or '')
    return {
        'id': str(case.get('id') or ''),
        'index': case.get('index'),
        'topic': topic,
        'question': question[:700],
        'status': status,
        'inProgress': bool(case.get('inProgress')),
        'interrupted': bool(case.get('interrupted')),
        'rounds': int(case.get('rounds') or 0),
        'duration': round(float(case.get('durationSeconds') or 0), 1),
        'queryTotal': total,
        'unique': unique,
        'queryRounds': len({r['round'] for r in records}),
        'counts': counts,
        'followUps': follow,
        'repeatRate': round(repeat_rate, 4),
        'newRate': round(new_rate, 4),
        'extendRate': round(extend_rate, 4),
        'maxRepeat': max_repeat,
        'behavior': behaviour,
        'queries': [{k: v for k, v in q.items() if k != 'tokenSet'} for q in cases_queries],
    }


def main():
    manifest = json.loads((BASE / 'datasets' / 'index.json').read_text())
    runs = []
    for entry in manifest.get('datasets', []):
        if not entry.get('visible', True):
            continue
        data_path = BASE / (entry.get('data') or f"datasets/{entry.get('id')}/traces.json")
        if not data_path.is_file():
            print('MISSING', data_path, flush=True)
            continue
        print('READ', data_path, f'{data_path.stat().st_size/1e6:.1f}MB', flush=True)
        try:
            data = json.loads(data_path.read_text())
        except Exception as exc:
            print('SKIP', data_path, exc, flush=True)
            continue
        run_meta = data.get('run') or {}
        cases = []
        no_search = 0
        for case in data.get('cases') or []:
            processed = process_case(case, run_meta)
            if processed:
                cases.append(processed)
            else:
                no_search += 1
        if not cases:
            print('NO_CASES', entry.get('id'), flush=True)
            continue
        completed = [c for c in cases if c['status'] not in ('running', 'interrupted')]
        base_cases = completed or cases
        med = statistics.median([c['queryTotal'] for c in base_cases]) if base_cases else 0
        total_follow = sum(c['followUps'] for c in base_cases)
        repeat_total = sum(c['counts']['exact'] + c['counts']['near'] for c in base_cases)
        new_total = sum(c['counts']['new'] for c in base_cases)
        counts = {k: sum(c['counts'][k] for c in base_cases) for k in ('start', 'new', 'extend', 'near', 'exact')}
        behaviours = {k: sum(c['behavior'] == k for c in cases) for k in ('repeat', 'expand', 'mixed', 'single')}
        run = {
            'id': entry.get('id'),
            'label': entry.get('label') or entry.get('id'),
            'benchmark': entry.get('benchmark') or 'Unknown',
            'model': run_meta.get('model') or entry.get('label') or '',
            'inProgress': bool(run_meta.get('inProgress')) or entry.get('lifecycleOverride') == 'stopped',
            'caseCount': len(cases),
            'noSearchCount': no_search,
            'completedCount': len(completed),
            'stats': {
                'medianQueries': med,
                'repeatRate': round(repeat_total / total_follow, 4) if total_follow else 0,
                'newRate': round(new_total / total_follow, 4) if total_follow else 0,
                'counts': counts,
                'behaviours': behaviours,
            },
            'cases': cases,
        }
        runs.append(run)
        print('OK', run['id'], 'cases', len(cases), 'completed', len(completed), 'queries', sum(c['queryTotal'] for c in cases), flush=True)
    payload = {
        'generatedAt': dt.datetime.now(dt.timezone.utc).isoformat(),
        'thresholds': {'near': NEAR, 'extend': EXTEND},
        'runs': runs,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix('.tmp')
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')))
    tmp.replace(OUT)
    print('WROTE', OUT, f'{OUT.stat().st_size/1e6:.2f}MB', 'runs', len(runs), flush=True)


if __name__ == '__main__':
    main()
