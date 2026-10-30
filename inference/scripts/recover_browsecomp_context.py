"""Resume the interrupted context-overflow case within its original turn budget."""
import copy
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
RUN=ROOT/'workspace/strict-reproduction/browsecomp-sft-25pct-pool64-20261029-r1'
CASE='row0300'


def update(**fields):
    with (RUN/'controller.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        path=RUN/'status.json';state=json.loads(path.read_text());state['cases'][CASE].update(fields);state['epoch']=time.time()
        temporary=path.with_suffix('.context-recovery.tmp');temporary.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n');temporary.replace(path)


def main():
    with (RUN/'checks/context-recovery.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        metadata=json.loads((RUN/'checks/research-recovery-active.json').read_text())
        record=json.loads(Path(metadata['checkpoint_path']).read_text().splitlines()[-1])
        os.environ.update(MEMORY_MODEL_NAME='openai/QWEN35-BASE',MEMORY_API_BASE='http://127.0.0.1:18201/v1',MEMORY_API_KEY='EMPTY',MEMORY_DISABLE_THINKING='true',MEMORY_TOKENIZER_PATH=str(ROOT/'workspace/models/Qwen3.5-4B'),MEMORY_INPUT_TOKEN_BUDGET='48000',MEMORY_MAX_OUTPUT_TOKENS='4096',MEMORY_RETRY_INVALID_JSON='true',MEMORY_BATCH_AUDIT=str(RUN/'checks/row0300-memory-batches.jsonl'))
        for key in ['VISIT_LOCAL_PROMPT_ENABLED','MEMORY_LOCAL_PROMPT_ENABLED']:os.environ.pop(key,None)
        update(agent_state='running',agent_pid=os.getpid(),judge_state='pending',recovery_stage='memory_preparation',recovery_pending=True)
        sys.path.insert(0,str(ROOT/'inference'))
        from tool_memory import Memory
        tool=Memory();tool.token_threshold=None
        events=[copy.deepcopy(message) for message in record['messages'] if message.get('role') in ('user','assistant')]
        api_code=tool.call_api_with_litellm.__func__.__code__;started={}
        def profile(frame,event,arg):
            if frame.f_code is not api_code:return
            if event=='call':started[id(frame)]=time.monotonic()
            elif event=='return':
                response=frame.f_locals.get('response') or frame.f_locals.get('chat_response');usage=getattr(response,'usage',None)
                item={'epoch':time.time(),'seconds':time.monotonic()-started.pop(id(frame),time.monotonic()),'model':getattr(response,'model',None),'usage':usage.model_dump() if hasattr(usage,'model_dump') else None,'output':arg}
                with (RUN/'checks/row0300-memory-preparation-api.jsonl').open('a') as handle:handle.write(json.dumps(item,ensure_ascii=False,default=str)+'\n')
        sys.setprofile(profile)
        try:raw=tool.call({'events':events,'prev_state':None})
        finally:sys.setprofile(None)
        memory=tool._extract_json_from_response(raw)
        if not isinstance(memory,dict) or not memory:raise RuntimeError('bounded memory did not produce a usable state; raw checkpoint retained')
        systems=[copy.deepcopy(message) for message in record['messages'] if message.get('role')=='system']
        first_user=copy.deepcopy(next(message for message in record['messages'] if message.get('role')=='user'))
        marker='====================\nRESEARCH STATE SUMMARY'
        position=first_user['content'].find(marker)
        if position>=0:first_user['content']=first_user['content'][:position].rstrip()
        first_user['content']+='\n\n====================\nRESEARCH STATE SUMMARY (prev_state)\n====================\n'+json.dumps(memory,ensure_ascii=False,indent=2)+'\n\nContinue from this saved research state, retaining its source references and uncertainty labels.'
        seed=dict(record,messages=systems+[first_user],memory_state=memory,termination='temporal save')
        destination=RUN/'results'/CASE/'QWEN35-SFT10'/CASE/'iter1.jsonl';destination.parent.mkdir(parents=True,exist_ok=True)
        if destination.exists():raise RuntimeError('refusing to overwrite a prior completed native result')
        destination.write_text(json.dumps(seed,ensure_ascii=False)+'\n')
        (RUN/'checks/row0300-resume-seed.jsonl').write_text(json.dumps(seed,ensure_ascii=False)+'\n')
        event_log=RUN/'logs'/f'{CASE}-agent-events.jsonl'
        original_bytes=event_log.read_bytes();original_copy=RUN/'checks/row0300-interrupted-events.jsonl';original_copy.write_bytes(original_bytes)
        if original_bytes and not original_bytes.endswith(b'\n'):
            cutoff=original_bytes.rfind(b'\n')+1;event_log.write_bytes(original_bytes[:cutoff])
        sequence_base=1000000
        env=dict(os.environ,QUEST_AB_PROJECT=str(ROOT/'workspace'),QUEST_AB_GROUP_ROOT=str(RUN),QUEST_AUDIT_CASE=CASE,QUEST_AUDIT_MODE='agent',QUEST_AB_NO_GAIA='true',QUEST_AB_MAX_TURNS='100',QUEST_AB_MEMORY_BASE='http://127.0.0.1:18210/v1',QUEST_TOOL_PROMPT_PROFILE=str(ROOT/'inference/tool_prompts/portable_v3.json'),VISIT_EXPERIMENT_METHOD='bm25',VISIT_EXPERIMENT_DELIVERY='direct',VISIT_PAGE_CONCURRENCY='16',VISIT_BM25_POOL_URL='http://127.0.0.1:18215',VISIT_EXPERIMENT_AUDIT=str(RUN/'logs'/f'{CASE}-retrieval.jsonl'),QUEST_AB_RESUME_MESSAGES='true',QUEST_AUDIT_SEQ_BASE=str(sequence_base),QUEST_KEY_ROTATION='1')
        env['PYTHONPATH']=str(ROOT/'inference/key_rotation')+os.pathsep+env.get('PYTHONPATH','')
        metadata.update(preparation_completed_epoch=time.time(),resume_seed_sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),original_event_sha256=hashlib.sha256(original_bytes).hexdigest(),event_sequence_base=sequence_base,memory_input_budget=48000,memory_max_output_tokens=4096)
        (RUN/'checks/research-recovery-active.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
        with (RUN/'logs'/f'{CASE}-agent.stdout.log').open('a') as output:
            output.write('\n[Context recovery] Original checkpoint retained; resuming within 100 total research rounds.\n');output.flush()
            process=subprocess.Popen([str(ROOT/'workspace/env/bin/python'),'-u',str(ROOT/'inference/scripts/observe_retrieval_ab.py')],cwd=RUN,env=env,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
            update(agent_state='running',agent_pid=process.pid,recovery_stage='resumed_agent',recovery_started_epoch=time.time(),result_path=str(destination))
            print('resumed agent',process.pid,'start round',record['num_rounds'],flush=True);returncode=process.wait()
        result=json.loads(destination.read_text().splitlines()[-1])
        if returncode or not result.get('resumed_from_messages') or not result.get('resume_memory_state_restored') or result.get('termination')=='temporal save':raise RuntimeError('resumed agent did not produce a completed result')
        if not record['num_rounds']<=result.get('num_rounds',0)<=100:raise RuntimeError('resumed round budget mismatch')
        update(agent_state='terminal',agent_returncode=returncode,agent_ended_epoch=time.time(),judge_state='unavailable',is_correct=None,recovery_pending=False,recovery_stage='completed',judgment='检查点续跑完成，统一最终可见回答评分由独立裁判写入')
        (RUN/'checks/research-recovery-complete.json').write_text(json.dumps({'epoch':time.time(),'case':CASE,'resume_start_rounds':record['num_rounds'],'completed_rounds':result['num_rounds'],'result_path':str(destination),'raw_checkpoint':metadata['checkpoint_path']},ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    try:main()
    except Exception as exc:
        update(agent_state='interrupted',judge_state='unavailable',recovery_stage='failed',judgment='上下文恢复失败；原检查点保留：'+type(exc).__name__)
        raise
