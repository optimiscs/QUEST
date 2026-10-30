"""Continuously record new BrowseComp bad cases and tool failures."""
import collections,fcntl,json,os,re,time
from pathlib import Path
R=Path(__file__).resolve().parents[2]/'workspace/strict-reproduction/browsecomp-sft-25pct-pool64-20261029-r1';O=R/'checks';O.mkdir(parents=True,exist_ok=True)
PATTERNS={'invalid_tool_json':r'Invalid tool call format','tool_json_repaired':r'\[Tool JSON repair\] appended','context_overflow':r'maximum context length is 65536|context_length_exceeded','reader_key_exhausted':r'All Jina keys are exhausted or invalid','bm25_error':r'\[visit\] Error:.*(?:18215|BM25 pool|/prepare)','sandbox_timeout':r'Python Interpreter Error.*Timeout|sandbox.*Read timed out','memory_parse_failure':r'Failed to parse state|Failed to parse JSON from memory'}
compiled={k:re.compile(v,re.I) for k,v in PATTERNS.items()};seen={}; offsets={};event_offsets={}
with (O/'live-monitor.lock').open('a+') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 while True:
  counts=collections.Counter();cases=collections.defaultdict(list)
  for p in (R/'logs').glob('row*-agent.stdout.log'):
   case=p.name.split('-')[0]
   try:
    with p.open(errors='replace') as f:
     f.seek(offsets.get(case,0));lines=f.readlines();offsets[case]=f.tell()
   except OSError:continue
   for line in lines:
    for k,pat in compiled.items():
     if pat.search(line):counts[k]+=1;cases[k].append(case)
  for p in (R/'logs').glob('row*-agent-events.jsonl'):
   case=p.name.split('-')[0]
   try:
    with p.open(errors='replace') as f:
     f.seek(event_offsets.get(case,0))
     while True:
      start=f.tell();line=f.readline()
      if not line:break
      if not line.endswith('\n'):f.seek(start);break
      try:event=json.loads(line)
      except ValueError:continue
      if event.get('event')!='span_end' or event.get('kind')!='policy_model' or not isinstance(event.get('output'),str):continue
      text=event['output'].rsplit('</think>',1)[-1].split('<think>',1)[0]
      text=re.sub(r'```[^\n]*\n.*?```','',text,flags=re.S)
      calls=re.findall(r'<tool_call>(.*?)</tool_call>',text,re.S)
      if not calls:continue
      raw=re.sub(r'<code>.*?</code>','',calls[-1],flags=re.S).strip()
      try:json.loads(raw)
      except ValueError:counts['invalid_tool_json_event']+=1;cases['invalid_tool_json_event'].append(case)
     event_offsets[case]=f.tell()
   except OSError:continue
  for k,v in counts.items():seen[k]=seen.get(k,0)+v
  item={'epoch':time.time(),'new_counts':dict(counts),'total_counts':seen,'affected_cases':{k:sorted(set(v)) for k,v in cases.items()}}
  with (O/'live-monitor.jsonl').open('a') as out:out.write(json.dumps(item,ensure_ascii=False)+'\n')
  p=R/'status.json'
  if p.exists():
   rows=json.loads(p.read_text())['cases']
   if all(v['agent_state']=='terminal' and v['judge_state'] not in ('pending','running') for v in rows.values()):break
  time.sleep(60)
