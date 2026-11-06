"""Read-only audit of a static selection against the current serving harness."""
import collections
import concurrent.futures
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import zlib

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'training_scripts/sft'));sys.path.insert(0,str(ROOT))
from optimize_summary_data import Pipeline,write,sha
from clean_harness_trajectories import schemas_from_source,file_sha
from inference import native_tools
from inherit_upstream_data import verify_conversion
from tokenize_summary_sessions import policy_views


def main():
    import requests
    from jsonschema import validate
    from transformers import AutoTokenizer
    source_file=Path(sys.argv[1]).resolve();out=Path(sys.argv[2]).resolve()
    os.environ['QUEST_SOURCE_IDS']='true'
    for name in ('records','rules','sources'):(out/name).mkdir(parents=True,exist_ok=True)
    rows=[json.loads(line) for line in source_file.open()]
    tokenizer_path=source_file.parent/'tokenizer'
    if not tokenizer_path.is_dir():tokenizer_path=ROOT/'workspace/models/Qwen3.8-27B-NVFP4'
    tokenizer=AutoTokenizer.from_pretrained(tokenizer_path,local_files_only=True)
    p=Pipeline.__new__(Pipeline);p.out=out;p.source=ROOT/'workspace/strict-reproduction/sft-summary1024-20261101-r1'
    p.db=sqlite3.connect((p.source/'pool.sqlite').as_uri()+'?mode=ro',uri=True)
    p.schemas=[s for s in schemas_from_source() if s['function']['name'] in ('search','visit')]
    p.contract_sha='audit-only';p.tokenizer=tokenizer
    checks=[];sessions=[];started=time.time()
    def remote_check(ident,index,payload,local):
        response=requests.post('http://127.0.0.1:19300/tokenize',json=payload,timeout=(10,120))
        response.raise_for_status();remote=response.json()['tokens']
        return {'id':ident,'assistant_index':index,'equal':local==remote,'tokens':len(local),
                'local_sha256':sha(local),'remote_sha256':sha(remote)}
    def progress():
        write(out/'progress.json',{'sessions_checked':len(sessions),'total':len(rows),
                                  'prefixes_checked':len(checks),'seconds':time.time()-started})
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        pending=set()
        for row in rows:
            ident=row['metadata']['id'];result={'id':ident,'protocol':'pass','rebuild':'pending',
                                               'conversion':'pending','target_encoding':'pending'}
            try:
                if row['tools']!=p.schemas:raise ValueError('tool_schema_mismatch')
                waiting=None;seen_calls=set()
                for message in row['messages']:
                    calls=message.get('tool_calls',[])
                    if calls:
                        if waiting or len(calls)!=1:raise ValueError('invalid_call_pairing')
                        call=calls[0]
                        if call['id'] in seen_calls:raise ValueError('duplicate_call_id')
                        seen_calls.add(call['id'])
                        schema=next(s for s in p.schemas if s['function']['name']==call['function']['name'])
                        validate(json.loads(call['function']['arguments']),schema['function']['parameters'])
                        waiting=call['id']
                    elif message['role']=='tool':
                        if message.get('tool_call_id')!=waiting or not waiting:raise ValueError('unpaired_tool_result')
                        waiting=None
                    elif waiting:raise ValueError('missing_tool_result')
                if waiting:raise ValueError('missing_tool_result')
                rebuilt=p.convert(row['metadata'])
                if rebuilt is None:raise ValueError('current_converter_rejects')
                if rebuilt['messages']!=row['messages'] or rebuilt['tools']!=row['tools']:
                    raise ValueError('current_rebuild_differs')
                result['rebuild']='identical'
                original=json.loads(zlib.decompress(p.db.execute('SELECT messages FROM pool WHERE id=?',(ident,)).fetchone()[0]))
                try:verify_conversion(original,row);result['conversion']='pass'
                except (ValueError,KeyError,TypeError) as exc:result['conversion']='warning';result['conversion_warning']=str(exc)
                maximum=0;targets=0
                for index,messages,final,tools in policy_views(row):
                    formatted=native_tools.prepare_messages(messages,for_template=True)
                    kw={'tools':tools,'enable_thinking':not final}
                    prefix=tokenizer.apply_chat_template(formatted[:-1],tokenize=False,add_generation_prompt=True,**kw)
                    complete=tokenizer.apply_chat_template(formatted,tokenize=False,add_generation_prompt=False,**kw)
                    if not complete.startswith(prefix):raise ValueError('target_not_prefix_extension')
                    local=tokenizer.encode(prefix,add_special_tokens=False)
                    target=tokenizer.encode(complete[len(prefix):],add_special_tokens=False)
                    if not target:raise ValueError('empty_training_target')
                    maximum=max(maximum,len(local)+len(target));targets+=1
                    if maximum>65536:raise ValueError('overlength')
                    payload={'model':'qwen38-27b','messages':native_tools.prepare_messages(messages[:-1]),
                        'tools':tools,'add_generation_prompt':True,'add_special_tokens':False,
                        'chat_template_kwargs':{'enable_thinking':not final}}
                    pending.add(pool.submit(remote_check,ident,index,payload,local))
                    if len(pending)>=32:
                        done,pending=concurrent.futures.wait(pending,return_when=concurrent.futures.FIRST_COMPLETED)
                        checks.extend(f.result() for f in done)
                result.update(target_encoding='pass',max_tokens=maximum,assistant_targets=targets)
            except Exception as exc:
                result.update(protocol='failed',error=type(exc).__name__+':'+str(exc))
            sessions.append(result)
            if len(sessions)%20==0:progress()
        checks.extend(f.result() for f in concurrent.futures.as_completed(pending))
    report={'scope':'all static policy prefixes of the supplied selection; no live task rollout or semantic rejudgment',
            'source_file':str(source_file),'source_file_sha256':file_sha(source_file),
            'sessions':len(rows),'protocol_pass':sum(r['protocol']=='pass' for r in sessions),
            'identical_current_rebuild':sum(r['rebuild']=='identical' for r in sessions),
            'conversion_counts':dict(collections.Counter(r['conversion'] for r in sessions)),
            'target_encoding_pass':sum(r['target_encoding']=='pass' for r in sessions),
            'checked_prefixes':len(checks),'all_prefixes_equal':all(c['equal'] for c in checks),
            'max_tokens':max((r.get('max_tokens',0) for r in sessions),default=0),
            'model':'qwen38-27b','mode':'summary','training_started':False,
            'tokenizer_path':str(tokenizer_path),
            'chat_template_sha256':file_sha(tokenizer_path/'chat_template.jinja'),
            'harness_hashes':{s:file_sha(ROOT/s) for s in ('inference/native_tools.py','inference/source_ids.py','inference/react_agent.py')},
            'seconds':time.time()-started,'session_checks':sessions,'prefix_checks':checks}
    write(out/'report.json',report);progress()
    print(json.dumps({k:v for k,v in report.items() if k not in ('session_checks','prefix_checks')}),flush=True)


if __name__=='__main__':main()
