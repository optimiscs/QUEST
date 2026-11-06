"""Publish live objective-508 trajectories without assigning unrun scores."""
import json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
RUN=Path(os.environ.get('QUEST_OBJECTIVE_VIEWER_RUN', ROOT/'workspace/strict-reproduction/quest-objective508-bm25-embedding4b-20261101-r2'))
SITE=ROOT/'web/trace-viewer';ID=RUN.name;LABEL=os.environ.get('QUEST_OBJECTIVE_VIEWER_LABEL','QUEST 客观题 508 · 27B · BM25+Embedding 4B')
while True:
 try:
  status=RUN/'status.json'
  if not status.exists():time.sleep(5);continue
  state=json.loads(status.read_text());dest=SITE/'datasets'/ID
  count=len(state['cases'])
  cmd=[sys.executable,str(ROOT/'web/build_gaia.py'),'--run-root',str(RUN),'--output-dir',str(dest),'--label',LABEL,'--benchmark','QUEST Objective','--requested-cases',str(count),'--include-running','--replace-existing']
  stop=RUN/'checks/user-stopped.json'
  if stop.exists():cmd.extend(['--stopped-at',str(json.loads(stop.read_text())['epoch'])])
  p=subprocess.run(cmd,capture_output=True,text=True,timeout=300)
  if p.returncode:print('build_error',p.stderr[-1500:],flush=True)
  elif (dest/'traces.json').exists():
   indexfile=SITE/'datasets/index.json';index=json.loads(indexfile.read_text())
   if not any(x.get('id')==ID for x in index.get('datasets',[])):
    index.setdefault('datasets',[]).append({'id':ID,'label':LABEL,'description':f'{count} 道 QUEST 客观候选；27B 联网研究，BM25 + 4B embedding；尚未运行原任务评分','folder':'datasets/'+ID,'data':'datasets/'+ID+'/traces.json','benchmark':'QUEST Objective','visible':True})
    tmp=indexfile.with_name(f'index.{os.getpid()}.tmp');tmp.write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n');tmp.replace(indexfile)
   print('published',state.get('counts'),p.stdout.strip(),flush=True)
 except Exception as exc:print('publisher_error',repr(exc),flush=True)
 time.sleep(30)
