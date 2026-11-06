"""Fill genuine evidence deficits with fresh runs of the same summary harness.

Original questions only; no reference answer or inherited memory is injected.
Training views come from actual recorded API requests, so condenser transitions
cannot retroactively change prompts of earlier supervised turns.
"""
import concurrent.futures
import json
from pathlib import Path
import subprocess
import time
from inference import native_tools, source_ids
from run_summary16 import environment
from optimization_quality import evidence_bundle

ROOT=Path(__file__).resolve().parents[2]


def record_from_events(run, meta, schemas):
    from optimize_summary_data import write, sha
    case=meta['case'];result_file=next((run/'results'/case).rglob('iter1.jsonl'))
    result=json.loads(result_file.read_text().splitlines()[-1])
    if not result.get('prediction') or 'answer not found' in result['prediction'].lower():
        raise ValueError('incomplete_generation')
    events=list(map(json.loads,(run/'logs'/(case+'-agent-events.jsonl')).read_text().splitlines()))
    source_dir=run/'traces'/case/case/'iter1'
    mapping=json.loads((source_dir/'sources.json').read_text())
    provenance=json.loads((source_dir/'source-provenance.json').read_text())
    registry=source_ids.SourceRegistry(run/'validated-sources'/case)
    known={};history=[];views=[];pending=[]
    def admit(ids):
        for sid in ids:
            if sid not in mapping:raise ValueError('unknown_observation_source')
            known[sid]=mapping[sid]
        write(registry.path,known)
        write(registry.provenance_path,{s:provenance.get(s,{'origins':[]}) for s in known})
    for event in events:
        if event['event']!='span_end':continue
        if event.get('kind')=='policy_model':
            context=event.get('api_request_context');api=event.get('api_response');options=event.get('api_request_options')
            if not context or not api or not options:raise ValueError('missing_actual_request_or_response')
            if sha(context.get('tools'))!=sha(schemas):raise ValueError('runtime_tool_schema_mismatch')
            choice=api['choices'][0]
            if choice.get('finish_reason') not in ('stop','tool_calls'):raise ValueError('truncated_or_invalid_target')
            if not history:
                initial=context['messages'][:2]
                # System instructions contain illustrative IDs such as S123;
                # they are not user-provided sources or evidence.
                initial_ids=source_ids.referenced_ids([m for m in initial if m['role']!='system'])
                for sid in initial_ids:
                    if not set(provenance.get(sid,{}).get('origins',[])) & {'user_seed','instruction'}:
                        raise ValueError('initial_context_contains_nonseed_source')
                admit(initial_ids);history.extend(initial)
            if pending:raise ValueError('missing_tool_return')
            # Every source visible in a captured prompt must have appeared in
            # the real preceding observation stream, including across memory.
            if source_ids.referenced_ids([m for m in context['messages'] if m['role']!='system'])-known.keys():
                raise ValueError('future_source_in_actual_prompt')
            raw=choice['message'];target={'role':'assistant','content':raw.get('content') or ''}
            reasoning=raw.get('reasoning_content') or raw.get('reasoning')
            if reasoning:target.update(reasoning_content=reasoning,reasoning=reasoning)
            calls=raw.get('tool_calls') or []
            if calls:
                target['tool_calls']=[{'id':c['id'],'type':'function','function':{
                    'name':c['function']['name'],'arguments':c['function']['arguments']}} for c in calls]
                if len(calls)!=1:raise ValueError('multiple_tool_calls')
                # A new trajectory must not contain illegal calls or text-only
                # calls. The live harness can recover, but these are not clean targets.
                from jsonschema import validate
                tool=next((s for s in schemas if s['function']['name']==calls[0]['function']['name']),None)
                if tool is None:raise ValueError('unavailable_tool')
                validate(json.loads(calls[0]['function']['arguments']),tool['function']['parameters'])
            if '<tool_call>' in target['content']:raise ValueError('textual_tool_call')
            target=registry.assistant(target)
            final=options.get('tool_choice')=='none'
            if final:
                value=json.loads(target['content'])
                if set(value)!= {'answer'}:raise ValueError('invalid_final_json')
                registry.validate_final(value['answer'])
                history.append(context['messages'][-1])
            history.append(target)
            views.append({'messages':context['messages']+[target],'tools':context['tools'],
                          'final':final,'source_span':event['span_id'],'history_step':len(history)-1,
                          'request_options':options})
            pending=list(target.get('tool_calls',[]))
        elif event.get('kind')=='tool':
            if len(pending)!=1:raise ValueError('unpaired_tool_result')
            body=event.get('output')
            if not isinstance(body,str) or not body.strip() or body.lstrip().startswith(('[Tool Error]','[Visit Error]')):
                raise ValueError('failed_tool_result')
            admit(source_ids.referenced_ids(body))
            history.append({'role':'tool','tool_call_id':pending[0]['id'],'content':body});pending=[]
    if pending or not views or not views[-1]['final']:raise ValueError('missing_complete_final')
    if json.loads(history[-1]['content'])['answer'] != result['prediction']:raise ValueError('final_result_mismatch')
    ident=sha({'source_question':meta['question_sha256'],'views':views})
    metadata=dict(meta,id=ident,source_map=str(registry.path),has_memory=False,
                  session_type='fresh_recorded_policy_views',visible_tool_calls=sum(bool(m.get('tool_calls')) for m in history),
                  generation_run=str(run),source_stratum=meta['stratum'],
                  stratum_definition='original source-session stratum; regenerated length reported separately',
                  automatic_memory_used=any(e.get('kind')=='memory_api' for e in events),
                  quality_status='pending_semantic_review',converted_sha256=sha(history),tools_sha256=sha(schemas))
    row={'messages':history,'tools':schemas,'metadata':metadata,'training_views':views}
    if evidence_bundle(row)['rule_issues']:raise ValueError('final_citation_not_supported_by_observation')
    return row


def generate(pipeline, meta, job):
    from optimize_summary_data import write
    run=Path(job['run']);case=meta['case']
    for name in ('logs','traces','results','cache','configs'):(run/name).mkdir(parents=True,exist_ok=True)
    (run/'configs'/(case+'.jsonl')).write_text(json.dumps({'question':meta['question'],'answer':'','filename':case})+'\n')
    (run/'configs'/(case+'-server_endpoints.conf')).write_text('HOSTNAME_LIST=127.0.0.1\nPORTS=19300\n')
    job_path=run/'job.json';write(job_path,dict(job,status='running'))
    try:
        with (run/'logs'/(case+'-console.log')).open('x') as log:
            child=subprocess.Popen([str(ROOT/'workspace/env/bin/python'),str(ROOT/'inference/scripts/observe_retrieval_ab.py')],
                cwd=ROOT,env=environment(run,case),stdout=log,stderr=subprocess.STDOUT)
            try:code=child.wait(timeout=3600)
            except subprocess.TimeoutExpired:child.kill();child.wait();raise ValueError('generation_timeout')
        if code:raise ValueError('generation_process_failed')
        row=record_from_events(run,meta,pipeline.schemas)
        # Validate the actual per-call training lengths, not a synthetic
        # concatenation that would erase memory boundaries.
        lengths=[]
        for view in row['training_views']:
            ids=pipeline.tokenizer.apply_chat_template(native_tools.prepare_messages(view['messages'],for_template=True),
                tools=view['tools'],enable_thinking=not view['final'],tokenize=True,return_dict=False)
            lengths.append(len(ids))
        if max(lengths)>65536:raise ValueError('generated_training_view_overlength')
        row['metadata'].update(tokens=max(lengths),optimization_contract=pipeline.contract_sha)
        ident=row['metadata']['id']
        write(pipeline.out/'records'/(ident+'.json'),row)
        write(pipeline.out/'rules'/(ident+'.json'),{'id':ident,'kind':meta['kind'],'stratum':meta['stratum'],'status':'pass','generated':True})
        decision=pipeline.review(row)
        write(job_path,dict(job,status='reviewed',candidate_id=ident,decision=decision['status']))
        return decision['status']
    except Exception as exc:
        write(job_path,dict(job,status='failed',error=type(exc).__name__+':'+str(exc)[:700]))
        return 'failed'


def fill(pipeline):
    """At most two fresh attempts per unused question, with explicit receipts."""
    from optimize_summary_data import write
    jobs_root=pipeline.out/'generated';jobs_root.mkdir(exist_ok=True)
    if pipeline.tokenizer is None:
        from transformers import AutoTokenizer
        pipeline.tokenizer=AutoTokenizer.from_pretrained(ROOT/'workspace/models/Qwen3.8-27B-NVFP4',local_files_only=True)
    attempts={}
    for f in jobs_root.glob('*/job.json'):
        j=json.loads(f.read_text());attempts[j['question_sha256']]=max(attempts.get(j['question_sha256'],0),j['attempt'])
    running={};active=set();failures=0;halted=False
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(2,pipeline.args.workers)) as pool:
        while True:
            rows,counts=pipeline.accepted();seen={r['metadata']['question_sha256'] for r in rows}
            if len(rows)==1024 and not running:break
            capacity=0 if halted else min(2,pipeline.args.workers)-len(running)
            for _ in range(capacity):
                chosen=None
                for m in pipeline.plan:
                    key=(m['kind'],m['stratum']);quota=192 if m['kind']=='objective' else 64
                    q=m['question_sha256']
                    if counts[key]>=quota or q in seen or q in active or attempts.get(q,0)>=2:continue
                    if not pipeline.original_rubrics.eligible(m):continue
                    chosen=m;break
                if chosen is None:break
                q=chosen['question_sha256'];attempts[q]=attempts.get(q,0)+1
                raw=pipeline.db.execute('SELECT meta FROM pool WHERE id=?',(chosen['id'],)).fetchone()[0]
                meta=json.loads(raw);meta.update(stratum=chosen['stratum'],case='generated')
                run=jobs_root/(q[:20]+f'-a{attempts[q]}')
                job={'question_sha256':q,'source_candidate':chosen['id'],'attempt':attempts[q],
                     'kind':chosen['kind'],'source_stratum':chosen['stratum'],'run':str(run),
                     'profile':'same summary harness, 100 policy calls, 40000 memory threshold'}
                run.mkdir();write(run/'job.json',dict(job,status='queued'))
                future=pool.submit(generate,pipeline,meta,job);running[future]=q;active.add(q)
            if not running:break
            done,_=concurrent.futures.wait(running,timeout=30,return_when=concurrent.futures.FIRST_COMPLETED)
            for f in done:
                status=f.result();active.remove(running.pop(f))
                failures=failures+1 if status=='failed' else 0
                if failures>=5:
                    halted=True
                    write(pipeline.out/'generation-halted.json',{'reason':'Five consecutive operational or structural generation failures; inspect job receipts before resuming.'})
            pipeline.progress('regenerating_evidence_deficits')
    pipeline.progress('regeneration_pool_exhausted_or_target_met')
