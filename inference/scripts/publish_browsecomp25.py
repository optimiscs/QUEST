"""Publish BrowseComp run to the existing trace viewer."""
import json,subprocess,sys,time
from pathlib import Path
R=Path(__file__).resolve().parents[2];RUN=R/'workspace/strict-reproduction/browsecomp-sft-25pct-pool64-20261029-r1';SITE=R/'web/trace-viewer';ID=RUN.name
while True:
 try:
  p=RUN/'status.json'
  if not p.exists():time.sleep(5);continue
  state=json.loads(p.read_text())['cases'];dest=SITE/'datasets'/ID
  result=subprocess.run([sys.executable,str(R/'web/build_gaia.py'),'--run-root',str(RUN),'--output-dir',str(dest),'--label','BrowseComp 25% · 4B SFT · BM25 64','--benchmark','BrowseComp','--requested-cases','317','--include-running','--replace-existing'],capture_output=True,text=True,timeout=300)
  if result.returncode:print('build failed',result.stderr[-1000:],flush=True)
  elif (dest/'traces.json').exists():
   indexfile=SITE/'datasets/index.json';index=json.loads(indexfile.read_text())
   if not any(x.get('id')==ID for x in index['datasets']):
    index['datasets'].append({'id':ID,'label':'BrowseComp 25% · 4B SFT · BM25 64','description':'317 条；本地 4B 记忆与官方提示词本地 4B 评分','folder':'datasets/'+ID,'data':'datasets/'+ID+'/traces.json','benchmark':'BrowseComp','visible':True})
    tmp=indexfile.with_suffix('.tmp');tmp.write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n');tmp.replace(indexfile)
  print('published terminal',sum(x['agent_state']=='terminal' for x in state.values()),'scored',sum(x['judge_state']=='scored' for x in state.values()),flush=True)
  if (all(x['agent_state']=='terminal' and x['judge_state'] not in ('pending','running') for x in state.values()) and (RUN/'checks/judge-recovery-complete.json').exists() and (RUN/'checks/final-answer-recovery-complete.json').exists()):break
 except Exception as exc:print('publisher error',repr(exc),flush=True)
 time.sleep(60)
