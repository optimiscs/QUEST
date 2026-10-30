"""Publish comparable tool-call metrics for the two GAIA32 base-model runs."""
import collections, json, os, re, time
from pathlib import Path
REPO=Path(__file__).resolve().parents[2]
BASE=REPO/'workspace/strict-reproduction'
DEST=Path(os.environ.get('QUEST_COMPARISON_OUTPUT',str(REPO/'web/trace-viewer/datasets/gaia-toolprompt-comparison.json')))
GROUPS={'original':os.environ.get('QUEST_COMPARISON_ORIGINAL','gaia-bm25-5gpu-base-20261029-r1'),'optimized':os.environ.get('QUEST_COMPARISON_OPTIMIZED','gaia-bm25-5gpu-base-toolprompt-v1-20261029-r1')}

def visible_calls(content):
    visible=content.rsplit('</think>',1)[-1].split('<think>',1)[0]
    visible=re.sub(r'```[^\n]*\n.*?```','',visible,flags=re.DOTALL)
    return re.findall(r'<tool_call>(.*?)</tool_call>',visible,re.DOTALL)

def summarize(root):
    rows=json.loads((root/'status.json').read_text())['cases']
    counts=collections.Counter(); statuses=collections.Counter()
    for case,row in rows.items():
        statuses[row['agent_state']]+=1
        if row.get('judge_state')=='scored':
            counts['scored']+=1; counts['correct']+=row.get('is_correct') is True
        path=root/'logs'/f'{case}-agent-events.jsonl'
        if not path.exists():continue
        for line in path.open():
            try:x=json.loads(line)
            except json.JSONDecodeError:continue
            if x.get('event')!='span_end':continue
            kind=x.get('kind')
            if kind=='policy_model' and isinstance(x.get('output'),str):
                calls=visible_calls(x['output'])
                # Main loop only executes the final visible call.
                if calls:
                    counts['attempts']+=1
                    raw=re.sub(r'<code>.*?</code>','',calls[-1],flags=re.DOTALL).strip()
                    try:
                        obj=json.loads(raw)
                        if isinstance(obj,dict) and isinstance(obj.get('name'),str) and isinstance(obj.get('arguments',{}),dict):counts['json_valid']+=1
                    except (ValueError,TypeError):pass
            elif kind=='tool':
                counts['dispatched']+=1
                output=str(x.get('output') or '')
                if output.lstrip().startswith(('[Tool Error]','[Visit Error]','[Search Error]','[Python Error]')):counts['explicit_tool_errors']+=1
                else:counts['returned_without_explicit_error']+=1
            elif kind in ('reader','search_query'):
                status=x.get('http_status')
                if isinstance(status,int):counts[kind+'_http_total']+=1;counts[kind+'_http_2xx']+=200<=status<300
    return {'run':root.name,'total':len(rows),'states':dict(statuses),'metrics':dict(counts),'cases':{k:{'judged':v.get('judge_state')=='scored','correct':v.get('is_correct')} for k,v in rows.items()}}

def main():
    while True:
        try:
            groups={k:summarize(BASE/v) for k,v in GROUPS.items()}
            paired=[(x,groups['optimized']['cases'][k]) for k,x in groups['original']['cases'].items() if x['judged'] and groups['optimized']['cases'][k]['judged']]
            out={'updated':time.time(),'groups':groups,'paired':{'count':len(paired),'optimized_only':sum(not a['correct'] and b['correct'] for a,b in paired),'original_only':sum(a['correct'] and not b['correct'] for a,b in paired),'both_correct':sum(a['correct'] and b['correct'] for a,b in paired),'both_wrong':sum(not a['correct'] and not b['correct'] for a,b in paired)}}
            tmp=DEST.with_suffix('.tmp');tmp.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');tmp.replace(DEST)
            if all(g['states'].get('terminal',0)==g['total'] for g in groups.values()):break
        except (OSError,ValueError,KeyError) as exc: print('metrics publication error',repr(exc),flush=True)
        time.sleep(30)
if __name__=='__main__':main()
