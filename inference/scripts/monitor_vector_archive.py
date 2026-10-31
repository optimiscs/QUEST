"""Observational counters; hit/URL reuse are proxies, not relevance labels."""
import json
import os
import re
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

RUN = Path(os.environ['QUEST_BROWSE128_RUN'])

def canonical_url(raw):
    try:
        p = urlsplit(raw)
        return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip('/'), p.query, ''))
    except (TypeError, ValueError):
        return ''

def report():
    total = Counter()
    scores = []
    cases = []
    for file in (RUN/'traces').rglob('vector-audit.jsonl'):
        count = Counter(); queries = set(); old_urls = set(); recalled_urls = set()
        for line in file.read_text(errors='replace').splitlines():
            try: e = json.loads(line)
            except ValueError: continue
            event = e.get('event'); count[event] += 1
            if event == 'archived':
                count['archived_'+str(e.get('tool'))] += 1
                count['archived_chars_saved'] += e.get('original_chars', 0)-e.get('retained_chars', 0)
            elif event == 'local_search':
                q = re.sub(r'\s+', ' ', str(e.get('query','')).strip().casefold())
                if q in queries: count['repeated_exact_queries'] += 1
                queries.add(q)
                hits = e.get('hits') or []
                if hits: count['local_queries_with_hits'] += 1
                count['local_hits'] += len(hits)
                for hit in hits:
                    if isinstance(hit.get('score'), (float,int)): scores.append(hit['score'])
                    u = canonical_url(hit.get('url',''))
                    if u: recalled_urls.add(u)
            elif event == 'external_search':
                for entry in e.get('entries', []):
                    u = canonical_url(entry.get('url',''))
                    if not u: continue
                    count['external_url_results'] += 1
                    if u in old_urls: count['repeat_external_urls'] += 1
                    old_urls.add(u)
            elif event == 'visit':
                urls = e.get('urls') or []
                if isinstance(urls,str): urls = [urls]
                for raw in urls:
                    u = canonical_url(raw)
                    if u and u in recalled_urls: count['visits_to_previously_recalled_url'] += 1
        total.update(count)
        cases.append({'trace':str(file.parent.relative_to(RUN)), 'counters':dict(count)})
    out = {'epoch':time.time(), 'cases_with_audit':len(cases), 'counters':dict(total),
           'mean_local_similarity':sum(scores)/len(scores) if scores else None,
           'note':'Exact repeated queries, URL overlap and similarity are proxies, not proof of relevance or memory loss.',
           'cases':cases}
    dest=RUN/'checks/vector-monitor.json';tmp=dest.with_suffix('.tmp')
    tmp.write_text(json.dumps(out,ensure_ascii=False,indent=2));tmp.replace(dest)
    return out

while True:
    info=report()
    print(json.dumps({'epoch':info['epoch'],'cases':info['cases_with_audit'],'counters':info['counters']}),flush=True)
    state=RUN/'status.json'
    if state.exists():
        data=json.loads(state.read_text())['cases']
        if data and all(v['agent_state']=='terminal' and v['judge_state'] not in ('pending','running') for v in data.values()): break
    time.sleep(30)
