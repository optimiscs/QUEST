"""Publish BrowseComp run to the existing trace viewer."""
import json,subprocess,sys,time,os
from pathlib import Path
R=Path(__file__).resolve().parents[2];RUN=Path(os.environ.get('QUEST_BROWSE128_RUN',R/'workspace/strict-reproduction/browsecomp-27b-rerank64-16-128-20261029-r1'));SITE=R/'web/trace-viewer';ID=RUN.name
sys.path.insert(0,str(R));from inference.visible_judge_state import visible_judging_finished
while True:
 try:
  p=RUN/'status.json'
  if not p.exists():time.sleep(5);continue
  state=json.loads(p.read_text())['cases'];dest=SITE/'datasets'/ID
  result=subprocess.run([sys.executable,str(R/'web/build_gaia.py'),'--run-root',str(RUN),'--output-dir',str(dest),'--label','BrowseComp 失败样本 128 · 27B · BM25+Reranker','--benchmark','BrowseComp','--requested-cases','128','--include-running','--replace-existing'],capture_output=True,text=True,timeout=300)
  if result.returncode:print('build failed',result.stderr[-1000:],flush=True)
  elif (dest/'traces.json').exists():
   indexfile=SITE/'datasets/index.json';index=json.loads(indexfile.read_text())
   if not any(x.get('id')==ID for x in index['datasets']):
    index['datasets'].append({'id':ID,'label':'BrowseComp 失败样本 128 · 27B · BM25+Reranker','description':'128 条 4B 失败样本；27B 记忆和裁判；BM25 Top64 + Reranker Top16','folder':'datasets/'+ID,'data':'datasets/'+ID+'/traces.json','benchmark':'BrowseComp','visible':True})
    tmp=indexfile.with_suffix('.tmp');tmp.write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n');tmp.replace(indexfile)
  print('published terminal',sum(x['agent_state']=='terminal' for x in state.values()),'scored',sum(x['judge_state']=='scored' for x in state.values()),flush=True)
  if (all(x['agent_state']=='terminal' and x['judge_state'] not in ('pending','running') for x in state.values())):break
 except Exception as exc:print('publisher error',repr(exc),flush=True)
 time.sleep(60)
