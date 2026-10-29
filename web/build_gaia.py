"""Build an atomically replaceable viewer dataset from completed native spans."""
import argparse,collections,datetime,json,os,re,sys,time
from pathlib import Path
from urllib.parse import urlparse

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO));from inference.visible_judge_state import apply_visible_judgment
parser=argparse.ArgumentParser(description='Build a fresh viewer dataset from recorded GAIA spans; does not run inference or scoring.')
parser.add_argument('--run-root',type=Path,required=True)
parser.add_argument('--output-dir',type=Path,required=True)
parser.add_argument('--label',required=True)
parser.add_argument('--requested-cases',type=int,default=32)
parser.add_argument('--benchmark',default='GAIA',help='Benchmark label for the viewer')
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
retry_manifest=root.parent/'checks/retry-required.json'
retries={};running_retries={};pending_retries=set()
if retry_manifest.exists():
 try:
  retry_records=json.loads(retry_manifest.read_text()).get('cases',[])
  retries={(x['group'],x['case']):x for x in retry_records if x.get('status')=='completed' and x.get('result_path') and x.get('retry_root')}
  running_retries={(x['group'],x['case']):x for x in retry_records if x.get('status')=='running_retry' and x.get('retry_root')}
  pending_retries={(x['group'],x['case']) for x in retry_records if x.get('status')=='pending_retry'}
 except (OSError,ValueError,KeyError):pass
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
 case=f'row{i:04d}';state=dict(status['cases'].get(case,{}))
 retry=retries.get((root.name,case))
 running_retry=running_retries.get((root.name,case))
 event_root=Path((retry or running_retry)['retry_root']) if retry or running_retry else root
 if retry:state.update(agent_state='terminal',judge_state='scored',is_correct=retry['is_correct'],result_path=retry['result_path'],judgment='GAIA official normalized exact match；工具修复后重跑')
 elif running_retry:state.update(agent_state='running',judge_state='pending',is_correct=None,result_path=None,judgment='正在重跑；原轨迹保留')
 elif (root.name,case) in pending_retries:state.update(judge_state='pending',is_correct=None,judgment='工具异常；等待重跑')
 final_retry=root/'checks'/f'{case}-final-answer-recovery.json'
 if cli.benchmark.lower()=='browsecomp' and final_retry.exists():
  try:
   recovered=json.loads(final_retry.read_text())
   if recovered.get('status')=='scored' and isinstance(recovered.get('is_correct'),bool) and Path(recovered.get('recovery_result_path','')).is_file():
    state.update(judge_state='scored',is_correct=recovered['is_correct'],result_path=recovered['recovery_result_path'],judgment='100 轮后无工具最终回答补全；本地 4B 裁判，原轨迹及原评分保留')
  except (OSError,ValueError,TypeError):pass
 local_judge_retry=root/'checks'/f'{case}-local-judge-retry.json'
 if state.get('judge_state')=='unavailable' and local_judge_retry.exists():
  try:
   receipt=json.loads(local_judge_retry.read_text())
   if receipt.get('status')=='scored' and isinstance(receipt.get('is_correct'),bool):
    state.update(judge_state='scored',is_correct=receipt['is_correct'],judgment='BrowseComp 官方判分提示；本地 4B 裁判格式重试')
  except (OSError,ValueError,TypeError):pass
 if cli.benchmark.lower()=='browsecomp':state,_=apply_visible_judgment(root,case,state)
 receipt_path=root/'checks'/f'{case}-score-receipt.json'
 if receipt_path.exists():
  try:
   receipt=json.loads(receipt_path.read_text());grade=receipt.get('status')
   if grade=='scored' and isinstance(receipt.get('is_correct'),bool):state.update(judge_state='scored',is_correct=receipt['is_correct'],judgment='DeepSeek Flash：'+('通过' if receipt['is_correct'] else '未通过')+'；判定内容：'+str(receipt.get('judgment','')))
   elif grade=='scored' and isinstance(receipt.get('score'),(int,float)):
    state.update(judge_state='scored_numeric',score=receipt['score'],judgment=str(receipt.get('judgment','评分'))+'：'+str(receipt['score'])+('；输出未被官方解析器识别，按官方规则计零' if 'official_zero_unparseable_response' in receipt.get('limitations',[]) else '')+('；无可验证引用，FACT 未评分' if 'fact_not_evaluable_no_validated_citations' in receipt.get('limitations',[]) else '')+('；引用抓取失败，FACT 未评分' if 'fact_citation_retrieval_failed' in receipt.get('limitations',[]) else '')+('；FACT 未运行' if 'fact_not_evaluated' in receipt.get('limitations',[]) else ''))
   elif grade=='scored_dimensions':state.update(judge_state='scored_dimensions',judgment='各维度评分：'+txt(receipt.get('dimensions',{})))
   elif grade=='needs_audit':state.update(judge_state='pending',judgment='评分已运行，待核验'+('；已有维度：'+txt(receipt['dimensions']) if receipt.get('dimensions') else '')+('；缺参考报告，未评分 depth' if 'depth_not_evaluated' in receipt.get('limitations',[]) or 'missing_depth' in receipt.get('limitations',[]) else ''))
   elif grade=='failed':state.update(judge_state='unavailable',judgment='评分失败，查看评分日志'+('：'+str(receipt['reason']) if receipt.get('reason') else ''))
   evidence=receipt.get('evidence')
   if isinstance(evidence,dict):
    recall=evidence.get('retrieval_recall');citation=evidence.get('citation_metrics')
    state['judgment']=str(state.get('judgment',''))+('；检索召回率：'+str(recall) if recall is not None else '；检索召回率不可用（历史轨迹不完整或缺证据）')
    if isinstance(citation,dict):state['judgment']+='；引用精度：'+str(citation.get('precision'))+'，引用召回率：'+str(citation.get('recall'))+'，引用文档数：'+str(citation.get('num_citations'))
   fact=receipt.get('fact')
   if isinstance(fact,dict):
    if fact.get('status')=='scored':state['judgment']=str(state.get('judgment',''))+'；FACT 引用准确率：'+str(fact.get('valid_rate'))+'（有效判断 '+str(fact.get('validated_citations'))+' 条）'
    else:state['judgment']=str(state.get('judgment',''))+'；FACT 未评分：'+str(fact.get('reason','待核验'))
  except (OSError,ValueError,TypeError):pass
 events=read_events(event_root/'logs'/f'{case}-agent-events.jsonl')
 retrieval_audits=read_events(event_root/'logs'/f'{case}-retrieval.jsonl')
 used_retrieval_audits=set()
 starts={x['span_id']:x for x in events if x.get('event')=='span_start'};ends={x['span_id']:x for x in events if x.get('event')=='span_end'}
 if state.get('agent_state')=='terminal' and state.get('result_path'):
  native=json.loads(result_path(state['result_path']).read_text().splitlines()[-1])
 elif state.get('agent_state') in ('running','interrupted') and cli.include_running:
  start=next((e for e in starts.values() if e.get('kind')=='task'),None)
  if not start: continue
  if cli.stopped_at is not None or state.get('agent_state')=='interrupted':
   # The task was paused before termination: do not count the pause as execution.
   # A partial trace has no authoritative task-end timestamp; show its recorded window.
   observed_epochs=[event.get('epoch') for event in events if isinstance(event.get('epoch'),(int,float))]
   observed_until=min(cli.stopped_at or float('inf'),max(observed_epochs,default=start['epoch']))
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
     audit=next(((i,x) for i,x in enumerate(retrieval_audits) if i not in used_retrieval_audits and x.get('url')==url),None)
     if audit:used_retrieval_audits.add(audit[0])
     info=audit[1] if audit else {}
     selected=txt(info.get('selected_content',''))
     desc=(f"筛选方式：{info.get('method','')}；原文 {info.get('input_tokens','?')} tokens；筛选后 {info.get('output_tokens','?')} tokens；原因：{info.get('reason','')}" if info else '')
     output=txt(summary.get('output','')) if summary else selected
     pages.append({'url':url,'domain':domain,'title':url or '页面','summary':output, 'rationale':desc, 'evidence':txt(d.get('reader_response_text',d.get('output',''))),'readerSeconds':d.get('seconds',0),'summarySeconds':summary.get('seconds',0) if summary else 0})
    if not pages:pages=[{'url':'','domain':'','title':'读取结果','summary':txt(b.get('output','')),'rationale':'','evidence':'','readerSeconds':sec,'summarySeconds':0}]
    obj.update(pages=pages,pageCount=len(pages),rawOutput=b.get('output',''))
   else:obj.update(code=txt(args.get('code','') if isinstance(args,dict) else args),stdout=txt(b.get('output','')),language='python')
   step.update(kind=kind,label={'search':'搜索','read':'读取','compute':'计算'}[kind],tool_seconds=sec,toolStart=ts,toolEnd=ts+sec,tool=obj)
  steps.append(step)
 if not steps:continue
 prediction=txt(native.get('prediction','')); scored=state.get('judge_state')=='scored'; last=native.get('messages',[]); raw_final=txt(last[-1].get('content','')) if last else ''; display_answer=prediction if prediction.strip() else '运行中或无原生答案（未评分）';rounds=int(native.get('num_rounds',len(steps)) or 0);case_time={'model':round(timing['policy_model'],3),'search':round(timing['tool_search'],3),'read':round(timing['reader']+timing['summary'],3),'compute':round(timing['tool_PythonInterpreter'],3),'overhead':max(0,duration-timing['policy_model']-timing['tool']-timing['automatic_memory']),'total':duration,'reader':round(timing['reader'],3),'summary':round(timing['summary'],3),'memory':round(timing['automatic_memory'],3)}
 display_note='原始模型预测及评分状态；未评分不等于错误'
 if cli.benchmark.lower()=='browsecomp' and prediction.strip().lower() in ('answer not found.','no answer found.'):
  visible=raw_final.rsplit('</think>',1)[-1].split('<think>',1)[0]
  if '<tool_call>' not in visible:
   matches=re.findall(r'(?im)^\s*(?:\*\*)?Exact Answer\s*:?(?:\*\*)?\s*:\s*(.+?)\s*$',visible)
   if matches:
    display_answer=matches[-1].strip();display_note='从模型最终输出的 Exact Answer 提取用于展示；原生预测未识别，原始输出和评分不变'
 counts=collections.Counter(x['kind'] for x in steps);n=len(steps);querycount=sum(len(x['tool'].get('queries',[])) for x in steps if x['kind']=='search' and x['tool']);pages=sum(len(x['tool'].get('pages',[])) for x in steps if x['kind']=='read' and x['tool'])
 cases.append({'inProgress':state.get('agent_state')=='running','interrupted':state.get('agent_state')=='interrupted','id':f'trace-{i+1:02d}','index':i+1,'field':cli.benchmark,'fieldZh':cli.benchmark,'topic':case,'topicZh':case,'question':native.get('question',''),'answer':display_answer,'answerNote':('未完成轨迹的时长为已记录事件窗口，不含暂停时间' if state.get('agent_state')=='running' and cli.stopped_at is not None else display_note),'judge':str(state.get('judgment','')),'correct':(state.get('is_correct') is True) if scored else None,'score':state.get('score') if state.get('judge_state')=='scored_numeric' else None,'scoredDimensions':state.get('judge_state')=='scored_dimensions','rounds':rounds,'durationSeconds':duration,'durationText':f'{int(duration//60)}m {int(duration%60)}s','model':label,'risk':{'level':{'confirmed_answer_exposure':'alert','potential_benchmark_source_exposure':'warn','none_detected':'clean'}.get(audit_rows.get(case,{}).get('contamination_status'),'unknown'),'label':audit_rows.get(case,{}).get('contamination_status','not_audited')},'riskKey':audit_rows.get(case,{}).get('contamination_status','not_audited'),'stats':{'steps':n,'searchCalls':counts['search'],'readCalls':counts['read'],'computeCalls':counts['compute'],'searchQueries':querycount,'resultsScanned':sum(x['tool'].get('resultCount',0) for x in steps if x['kind']=='search' and x['tool']),'pagesRead':pages,'uniqueSources':len(sources),'uniqueDomains':len(domains),'maxPromptTokens':0,'maxOutputTokens':0,'averageStepSeconds':duration/n,'longestStepSeconds':max((x['model_seconds']+x['tool_seconds'] for x in steps),default=0)},'timing':case_time,'domains':[{'domain':k,'count':v} for k,v in domains.most_common()],'steps':steps,'finalAnswer':raw_final or prediction,'keyIndices':[],'sources':sorted(sources)})
 _gt=gt_rows.get(norm_gt(native.get('question','')))
 if _gt:
  cases[-1]['groundTruth']=txt(_gt.get('answer',''))
  cases[-1]['groundTruthTaskId']=txt(_gt.get('task_id',''))
  cases[-1]['groundTruthLevel']=txt(_gt.get('Level',''))
if not cases:raise SystemExit(0)
all_terminal=(len(status.get('cases',{}))>=cli.requested_cases and all(v.get('agent_state')=='terminal' for v in status['cases'].values()) and not any(group==root.name for group,_ in pending_retries))
run={'name':label+' · '+cli.benchmark,'model':label,'benchmark':('GAIA text-only' if cli.benchmark=='GAIA' else cli.benchmark),'date':datetime.datetime.now(datetime.timezone.utc).date().isoformat(),'dateShort':datetime.datetime.now(datetime.timezone.utc).date().isoformat(),'totalCases':len(cases),'judgePassed':sum(c['correct'] is True for c in cases),'judgeScored':sum(c['correct'] is not None for c in cases),'rounds':sum(c['rounds'] for c in cases),'toolCalls':sum(c['stats']['searchCalls']+c['stats']['readCalls']+c['stats']['computeCalls'] for c in cases),'pagesRead':sum(c['stats']['pagesRead'] for c in cases),'searchQueries':sum(c['stats']['searchQueries'] for c in cases),'searchCalls':sum(c['stats']['searchCalls'] for c in cases),'inProgress':cli.stopped_at is None and not (root/'COMPLETE.json').exists() and not all_terminal,'stopped':cli.stopped_at is not None,'paused':(root/'checks/deepseek-balance-pause.json').exists() and not (root/'checks/deepseek-balance-resume.json').exists(),'requestedCases':cli.requested_cases,'wiki':'源于指定运行的原始事件；未评分不计为错误。'}
dest.mkdir(parents=True,exist_ok=True)
tmp=dest/f'traces.{os.getpid()}.tmp'
try:
 tmp.write_text(json.dumps({'generatedAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),'run':run,'cases':cases},ensure_ascii=False))
 if out.exists() and not cli.replace_existing:raise FileExistsError('viewer output exists')
 tmp.replace(out)
finally:
 if tmp.exists():tmp.unlink()
print('VIEWER_CASES',len(cases),flush=True)
