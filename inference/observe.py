#!/usr/bin/env python3
"""Run a QUEST entry point with optional per-stage, append-only JSONL tracing.

This observer does not modify model/tool functions or launch any job by itself.
Use a fresh private output directory for each run. Logs may include full prompts,
webpages, tool results and answers; never publish them without review.
"""
import argparse
import json
import os
from pathlib import Path
import runpy
import sys
import threading
import time
import uuid

MAP = {
    'react_agent.py': {'_run': 'task', 'call_server': 'policy_model', 'custom_call_tool': 'tool', '_call_condenser_directly': 'automatic_memory'},
    'tool_visit.py': {'jina_readpage': 'reader', 'call_server': 'summary'},
    'tool_search.py': {'google_search_with_serp': 'search_query'},
    'tool_memory.py': {'call_api_with_litellm': 'memory_api'},
    'tool_python.py': {'call': 'python'},
    'judge.py': {'call_litellm_for_judgment': 'judge_api'},
}
INPUTS = {'policy_model':['msgs'], 'reader':['url'], 'summary':['msgs'], 'search_query':['query'],
          'memory_api':['messages'], 'automatic_memory':['round_num'],
          'judge_api':['question','predicted_answer','ground_truth'],
          'tool':['tool_name','tool_args'], 'python':['params']}
SENSITIVE_KEYS = {'api_key', 'authorization', 'x-api-key', 'jina_api_keys', 'serper_key_id'}


def safe(value, seen=None, depth=0):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if depth > 24:
        return '[depth limit]'
    seen = seen or set()
    if isinstance(value, (dict, list, tuple)):
        if id(value) in seen:
            return '[cycle]'
        seen = seen | {id(value)}
    if isinstance(value, dict):
        return {str(k): safe(v, seen, depth+1) for k,v in value.items() if str(k).lower() not in SENSITIVE_KEYS}
    if isinstance(value, (list, tuple)):
        return [safe(x, seen, depth+1) for x in value]
    if hasattr(value, 'model_dump'):
        return safe(value.model_dump(), seen, depth+1)
    if hasattr(value, 'dict'):
        return safe(value.dict(), seen, depth+1)
    return repr(value)


class Observer:
    def __init__(self, source, events):
        self.source = source.resolve()
        self.events = events
        self.lock = threading.Lock()
        self.active = {}
        self.stacks = {}
        self.code_cache = {}
        self.secrets = [v for k,v in os.environ.items() if any(x in k.upper() for x in ('KEY','TOKEN','SECRET','PASSWORD')) and len(v) >= 8]
        self.events.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.events, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        os.close(fd)

    def write(self, record):
        record.update(epoch=time.time(), thread_id=threading.get_ident())
        line=json.dumps(record, ensure_ascii=False, default=str)
        for secret in self.secrets:
            line=line.replace(secret, '[REDACTED]')
        with self.lock:
            fd=os.open(self.events, os.O_APPEND | os.O_WRONLY)
            try: os.write(fd, (line+'\n').encode())
            finally: os.close(fd)

    def observe(self, frame, event, arg):
        if event not in ('call','return'):
            return
        code=frame.f_code
        try:
            if code not in self.code_cache:
                name=os.path.basename(code.co_filename)
                kind=MAP.get(name, {}).get(code.co_name)
                source=Path(code.co_filename).resolve() if kind else None
                if source is not None and not source.is_relative_to(self.source):
                    kind=None
                self.code_cache[code]=(source,kind)
            source,kind=self.code_cache[code]
            if not kind:
                return
            tid=threading.get_ident(); key=(tid,id(frame))
            if event=='call':
                ident=uuid.uuid4().hex
                stack=self.stacks.setdefault(tid,[])
                parent=stack[-1] if stack else None
                self.active[key]=(ident,parent,time.monotonic(),kind); stack.append(ident)
                data={k:safe(frame.f_locals[k]) for k in INPUTS.get(kind,[]) if k in frame.f_locals}
                self.write({'event':'span_start','span_id':ident,'parent_id':parent,'kind':kind,'source':str(source),'function':code.co_name,'input':data})
            else:
                item=self.active.pop(key,None)
                if not item:return
                ident,parent,start,kind=item; stack=self.stacks.get(tid,[])
                if ident in stack: stack.remove(ident)
                data={'event':'span_end','span_id':ident,'parent_id':parent,'kind':kind,'seconds':time.monotonic()-start,'output':safe(arg)}
                loc=frame.f_locals
                if kind in ('policy_model','summary','memory_api','judge_api'):
                    response=loc.get('chat_response') or loc.get('response')
                    if response is not None and hasattr(response,'model_dump'):data['api_response']=safe(response)
                if kind=='search_query' and isinstance(loc.get('results'),dict):data['serper_response']=safe(loc['results'])
                if kind=='reader' and loc.get('response') is not None:
                    response=loc['response'];data.update(http_status=getattr(response,'status_code',None),reader_response_text=getattr(response,'text',None))
                if kind=='python' and loc.get('code_result') is not None:data['sandbox_response']=safe(loc['code_result'])
                self.write(data)
        except Exception as exc:
            try:self.write({'event':'observer_error','error_type':type(exc).__name__})
            except Exception:pass


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--events',type=Path,required=True)
    parser.add_argument('--source-root',type=Path,default=Path(__file__).resolve().parent)
    parser.add_argument('script',type=Path)
    parser.add_argument('script_args',nargs=argparse.REMAINDER)
    args=parser.parse_args()
    script=args.script.resolve(strict=True)
    observer=Observer(args.source_root,args.events)
    sys.path.insert(0,str(script.parent));sys.argv=[str(script),*args.script_args]
    observer.write({'event':'process_start','script':str(script)})
    sys.setprofile(observer.observe);threading.setprofile(observer.observe)
    try:
        runpy.run_path(str(script),run_name='__main__')
        observer.write({'event':'process_done'})
    except BaseException as exc:
        observer.write({'event':'process_exception','error_type':type(exc).__name__,'error':str(exc)})
        raise
    finally:
        sys.setprofile(None);threading.setprofile(None)

if __name__=='__main__':main()
