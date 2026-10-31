"""Publish BrowseComp run to the existing trace viewer."""
import json,subprocess,sys,time,os
from pathlib import Path
R=Path(__file__).resolve().parents[2];RUN=Path(os.environ.get('QUEST_BROWSE128_RUN',R/'workspace/strict-reproduction/browsecomp-27b-rerank64-16-128-20261029-r1'));SITE=R/'web/trace-viewer';ID=RUN.name;LABEL=os.environ.get('QUEST_BROWSE128_LABEL','BrowseComp 失败样本 128 · 27B · BM25+Embedding')
sys.path.insert(0,str(R));from inference.visible_judge_state import visible_judging_finished
while True:
 try:
  p=RUN/'status.json'
  if not p.exists():time.sleep(5);continue
  state=json.loads(p.read_text())['cases'];dest=SITE/'datasets'/ID
  result=subprocess.run([sys.executable,str(R/'web/build_gaia.py'),'--run-root',str(RUN),'--output-dir',str(dest),'--label',LABEL,'--benchmark','BrowseComp','--requested-cases',str(len(state)),'--include-running','--replace-existing'],capture_output=True,text=True,timeout=300)
  if result.returncode:print('build failed',result.stderr[-1000:],flush=True)
  elif (dest/'traces.json').exists():
   indexfile=SITE/'datasets/index.json';index=json.loads(indexfile.read_text())
   if not any(x.get('id')==ID for x in index['datasets']):
    method='原始网页 + 27B 摘要' if os.environ.get('QUEST_VISIT_MODE')=='original_summary' else os.environ.get('VISIT_EXPERIMENT_METHOD','bm25_embedding')
    index['datasets'].append({'id':ID,'label':LABEL,'description':f'{len(state)} 条 BrowseComp 样本；检索方式 {method}','folder':'datasets/'+ID,'data':'datasets/'+ID+'/traces.json','benchmark':'BrowseComp','visible':True})
    tmp=indexfile.with_suffix('.tmp');tmp.write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n');tmp.replace(indexfile)
  print('published terminal',sum(x['agent_state']=='terminal' for x in state.values()),'scored',sum(x['judge_state']=='scored' for x in state.values()),flush=True)
  if (all(x['agent_state']=='terminal' and x['judge_state'] not in ('pending','running') for x in state.values())):break
 except Exception as exc:print('publisher error',repr(exc),flush=True)
 time.sleep(60)
