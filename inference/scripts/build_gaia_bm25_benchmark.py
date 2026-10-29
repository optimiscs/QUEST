"""Freeze real GAIA visits and Reader responses for reproducible benchmarks."""
import collections
import glob
import hashlib
import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RUN = REPO/'workspace/strict-reproduction/gaia-retrieval-ab-20261029-r1'
OUT = RUN/'checks/bm25-concurrency'


def lines(path):
    with open(path, encoding='utf-8') as handle:
        for line in handle:
            try: yield json.loads(line)
            except ValueError: continue


def normalize_goal(goal):
    if isinstance(goal, list):
        return '; '.join(str(x) for x in goal if x is not None)
    return goal if isinstance(goal, str) else ''


def build():
    choices = collections.defaultdict(list)
    audits = sorted(glob.glob(str(RUN/'*-direct/logs/row*-retrieval.jsonl')))
    audits += sorted(glob.glob(str(RUN/'retries/*-direct/**/logs/row*-retrieval.jsonl'),recursive=True))
    for audit in audits:
        audit = Path(audit)
        case = audit.name.split('-')[0]
        events = audit.with_name(f'{case}-agent-events.jsonl')
        records = {}
        for row in lines(audit):
            goal = normalize_goal(row.get('goal'))
            url, text = row.get('url'), row.get('original_content')
            if goal and isinstance(url,str) and url and isinstance(text,str) and text and not text.startswith('[visit] Error'):
                records.setdefault((goal,url),text)
        if not records: continue
        if events.exists():
            for event in lines(events):
                inp = event.get('input') or {}
                if event.get('event') != 'span_start' or event.get('kind') != 'tool' or inp.get('tool_name') != 'visit': continue
                args = inp.get('tool_args') or {}
                if not isinstance(args,dict): continue
                goal = normalize_goal(args.get('goal'))
                urls = args.get('url')
                urls = [urls] if isinstance(urls,str) else urls if isinstance(urls,list) else []
                pages = []
                for url in urls:
                    text = records.get((goal,url)) if isinstance(url,str) else None
                    if text and not any(x['url']==url for x in pages): pages.append({'url':url,'text':text})
                if pages:
                    choices[case].append({'case':case,'goal':goal,'pages':pages[:4],
                                          'source':str(audit.relative_to(RUN)),'batch':'recorded_visit'})
        # A valid Reader snapshot remains useful even if its original event is absent.
        for (goal,url),text in records.items():
            choices[case].append({'case':case,'goal':goal,'pages':[{'url':url,'text':text}],
                                  'source':str(audit.relative_to(RUN)),'batch':'single_snapshot'})
    historic = REPO/'workspace/strict-reproduction/gaia-sft32-27b-summary-20261028-r1/logs/row0023-agent-events.jsonl'
    if historic.exists():
        events = list(lines(historic));starts={e['span_id']:e for e in events if e.get('event')=='span_start'}
        for event in events:
            if event.get('event')!='span_end' or event.get('kind')!='reader':continue
            start=starts.get(event.get('span_id'),{});parent=starts.get(start.get('parent_id'),{})
            goal=normalize_goal(((parent.get('input') or {}).get('tool_args') or {}).get('goal'))
            url=(start.get('input') or {}).get('url');text=event.get('output')
            if goal and isinstance(url,str) and isinstance(text,str) and text and not text.startswith('[visit] Error'):
                choices['row0023'].append({'case':'row0023','goal':goal,'pages':[{'url':url,'text':text}],
                                            'source':str(historic.relative_to(REPO)),'batch':'recorded_visit'})
    selected=[]
    for i in range(32):
        case=f'row{i:04d}'
        if not choices[case]: continue
        # Prefer a genuine multi-URL visit, then the first deterministically read snapshot.
        selected.append(max(choices[case],key=lambda x:(len(x['pages']),x['batch']=='recorded_visit')))
    OUT.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(OUT,0o700)
    path=OUT/'gaia32-recorded-pages.jsonl'
    with path.open('w',encoding='utf-8') as handle:
        for row in selected: handle.write(json.dumps(row,ensure_ascii=False)+'\n')
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    missing=[f'row{i:04d}' for i in range(32) if f'row{i:04d}' not in {x['case'] for x in selected}]
    meta={'cases':len(selected),'pages':sum(len(x['pages']) for x in selected),
          'multi_url_visits':sum(len(x['pages'])>1 for x in selected),'missing':missing,'sha256':digest,
          'scope':'recorded visit goal and page text; network fetch is not benchmarked'}
    (OUT/'dataset-meta.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
    return meta


if __name__=='__main__': print(json.dumps(build(),ensure_ascii=False))
