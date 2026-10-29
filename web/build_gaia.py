"""Build an atomically replaceable viewer dataset from completed native spans."""
import argparse,collections,datetime,json,os,re,time
from pathlib import Path
from urllib.parse import urlparse

REPO=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description='Build a fresh viewer dataset from recorded GAIA spans; does not run inference or scoring.')
parser.add_argument('--run-root',type=Path,required=True)
parser.add_argument('--output-dir',type=Path,required=True)
parser.add_argument('--label',required=True)
parser.add_argument('--requested-cases',type=int,default=32)
parser.add_argument('--include-running',action='store_true')
parser.add_argument('--stopped-at',type=float,help='UTC epoch upper bound for a stopped run; partial durations end at the last recorded event')
parser.add_argument('--replace-existing',action='store_true',help='Atomically replace an existing viewer output')
cli=parser.parse_args()
if cli.requested_cases < 1:parser.error('--requested-cases must be positive')
root=cli.run_root.resolve(strict=True);dest=cli.output_dir.resolve();label=cli.label
out=dest/'traces.json'
if out.exists() and not cli.replace_existing:raise FileExistsError('viewer output exists; specify a fresh directory or --replace-existing')
def result_path(raw):
 p=Path(raw)
 if p.exists():return p.resolve()
 # Historical status files are retained byte-for-byte; map the old project prefix on read only.
 for prefix in ('/root/autodl-tmp/Quest/quest4b-gaia-20261027','/root/autodl-tmp/quest4b-gaia-20261027'):
  if raw.startswith(prefix+'/'):
   candidate=REPO/'workspace'/raw[len(prefix)+1:]
   if candidate.is_file():return candidate
 raise FileNotFoundError('Native result path not found: '+raw)
status_path=root/'status.json'
if not status_path.exists(): raise SystemExit(0)
status=json.loads(status_path.read_text());cases=[]
audit_path=root/'checks/audit-latest.json'
audit_rows={x['case']:x for x in json.loads(audit_path.read_text()).get('rows',[])} if audit_path.exists() else {}
def norm_gt(value): return re.sub(r'\s+',' ',str(value or '')).strip().casefold()
gt_path=root/'judge/ground-truth/gaia-103-org.json'
gt_rows={}
if gt_path.exists():
 for row in json.loads(gt_path.read_text()):
  q=norm_gt(row.get('Question',''))
  if q:gt_rows[q]=row
def read_events(path):
 rows=[]
 if path.exists():
  for line in path.open():
   try:rows.append(json.loads(line))
   except json.JSONDecodeError:pass
 return rows
def txt(v):return v if isinstance(v,str) else json.dumps(v,ensure_ascii=False,default=str)
for i in range(cli.requested_cases):
 case=f'row{i:04d}';state=status['cases'].get(case,{})
 events=read_events(root/'logs'/f'{case}-agent-events.jsonl')
 starts={x['span_id']:x for x in events if x.get('event')=='span_start'};ends={x['span_id']:x for x in events if x.get('event')=='span_end'}
 if state.get('agent_state')=='terminal' and state.get('result_path'):
  native=json.loads(result_path(state['result_path']).read_text().splitlines()[-1])
 elif state.get('agent_state')=='running' and cli.include_running:
  start=next((e for e in starts.values() if e.get('kind')=='task'),None)
  if not start: continue
  if cli.stopped_at is not None:
   # The task was paused before termination: do not count the pause as execution.
   # A partial trace has no authoritative task-end timestamp; show its recorded window.
   observed_epochs=[event.get('epoch') for event in events if isinstance(event.get('epoch'),(int,float))]
   observed_until=min(cli.stopped_at,max(observed_epochs,default=start['epoch']))
  else:
   observed_until=time.time()
  ends.setdefault(start['span_id'],{'epoch':observed_until,'seconds':max(0,observed_until-start['epoch'])})
  native={'question':start.get('input',{}).get('question',''),'prediction':'','messages':[],'num_rounds':sum(e.get('kind')=='policy_model' and sid in ends for sid,e in starts.items())}
 else: continue
 pairs=[(v,ends[k]) for k,v in starts.items() if k in ends];pairs.sort(key=lambda x:x[0]['epoch'])
 task=next(((s,e) for s,e in pairs if s['kind']=='task'),None)
 if not task:continue
 origin=task[0]['epoch'];duration=task[1]['seconds'];stats=collections.Counter();timing=collections.Counter()
 for s,e in pairs:stats[s['kind']]+=1;timing[s['kind']]+=e.get('seconds',0)
 policies=[(s,e) for s,e in pairs if s['kind']=='policy_model'];tools=[(s,e) for s,e in pairs if s['kind']=='tool'];steps=[];domains=collections.Counter();sources=set()
 for j,(s,e) in enumerate(policies):
  next_epoch=policies[j+1][0]['epoch'] if j+1<len(policies) else float('inf');tool=next(((a,b) for a,b in tools if e['epoch']<=a['epoch']<next_epoch),None)
  mstart=max(0,s['epoch']-origin);msec=e.get('seconds',0);step={'n':j+1,'kind':'answer','label':'回答','thought':txt(e.get('output','')),'model_seconds':msec,'tool_seconds':0,'modelStart':mstart,'modelEnd':mstart+msec,'toolStart':None,'toolEnd':None,'tool':None}
  if tool:
   a,b=tool; name=a.get('input',{}).get('tool_name','tool');args=a.get('input',{}).get('tool_args',{});kind='search' if name=='search' else 'read' if name=='visit' else 'compute'
   ts=max(0,a['epoch']-origin);sec=b.get('seconds',0);child=[(c,d) for c,d in pairs if c.get('parent_id')==a['span_id'] or (a['epoch']<=c['epoch']<=b['epoch'] and c['kind'] in ('reader','summary','search_query','python'))]
   obj={'name':name,'kind':kind,'goal':''}
   if kind=='search':
    queries=[]
    for c,d in child:
     if c['kind']!='search_query':continue
     response=d.get('serper_response') or {};items=response.get('organic',[]) if isinstance(response,dict) else [];results=[]
     for item in items:
      url=item.get('link','');domain=urlparse(url).netloc
      if url:sources.add(url);domains[domain]+=1
      results.append({'title':item.get('title',''),'url':url,'domain':domain,'snippet':item.get('snippet','')})
     queries.append({'query':txt(c.get('input',{}).get('query','')),'seconds':d.get('seconds',0),'count':len(results),'results':results,'rawOutput':d.get('output','')})
    if not queries:queries=[{'query':txt(args),'seconds':sec,'count':0,'results':[],'rawOutput':b.get('output','')}]
    obj.update(queries=queries,queryCount=len(queries),issuedQueryCount=len(queries),resultCount=sum(x['count'] for x in queries),rawOutput=b.get('output',''))
   elif kind=='read':
    pages=[];summaries=[(c,d) for c,d in child if c['kind']=='summary']
    for c,d in child:
     if c['kind']!='reader':continue
     url=txt(c.get('input',{}).get('url',''));domain=urlparse(url).netloc
     if url:sources.add(url);domains[domain]+=1
     summary=next((x[1] for x in summaries if x[0]['epoch']>=d['epoch']),None)
     pages.append({'url':url,'domain':domain,'title':url or '页面','summary':txt(summary.get('output','')) if summary else '', 'rationale':'', 'evidence':txt(d.get('reader_response_text',d.get('output',''))),'readerSeconds':d.get('seconds',0),'summarySeconds':summary.get('seconds',0) if summary else 0})
    if not pages:pages=[{'url':'','domain':'','title':'读取结果','summary':txt(b.get('output','')),'rationale':'','evidence':'','readerSeconds':sec,'summarySeconds':0}]
    obj.update(pages=pages,pageCount=len(pages),rawOutput=b.get('output',''))
   else:obj.update(code=txt(args.get('code','') if isinstance(args,dict) else args),stdout=txt(b.get('output','')),language='python')
   step.update(kind=kind,label={'search':'搜索','read':'读取','compute':'计算'}[kind],tool_seconds=sec,toolStart=ts,toolEnd=ts+sec,tool=obj)
  steps.append(step)
 if not steps:continue
 prediction=txt(native.get('prediction','')); scored=state.get('judge_state')=='scored'; last=native.get('messages',[]); raw_final=txt(last[-1].get('content','')) if last else ''; display_answer=prediction if prediction.strip() else '运行中或无原生答案（未评分）';rounds=int(native.get('num_rounds',len(steps)) or 0);case_time={'model':round(timing['policy_model'],3),'search':round(timing['tool_search'],3),'read':round(timing['reader']+timing['summary'],3),'compute':round(timing['tool_PythonInterpreter'],3),'overhead':max(0,duration-timing['policy_model']-timing['tool']-timing['automatic_memory']),'total':duration,'reader':round(timing['reader'],3),'summary':round(timing['summary'],3),'memory':round(timing['automatic_memory'],3)}
 counts=collections.Counter(x['kind'] for x in steps);n=len(steps);querycount=sum(len(x['tool'].get('queries',[])) for x in steps if x['kind']=='search' and x['tool']);pages=sum(len(x['tool'].get('pages',[])) for x in steps if x['kind']=='read' and x['tool'])
 cases.append({'inProgress':state.get('agent_state')=='running','id':f'trace-{i+1:02d}','index':i+1,'field':'GAIA','fieldZh':'GAIA','topic':case,'topicZh':case,'question':native.get('question',''),'answer':display_answer,'answerNote':('未完成轨迹的时长为已记录事件窗口，不含暂停时间' if state.get('agent_state')=='running' and cli.stopped_at is not None else '原始模型预测及评分状态；未评分不等于错误'),'judge':str(state.get('judgment','')),'correct':(state.get('is_correct') is True) if scored else None,'rounds':rounds,'durationSeconds':duration,'durationText':f'{int(duration//60)}m {int(duration%60)}s','model':label,'risk':{'level':{'confirmed_answer_exposure':'alert','potential_benchmark_source_exposure':'warn','none_detected':'clean'}.get(audit_rows.get(case,{}).get('contamination_status'),'unknown'),'label':audit_rows.get(case,{}).get('contamination_status','not_audited')},'riskKey':audit_rows.get(case,{}).get('contamination_status','not_audited'),'stats':{'steps':n,'searchCalls':counts['search'],'readCalls':counts['read'],'computeCalls':counts['compute'],'searchQueries':querycount,'resultsScanned':sum(x['tool'].get('resultCount',0) for x in steps if x['kind']=='search' and x['tool']),'pagesRead':pages,'uniqueSources':len(sources),'uniqueDomains':len(domains),'maxPromptTokens':0,'maxOutputTokens':0,'averageStepSeconds':duration/n,'longestStepSeconds':max((x['model_seconds']+x['tool_seconds'] for x in steps),default=0)},'timing':case_time,'domains':[{'domain':k,'count':v} for k,v in domains.most_common()],'steps':steps,'finalAnswer':raw_final or prediction,'keyIndices':[],'sources':sorted(sources)})
 _gt=gt_rows.get(norm_gt(native.get('question','')))
 if _gt:
  cases[-1]['groundTruth']=txt(_gt.get('answer',''))
  cases[-1]['groundTruthTaskId']=txt(_gt.get('task_id',''))
  cases[-1]['groundTruthLevel']=txt(_gt.get('Level',''))
if not cases:raise SystemExit(0)
run={'name':label+' · GAIA','model':label,'benchmark':'GAIA text-only','date':datetime.datetime.now(datetime.timezone.utc).date().isoformat(),'dateShort':datetime.datetime.now(datetime.timezone.utc).date().isoformat(),'totalCases':len(cases),'judgePassed':sum(c['correct'] is True for c in cases),'judgeScored':sum(c['correct'] is not None for c in cases),'rounds':sum(c['rounds'] for c in cases),'toolCalls':sum(c['stats']['searchCalls']+c['stats']['readCalls']+c['stats']['computeCalls'] for c in cases),'pagesRead':sum(c['stats']['pagesRead'] for c in cases),'searchQueries':sum(c['stats']['searchQueries'] for c in cases),'searchCalls':sum(c['stats']['searchCalls'] for c in cases),'inProgress':cli.stopped_at is None and not (root/'COMPLETE.json').exists(),'stopped':cli.stopped_at is not None,'paused':(root/'checks/deepseek-balance-pause.json').exists() and not (root/'checks/deepseek-balance-resume.json').exists(),'requestedCases':cli.requested_cases,'wiki':'源于指定运行的原始事件；未评分不计为错误。'}
dest.mkdir(parents=True,exist_ok=True)
tmp=dest/f'traces.{os.getpid()}.tmp'
try:
 tmp.write_text(json.dumps({'generatedAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),'run':run,'cases':cases},ensure_ascii=False))
 if out.exists() and not cli.replace_existing:raise FileExistsError('viewer output exists')
 tmp.replace(out)
finally:
 if tmp.exists():tmp.unlink()
print('VIEWER_CASES',len(cases),flush=True)
