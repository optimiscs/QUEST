"""Resume paused experiment processes only after KV-offloaded services work."""
import json,os,signal,time,requests
from pathlib import Path
R=Path(__file__).resolve().parents[2];run=R/'workspace/strict-reproduction/browsecomp-27b-mtp3-low-128-r1';saved=json.loads((run/'checks/offload-restart-paused.json').read_text());s=requests.Session();s.trust_env=False;deadline=time.monotonic()+1800
for p in (19000,19001,19002):
 while time.monotonic()<deadline:
  try:
   data={'model':'QWEN38-27B-NVFP4','messages':[{'role':'user','content':'Reply OK.'}],'max_tokens':24,'temperature':0.7,'chat_template_kwargs':{'enable_thinking':False}}
   r=s.post(f'http://127.0.0.1:{p}/v1/chat/completions',json=data,timeout=90);r.raise_for_status();assert r.json()['choices'][0]['message'].get('content');print('generation OK',p,flush=True);break
  except Exception as e:print('waiting',p,type(e).__name__,str(e)[:100],flush=True);time.sleep(10)
 else:raise SystemExit(f'preflight timeout on {p}; agents remain paused')
while time.monotonic()<deadline:
 try:
  s.get('http://127.0.0.1:18314/health',timeout=5).raise_for_status();break
 except requests.RequestException:time.sleep(5)
else:raise SystemExit('reranker not healthy; agents remain paused')
for pid in saved['agents']:
 try:os.kill(pid,signal.SIGCONT)
 except ProcessLookupError:print('agent exited',pid,flush=True)
os.kill(saved['controller'],signal.SIGCONT)
(run/'checks/offload-resumed.json').write_text(json.dumps({'epoch':time.time(),'cpu_cache_gib_per_server':48,'paused_pids':saved['agents']},indent=2));print('agents and controller resumed',flush=True)
