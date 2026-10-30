"""Record 1-minute vLLM preemption deltas while the scheduler drains."""
import collections,json,os,time,requests
from pathlib import Path
run=Path(os.environ['QUEST_BROWSE128_RUN']);ports=[int(x) for x in os.environ['QUEST_BROWSE128_PORTS'].split(',')];session=requests.Session();session.trust_env=False
keys=['num_preemptions_total','num_requests_running','num_requests_waiting','kv_cache_usage_perc','generation_tokens_total']
def sample():
 now=time.time();rows=json.loads((run/'status.json').read_text())['cases'];gpus=collections.Counter(str(v.get('gpu')) for v in rows.values() if v.get('agent_state')=='running');out={}
 for p in ports:
  d={}
  for line in session.get(f'http://127.0.0.1:{p}/metrics',timeout=5).text.splitlines():
   for k in keys:
    if line.startswith(f'vllm:{k}{{'):d[k]=float(line.rsplit(' ',1)[1])
  out[str(p)]=d
 return {'epoch':now,'agent_counts':dict(gpus),'metrics':out}
previous=sample()
for _ in range(10):
 time.sleep(60)
 try:
  current=sample();dt=current['epoch']-previous['epoch']
  for p in map(str,ports):
   a=previous['metrics'][p];b=current['metrics'][p];b['preemptions_per_min']=(b['num_preemptions_total']-a['num_preemptions_total'])*60/dt;b['output_tokens_per_second']=(b['generation_tokens_total']-a['generation_tokens_total'])/dt
  with (run/'checks/preemption-after-limit4.jsonl').open('a') as f:f.write(json.dumps(current)+'\n')
  previous=current
 except Exception as e:
  with (run/'checks/preemption-after-limit4.jsonl').open('a') as f:f.write(json.dumps({'epoch':time.time(),'error':type(e).__name__})+'\n')
