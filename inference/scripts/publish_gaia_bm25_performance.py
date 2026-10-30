"""Publish comparable observed GAIA task, visit and selected-page latencies."""
import json,math,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'workspace/strict-reproduction'
OUT=ROOT/'web/trace-viewer/datasets/gaia-v3-bm25-performance.json'
NAMES=['gaia-bm25-5gpu-base-toolprompt-v3-20261029-r1','gaia-bm25-5gpu-base-v3-pool8-page2-20261029-r1']

def stats(values):
 a=sorted(x for x in values if isinstance(x,(int,float)) and math.isfinite(x) and x>=0)
 if not a:return {'count':0,'p50_s':None,'p95_s':None,'mean_s':None}
 return {'count':len(a),'p50_s':a[math.ceil(len(a)*.5)-1],'p95_s':a[math.ceil(len(a)*.95)-1],'mean_s':sum(a)/len(a)}

def group(root):
 rows=json.loads((root/'status.json').read_text())['cases']; task=[];visit=[];pages=[]; reasons={};calls=0;urls=0;multis=0
 for case,row in rows.items():
  if row.get('agent_state')=='terminal' and row.get('agent_returncode')==0 and row.get('judge_state')=='scored' and row.get('agent_started_epoch') and row.get('agent_ended_epoch'):
   task.append(row['agent_ended_epoch']-row['agent_started_epoch'])
  path=root/'logs'/f'{case}-agent-events.jsonl';starts={}
  if path.exists():
   for line in path.open():
    try:x=json.loads(line)
    except json.JSONDecodeError:continue
    if x.get('kind')=='tool' and x.get('event')=='span_start' and x.get('input',{}).get('tool_name')=='visit':
     sid=x.get('span_id'); starts[sid]=True;calls+=1;v=x.get('input',{}).get('tool_args',{}).get('url',[]); n=len(v) if isinstance(v,list) else int(bool(v));urls+=n;multis+=n>1
    if x.get('kind')=='tool' and x.get('event')=='span_end' and x.get('span_id') in starts:
     visit.append(x.get('seconds'))
  path=root/'logs'/f'{case}-retrieval.jsonl'
  if path.exists():
   for line in path.open():
    try:x=json.loads(line)
    except json.JSONDecodeError:continue
    reason=x.get('reason','unknown');reasons[reason]=reasons.get(reason,0)+1
    if reason=='selected' and isinstance(x.get('total_seconds'),(int,float)):pages.append(x['total_seconds'])
 return {'task':stats(task),'visit':stats(visit),'selected_page':stats(pages),'visit_calls_started':calls,'visit_urls_requested':urls,'multi_url_visits':multis,'page_reasons':reasons,'scored':sum(v.get('judge_state')=='scored' for v in rows.values()),'correct':sum(v.get('judge_state')=='scored' and v.get('is_correct') is True for v in rows.values()),'terminal':sum(v.get('agent_state')=='terminal' for v in rows.values()),'total':len(rows)}

def main():
 while True:
  try:
   groups={name:group(BASE/name) for name in NAMES}
   obj={'updated':time.time(),'groups':groups,'limitations':'Live web and independent sampling; selected-page excludes short pages and includes preparation/ranking/packing and pool IPC when used; visit includes Jina/network; no causal speedup claim from unpaired workloads.'}
   tmp=OUT.with_suffix('.tmp');tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n');tmp.replace(OUT)
   if all(v['terminal']==v['total'] for v in groups.values()):break
  except (OSError,ValueError,KeyError) as exc:print('performance metrics unavailable:',repr(exc),flush=True)
  time.sleep(60)
if __name__=='__main__':main()
