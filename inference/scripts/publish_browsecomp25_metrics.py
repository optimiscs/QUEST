"""Incremental metrics for the BrowseComp experiment, keeping anomalies visible."""
import collections,json,math,re,sys,time
from pathlib import Path
R=Path(__file__).resolve().parents[2];RUN=R/'workspace/strict-reproduction/browsecomp-sft-25pct-pool64-20261029-r1';OUT=R/'web/trace-viewer/datasets/browsecomp-sft-25pct-pool64-20261029-r1-metrics.json'
sys.path.insert(0,str(R));from inference.visible_judge_state import apply_visible_judgment,visible_judging_finished
def stats(xs):
 xs=sorted(x for x in xs if isinstance(x,(int,float)) and math.isfinite(x) and x>=0)
 return {'n':len(xs),'mean':sum(xs)/len(xs) if xs else None,'p50':xs[math.ceil(.5*len(xs))-1] if xs else None,'p95':xs[math.ceil(.95*len(xs))-1] if xs else None}
def explicit_tool_error(output, tool_name):
 s=str(output or '')
 if s.lstrip().startswith(('[Tool Error]','[Visit Error]','[Search Error]','[Python Error]')):return True
 # Batched search joins per-query results with blank lines, so an error may
 # follow an earlier successful query rather than appearing at the beginning.
 return tool_name=='search' and bool(re.search(r'(?:^|\n\n)\[Search Error\]',s))
def calc():
 rows=json.loads((RUN/'status.json').read_text())['cases'];c=collections.Counter();times=collections.defaultdict(list);states=collections.Counter();phases=collections.defaultdict(collections.Counter)
 for case,row in rows.items():
  final_path=RUN/'checks'/f'{case}-final-answer-recovery.json'
  if row.get('agent_state')=='terminal' and final_path.exists():
   try:
    recovery=json.loads(final_path.read_text())
    if recovery.get('status')=='scored' and isinstance(recovery.get('is_correct'),bool):row=dict(row,judge_state='scored',is_correct=recovery['is_correct'],result_path=recovery['recovery_result_path']);c['final_answer_recovered']+=1
   except (OSError,ValueError):pass
  retry_path=RUN/'checks'/f'{case}-local-judge-retry.json'
  if retry_path.exists():
   try:
    retry=json.loads(retry_path.read_text())
    if retry.get('status')=='scored' and isinstance(retry.get('is_correct'),bool):
     c['judge_recovered']+=1
     if row.get('judge_state')=='unavailable':row=dict(row,judge_state='scored',is_correct=retry['is_correct'])
   except (OSError,ValueError):pass
  if row.get('judge_state')=='scored':c['legacy_scored']+=1;c['legacy_correct']+=row.get('is_correct') is True
  row,visible_receipt=apply_visible_judgment(RUN,case,row)
  if visible_receipt:c['visible_judge_receipts']+=1
  states[row.get('agent_state')]+=1;states['judge_'+row.get('judge_state','unknown')]+=1
  if row.get('judge_state')=='scored':c['scored']+=1;c['correct']+=row.get('is_correct') is True
  if row.get('agent_returncode')==0 and row.get('judge_state')=='scored' and row.get('agent_ended_epoch') and row.get('agent_started_epoch'):times['task'].append(row['agent_ended_epoch']-row['agent_started_epoch'])
  log=RUN/'logs'/f'{case}-agent.stdout.log'
  phase='marker_not_recorded'
  if log.exists():
   s=log.read_text(errors='replace');enabled='optional conservative closure repair enabled' in s;phase='repair_marker_enabled' if enabled else 'marker_not_recorded';c['repair_enabled_cases']+=enabled
   array_enabled='optional single array bracket repair enabled' in s;c['array_bracket_repair_enabled_cases']+=array_enabled
   brace_repairs=s.count('[Tool JSON repair] appended');array_repairs=s.count('[Tool JSON repair] inserted one missing array bracket');repairs=brace_repairs+array_repairs
   c['repair_actions']+=repairs;c['repair_brace_actions']+=brace_repairs;c['repair_array_bracket_actions']+=array_repairs;phases[phase]['cases']+=1;phases[phase]['repair_actions']+=repairs
   c['memory_json_retries']+=s.count('[Memory] Invalid JSON; retrying once');c['memory_json_retry_success']+=s.count('[Memory] JSON retry produced a parseable state');c['final_answer_retries']+=s.count('[Final answer] Retrying final-answer format')
  p=RUN/'logs'/f'{case}-agent-events.jsonl'; starts={}
  if p.exists():
   for line in p.open():
    try:x=json.loads(line)
    except ValueError:continue
    event,kind=x.get('event'),x.get('kind')
    if event=='span_start' and kind=='tool':starts[x.get('span_id')]=x.get('input',{}).get('tool_name')
    if event!='span_end':continue
    if kind=='policy_model' and isinstance(x.get('output'),str):
     s=x['output'].rsplit('</think>',1)[-1].split('<think>',1)[0];s=re.sub(r'```[^\n]*\n.*?```','',s,flags=re.S);a=re.findall(r'<tool_call>(.*?)</tool_call>',s,re.S)
     if a:
      c['tool_attempts']+=1;phases[phase]['attempts']+=1;raw=re.sub(r'<code>.*?</code>','',a[-1],flags=re.S).strip()
      try:
       o=json.loads(raw);valid=isinstance(o,dict) and isinstance(o.get('name'),str) and isinstance(o.get('arguments',{}),dict);c['json_valid']+=valid;phases[phase]['json_valid']+=valid
      except (ValueError,TypeError):pass
    elif kind=='tool':
     c['tool_returned']+=1;out=str(x.get('output') or '');c['tool_explicit_errors']+=explicit_tool_error(out,starts.get(x.get('span_id')))
     if starts.get(x.get('span_id'))=='visit':times['visit'].append(x.get('seconds'))
    elif kind in ('summary','memory_api','automatic_memory'):
     c[kind+'_calls']+=1
     if kind in ('summary','memory_api'):times[kind].append(x.get('seconds'))
    elif kind in ('reader','search_query') and isinstance(x.get('http_status'),int):c[kind+'_http_total']+=1;c[kind+'_http_2xx']+=200<=x['http_status']<300
  p=RUN/'logs'/f'{case}-retrieval.jsonl'
  if p.exists():
   for line in p.open():
    try:x=json.loads(line)
    except ValueError:continue
    c['page_'+x.get('reason','unknown')]+=1
    if x.get('reason')=='selected':times['bm25_selected_page'].append(x.get('total_seconds'))
 rotation_log=R/'workspace/logs/key-rotation/events.jsonl';pids={v.get('agent_pid') for v in rows.values() if v.get('agent_pid')}
 if rotation_log.exists():
  for line in rotation_log.open():
   try:x=json.loads(line)
   except ValueError:continue
   if x.get('pid') in pids and x.get('event')=='temporary_rate_limit_retry':c['serper_temporary_rate_limit_retries']+=1
 queue=RUN/'checks/judge-review-queue.json'
 if queue.exists():
  try:
   audit=json.loads(queue.read_text());c['judge_review_flagged']=len(audit.get('cases',[]));c['judge_review_unresolved']=audit.get('unresolved',audit.get('unreviewed',0))
  except (OSError,ValueError):pass
 diagnostics=RUN/'checks/judge-equivalence-diagnostics.json'
 if diagnostics.exists():
  try:
   for item in json.loads(diagnostics.read_text()).get('cases',[]):
    if item.get('finish_reason')!='stop':continue
    if not isinstance(item.get('is_correct'),bool):continue
    original=RUN/'checks'/f"{item['case']}-local-judge.json"
    if original.exists():
     verdict=json.loads(original.read_text()).get('is_correct')
     if isinstance(verdict,bool):c['judge_diagnostic_compared']+=1;c['judge_diagnostic_disagreements']+=verdict!=item['is_correct']
  except (OSError,ValueError,KeyError):pass
 return {'epoch':time.time(),'total':len(rows),'states':dict(states),'counts':dict(c),'repair_phases':{k:dict(v) for k,v in phases.items()},'timings':{k:stats(v) for k,v in times.items()},'labels':{'judge':'本地 Qwen3.5 4B 基座，官方 BrowseComp 判分提示','prompt':'Qwen3.5 4B SFT + portable_v3','tool_success':'未发现已识别的外层错误或批量搜索错误，不保证结果有用','repair':'按启动标记分组；未记录标记不一定代表修复未启用，组间不是随机对照'}}

def main():
 while True:
  try:
   x=calc();tmp=OUT.with_suffix('.tmp');tmp.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n');tmp.replace(OUT);print('scored',x['counts'].get('scored',0),'running',x['states'].get('running',0),flush=True)
   if x['states'].get('terminal',0)==x['total'] and not x['states'].get('judge_pending',0) and not x['states'].get('judge_running',0) and (RUN/'checks/judge-recovery-complete.json').exists() and (RUN/'checks/final-answer-recovery-complete.json').exists() and visible_judging_finished(RUN):break
  except (OSError,ValueError,KeyError) as e:print('metrics error',repr(e),flush=True)
  time.sleep(60)


if __name__ == "__main__": main()
