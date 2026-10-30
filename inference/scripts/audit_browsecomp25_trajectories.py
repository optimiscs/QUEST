"""Account for completed original trajectories and labeled recovery overlays.

Token usage comes from recorded API responses. Judge calls and legacy final
answer recovery are excluded because their original logs do not record usage.
Observed error/format flags describe the trajectory, not the cause of failure.
"""
import collections
import json
import math
import re
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
RUN=ROOT/'workspace/strict-reproduction/browsecomp-sft-25pct-pool64-20261029-r1'
sys.path.insert(0,str(ROOT));from inference.visible_judge_state import apply_visible_judgment


def stats(values):
    values=sorted(x for x in values if isinstance(x,(int,float)) and math.isfinite(x) and x>=0)
    return {'n':len(values),'mean':sum(values)/len(values) if values else None,
            'p50':values[math.ceil(.5*len(values))-1] if values else None,
            'p95':values[math.ceil(.95*len(values))-1] if values else None}


def effective_result(case,row):
    effective=dict(row);result=Path(row['result_path']);grade_source='judge_format_retry' if row.get('judge_recovery_path') else 'original'
    final=RUN/'checks'/f'{case}-final-answer-recovery.json'
    if final.exists():
        receipt=json.loads(final.read_text())
        if receipt.get('status')=='scored' and isinstance(receipt.get('is_correct'),bool):
            effective.update(judge_state='scored',is_correct=receipt['is_correct'])
            result=Path(receipt['recovery_result_path']);grade_source='final_answer_recovery'
    retry=RUN/'checks'/f'{case}-local-judge-retry.json'
    if effective.get('judge_state')=='unavailable' and retry.exists():
        receipt=json.loads(retry.read_text())
        if receipt.get('status')=='scored' and isinstance(receipt.get('is_correct'),bool):
            effective.update(judge_state='scored',is_correct=receipt['is_correct']);grade_source='judge_format_retry'
    effective,visible_receipt=apply_visible_judgment(RUN,case,dict(effective,result_path=str(result)))
    if visible_receipt:grade_source='visible_final_only'
    return effective,result,grade_source


def audit():
    state=json.loads((RUN/'status.json').read_text());totals=collections.Counter()
    api=collections.defaultdict(collections.Counter);latencies=collections.defaultdict(list)
    retrieval=collections.Counter();cases=[];issues=[];score_groups=collections.defaultdict(list);reader_returns=collections.Counter()
    for case,row in state['cases'].items():
        if row.get('agent_state')!='terminal':continue
        originals=list((RUN/'results'/case).rglob('iter1.jsonl'))
        if len(originals)!=1 or not row.get('result_path'):
            issues.append({'case':case,'issue':'missing_or_duplicate_original_result'});continue
        original=json.loads(Path(row['result_path']).read_text().splitlines()[-1])
        effective,result_path,grade_source=effective_result(case,row)
        result=json.loads(result_path.read_text().splitlines()[-1])
        outcome=('correct' if effective.get('is_correct') is True else 'incorrect') if effective.get('judge_state')=='scored' else 'unscored'
        totals[outcome]+=1;rounds=original.get('num_rounds');spans=collections.Counter();current_policy_index=0;diagnostics=collections.Counter();queries=collections.Counter()
        if not isinstance(rounds,int) or not 0<rounds<=100:issues.append({'case':case,'issue':'research_round_limit','rounds':rounds})
        if grade_source=='final_answer_recovery':
            old_messages=original.get('messages',[]);new_messages=result.get('messages',[])
            if new_messages[:len(old_messages)]!=old_messages or any(x.get('role') not in ('user','assistant') for x in new_messages[len(old_messages):]):
                issues.append({'case':case,'issue':'recovery_changed_prior_messages_or_added_tool_messages'})
        events=RUN/'logs'/f'{case}-agent-events.jsonl'
        if not events.exists():issues.append({'case':case,'issue':'missing_agent_events'})
        else:
            for line in events.open():
                try:event=json.loads(line)
                except ValueError:issues.append({'case':case,'issue':'invalid_completed_event_record'});continue
                kind=event.get('kind')
                if event.get('event')=='span_start' and kind=='search_query':
                    query=event.get('input',{}).get('query')
                    if isinstance(query,str):queries[' '.join(query.casefold().split())]+=1
                if event.get('event')=='span_start' and kind=='tool' and current_policy_index>100:
                    issues.append({'case':case,'issue':'tool_executed_after_research_limit'})
                if event.get('event')!='span_end':continue
                spans[kind]+=1
                if kind=='policy_model':
                    current_policy_index+=1
                    content=str(event.get('output') or '').rsplit('</think>',1)[-1].split('<think>',1)[0]
                    content=re.sub(r'```[^\n]*\n.*?```','',content,flags=re.S)
                    calls=re.findall(r'<tool_call>(.*?)</tool_call>',content,re.S)
                    if calls:
                        raw=re.sub(r'<code>.*?</code>','',calls[-1],flags=re.S).strip()
                        try:json.loads(raw)
                        except ValueError:diagnostics['raw_invalid_tool_json']+=1
                    choices=(event.get('api_response') or {}).get('choices') or []
                    if choices and choices[0].get('finish_reason')=='length':diagnostics['model_length_truncations']+=1
                if kind=='reader':
                    content=str(event.get('output') or '')
                    reader_returns['none_or_empty' if not content else 'error' if content.startswith(('[visit] Error','[visit] Failed','[visit] Empty')) else 'content']+=1
                    if content.startswith(('[visit] Error','[visit] Failed','[visit] Empty')):diagnostics['reader_error_returns']+=1
                    if not content:diagnostics['reader_empty_returns']+=1
                    status=event.get('http_status')
                    if isinstance(status,int) and not 200<=status<300:diagnostics['reader_non_2xx']+=1
                if kind in ('policy_model','memory_api','summary','reader','tool'):
                    latencies[kind].append(event.get('seconds'))
                response=event.get('api_response')
                if not isinstance(response,dict) or not response.get('model'):continue
                model=response['model'];account=api[(kind,model)];account['responses']+=1
                usage=response.get('usage')
                if isinstance(usage,dict):
                    account['responses_with_usage']+=1
                    for field in ['prompt_tokens','completion_tokens','total_tokens']:
                        if isinstance(usage.get(field),int):account[field]+=usage[field]
                    details=usage.get('prompt_tokens_details')
                    if isinstance(details,dict) and isinstance(details.get('cached_tokens'),int):
                        account['responses_with_cache_usage']+=1;account['cached_tokens_reported']+=details['cached_tokens']
        if isinstance(rounds,int) and spans['policy_model']>rounds+3:
            issues.append({'case':case,'issue':'more_than_three_final_model_calls','policy_calls':spans['policy_model'],'rounds':rounds})
        retrieval_path=RUN/'logs'/f'{case}-retrieval.jsonl'
        if retrieval_path.exists():
            for line in retrieval_path.open():
                try:item=json.loads(line)
                except ValueError:issues.append({'case':case,'issue':'invalid_completed_retrieval_record'});continue
                retrieval['pages']+=1
                if item.get('method')!='bm25' or item.get('delivery')!='direct':issues.append({'case':case,'issue':'unexpected_retrieval_or_delivery_mode'})
                for field in ('input_tokens','output_tokens'):
                    if isinstance(item.get(field),int):retrieval[field]+=item[field]
        totals.update({f'spans:{key}':value for key,value in spans.items()})
        log_path=RUN/'logs'/f'{case}-agent.stdout.log';log=log_path.read_text(errors='replace') if log_path.exists() else ''
        repairs=log.count('[Tool JSON repair] appended')+log.count('[Tool JSON repair] inserted one missing array bracket')
        diagnostics['unrepaired_invalid_tool_json']=max(0,diagnostics['raw_invalid_tool_json']-repairs)
        diagnostics['memory_parse_failure']=log.count('[Memory] Warning: Failed to parse state from condenser result')
        diagnostics['context_overflow']=int(bool(re.search(r'ContextWindowExceededError|maximum context length|context_length_exceeded',log,re.I)))
        diagnostics['max_identical_search_repeats']=max(queries.values(),default=0)
        last=str((result.get('messages') or [{}])[-1].get('content','')).rsplit('</think>',1)[-1].split('<think>',1)[0]
        diagnostics['last_response_tool_call']=int('<tool_call>' in last)
        receipt=RUN/'checks'/f'{case}-visible-response-judge.json';extracted=None
        if receipt.exists():
            judgment=json.loads(receipt.read_text());match=re.search(r'(?im)^\s*extracted_final_answer:\s*(.*)$',judgment.get('raw') or '')
            extracted=match.group(1).strip() if match else None
        duration=row.get('agent_ended_epoch',0)-row.get('agent_started_epoch',0)
        record={'case':case,'outcome':outcome,'grade_source':grade_source,'original_is_correct':row.get('is_correct'),
                'rounds':rounds,'duration_seconds':duration,'original_termination':original.get('termination'),
                'original_prediction_missing':original.get('prediction') in ('answer not found.','no answer found.',''),
                'message_count':len(result.get('messages',[])),
                'trajectory_chars':sum(len(str(x.get('content',''))) for x in result.get('messages',[])),
                'effective_prediction_missing':result.get('prediction') in ('answer not found.','no answer found.',''),
                'judge_extracted_answer':extracted,'diagnostics':dict(diagnostics),
                'spans':dict(spans),'effective_result_path':str(result_path)}
        cases.append(record);score_groups[outcome].append(record)
    preparation=[];preparation_path=RUN/'checks/row0300-memory-preparation-api.jsonl'
    if preparation_path.exists():
        for line in preparation_path.open():
            item=json.loads(line);preparation.append({key:item.get(key) for key in ['model','usage','seconds']})
    models={model for _,model in api}|{item['model'] for item in preparation if item.get('model')}
    checks={'original_result_and_round_and_event_integrity':not issues,
            'no_page_summary_calls':totals['spans:summary']==0,
            'only_local_models_in_recorded_responses':bool(models) and models<={'QWEN35-SFT10','QWEN35-BASE','openai/QWEN35-BASE'}}
    comparisons={}
    for outcome,items in score_groups.items():
        comparisons[outcome]={'n':len(items),'rounds':stats([x['rounds'] for x in items]),
                              'duration_seconds':stats([x['duration_seconds'] for x in items]),
                              'trajectory_chars':stats([x['trajectory_chars'] for x in items]),
                              'missing_prediction':sum(x['original_prediction_missing'] for x in items),
                              'hit_100_rounds':sum(x['rounds']==100 for x in items)}
    return {'epoch':time.time(),'status_snapshot_epoch':state['epoch'],'requested':state['total'],'completed_analyzed':len(cases),
            'scope':'Completed original trajectories only. API token usage excludes judges and legacy final-answer recovery; missing cache usage is unknown, not zero. BM25 token counts use the retrieval chunk tokenizer.',
            'checks':checks,'issues':issues,'counts':dict(totals),
            'api_usage':[{'kind':kind,'model':model,**dict(values)} for (kind,model),values in api.items()],
            'additional_memory_preparation_api_usage':preparation,
            'retrieval':dict(retrieval),'timings':{kind:stats(values) for kind,values in latencies.items()},
            'reader_return_categories':dict(reader_returns),
            'outcome_comparison':comparisons,'cases':cases}


if __name__=='__main__':
    data=audit();out=RUN/'checks/trajectory-accounting.json';tmp=out.with_suffix('.tmp')
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');tmp.replace(out)
    print(json.dumps({k:data[k] for k in ['completed_analyzed','checks','issues','api_usage','retrieval']},ensure_ascii=False))
    raise SystemExit(0 if all(data['checks'].values()) else 1)
