"""Audit actual model requests and tool delivery from the 16-case run."""
import collections
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'training_scripts/sft'))
from inference.source_ids import URL_PATTERN
from clean_harness_trajectories import dump,sha
from summary_events import read_events


def main():
    run=Path(sys.argv[1]).resolve()
    samples=[json.loads(s) for s in (run/'sample16-aligned-v2.jsonl').read_text().splitlines()]
    reports=[]
    for row in samples:
        case=row['metadata']['case'];file=run/'logs'/(case+'-agent-events.jsonl')
        events,provenance=read_events(run,case)
        counts=collections.Counter();errors=[]
        for event in events:
            if event.get('event')!='span_end':continue
            kind=event.get('kind');counts[kind]+=1
            if kind=='policy_model':
                context=event.get('api_request_context')
                if context:
                    counts['recorded_policy_contexts']+=1
                    if sha(context.get('tools'))!=sha(row['tools']):errors.append('tool_schema_mismatch')
                    if URL_PATTERN.search(json.dumps(context,ensure_ascii=False)):errors.append('full_url_in_policy_context')
                    for m in context.get('messages',[]):
                        if m.get('role')=='assistant':
                            if m.get('reasoning_content')!=m.get('reasoning'):errors.append('reasoning_transport_mismatch')
                            if m.get('content','').lstrip().startswith('<think>'):errors.append('literal_think_wrapper_in_content')
            if kind=='tool' and str(event.get('output','')).startswith('[Tool Error]'):
                counts['tool_errors']+=1
        results=list((run/'results'/case).rglob('iter1.jsonl'))
        result=json.loads(results[0].read_text().splitlines()[-1]) if results else {}
        prediction=result.get('prediction','')
        maps=list((run/'traces'/case).rglob('sources.json'))
        sources=json.loads(maps[0].read_text()) if maps else {}
        unknown=sorted(set(re.findall(r'(?<!\w)S[1-9][0-9]*(?!\w)',prediction))-sources.keys())
        console=(run/'logs'/(case+'-console.log')).read_text()
        reports.append({'case':case,'event_provenance':provenance,
                        'memory_parse_warnings':console.count('Failed to parse state from condenser result'),
                        'memory_updates':console.count('State updated successfully from direct condenser call'),
                        'process_done':any(e.get('event')=='process_done' for e in events),
                        'nonempty_answer':bool(prediction) and 'answer not found' not in prediction.lower(),
                        'num_rounds':result.get('num_rounds'),'counts':dict(counts),
                        'context_protocol_errors':dict(collections.Counter(errors)),
                        'unknown_final_source_ids':unknown,'final_contains_full_url':bool(URL_PATTERN.search(prediction))})
    dump(run/'runtime-audit.json',{'cases':reports,'all_processes_done':all(r['process_done'] for r in reports),
        'nonempty_answers':sum(r['nonempty_answer'] for r in reports),
        'all_recorded_contexts_aligned':all(not r['context_protocol_errors'] and r['counts'].get('recorded_policy_contexts',0)>0 for r in reports),
        'all_final_sources_valid':all(not r['unknown_final_source_ids'] and not r['final_contains_full_url'] for r in reports)})


if __name__=='__main__':main()
