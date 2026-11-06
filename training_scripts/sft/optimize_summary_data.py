"""Resumable rule + independent-pass LLM screening; never launches training.

Run --prepare, then --pilot, then --run. The original set is immutable.
The full run reviews all original candidates before filling deficits from the
same task/length strata of the released reserve pool. No partial set is named
as a completed 1024-row dataset.
"""
import argparse
import collections
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import threading
import time
import zlib

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT/'inference'))
sys.path.insert(0, str(ROOT/'training_scripts/sft'))
from inference import native_tools, source_ids
from clean_harness_trajectories import schemas_from_source, sha, file_sha
from replay_cleaning_pilot import search_format
from select_summary1024 import FINAL_PROMPT
from optimization_quality import (evidence_bundle, validate_rubric, validate_review,
                                  RUBRIC_PROMPT, REVIEW_PROMPT, VERIFY_PROMPT)
from original_rubric_quality import (OriginalRubrics, prepare_payload, validate_assessment,
                                    ORIGINAL_REVIEW_PROMPT, ORIGINAL_CHALLENGE_PROMPT, RUNTIME, build_index)
import prompt
import requests


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name+'.', suffix='.tmp')
    with os.fdopen(fd, 'w') as stream: json.dump(obj, stream, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def jsonl(path, rows):
    temp = path.with_suffix('.tmp')
    temp.write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in rows))
    temp.replace(path)


class Pipeline:
    def __init__(self, args):
        os.environ['QUEST_SOURCE_IDS'] = 'true'
        self.args = args; self.out = Path(args.output).resolve(); self.source = Path(args.source).resolve()
        for name in ('records','rules','decisions','rubrics','reviews','sources','logs'):
            (self.out/name).mkdir(parents=True, exist_ok=True)
        if not (self.out/'original-rubric-index.json').exists():
            build_index(self.out,ROOT/'workspace/datasets/QUEST-SFT-Data-Objective-Script/data/train.parquet')
        files = ['inference/source_ids.py','inference/native_tools.py','inference/react_agent.py',
                 'inference/tool_memory.py','inference/session_telemetry.py',
                 'inference/scripts/observe_retrieval_ab.py','training_scripts/sft/run_summary16.py',
                 'training_scripts/sft/regenerate_optimization.py',
                 'training_scripts/sft/tokenize_summary_sessions.py','training_scripts/sft/check_summary_parity.py',
                 'training_scripts/sft/optimization_quality.py','training_scripts/sft/optimize_summary_data.py',
                 'training_scripts/sft/original_rubric_quality.py',str(RUNTIME.relative_to(ROOT))]
        inherit_upstream=getattr(args,'inherit_upstream',False)
        if inherit_upstream:files.append('training_scripts/sft/inherit_upstream_data.py')
        self.contract = {'sources':{f:file_sha(ROOT/f) for f in files}, 'model':'qwen38-27b',
                         'input_file_sha256':file_sha(self.source/'sft1024-summary-native-v2.jsonl'),
                         'mode':'summary', 'training_started':False, 'target':{'objective':768,'openended':256},
                         'review_policy':'original rubric tree and original aggregation; separate task and trajectory gates; two passing assessments; no generated-rubric fallback',
                         'original_rubric_index_sha256':file_sha(self.out/'original-rubric-index.json'),
                         'generation_policy':{'max_attempts_per_question':2,'parallel_runs':2,'timeout_seconds':3600,
                                              'max_policy_calls':100,'memory_threshold':40000},
                         'limitations':['Same model for both reviews, not independent factual certification.',
                                        'Tool summaries are supplied evidence; historical original pages are not verified.']}
        if inherit_upstream:
            self.contract.update(review_policy='inherit user-confirmed upstream task acceptance; local harness checks only; no LLM rejudgment',
                acceptance_basis='user confirmed original SFT release passed upstream acceptance',
                generation_policy={'enabled':False},
                limitations=['No local original-rubric score is claimed for inherited acceptance.',
                             'Known concrete defects remain isolated. Historical raw pages are not independently verified.'])
            if getattr(args,'flexible_mix',False):
                self.contract['target']={'total':1024,'preferred':{'objective':768,'openended':256},
                                         'allow_reallocation':True}
        contract_path=self.out/'contract.json'
        if contract_path.exists() and json.loads(contract_path.read_text()) != self.contract:
            raise RuntimeError('Code/input contract changed; use a new output version.')
        write(contract_path,self.contract)
        self.contract_sha=sha(self.contract)
        self.original_rubrics=OriginalRubrics(self.out)
        self.db=sqlite3.connect((self.source/'pool.sqlite').as_uri()+'?mode=ro',uri=True)
        self.schemas=[s for s in schemas_from_source() if s['function']['name'] in ('search','visit')]
        self.original=list(map(json.loads,(self.source/'sft1024-summary-native-v2.jsonl').read_text().splitlines()))
        self.original_meta={r['metadata']['id']:r['metadata'] for r in self.original}
        self.plan=[]
        for kind in ('objective','openended'):
            rows=list(self.db.execute('SELECT id,q,turns,memory FROM pool WHERE kind=? ORDER BY turns,id',(kind,)))
            for b in range(4):
                part=rows[len(rows)*b//4:len(rows)*(b+1)//4]
                for ident,q,turns,memory in sorted(part,key=lambda x:sha(('optimization-v1',x[0]))):
                    self.plan.append({'id':ident,'question_sha256':q,'kind':kind,'stratum':b,'has_memory':bool(memory)})
        self.plan_by_id={r['id']:r for r in self.plan}
        self.tokenizer=None
        self.locks=collections.defaultdict(threading.Lock)

    def convert(self, meta):
        ident=meta['id']; record_path=self.out/'records'/(ident+'.json'); receipt=self.out/'rules'/(ident+'.json')
        if receipt.exists():
            r=json.loads(receipt.read_text())
            return json.loads(record_path.read_text()) if r['status']=='pass' else None
        raw_meta,blob=self.db.execute('SELECT meta,messages FROM pool WHERE id=?',(ident,)).fetchone()
        metadata=json.loads(raw_meta);metadata['stratum']=meta['stratum']
        messages=json.loads(zlib.decompress(blob));folder=Path(tempfile.mkdtemp(prefix=ident+'-',dir=self.out/'sources'))
        registry=source_ids.SourceRegistry(folder)
        try:
            date=re.search(r'Current date:\s*([^\n]*)',messages[0]['content'])
            messages[0]['content']=native_tools.system_prompt(prompt.SYSTEM_PROMPT)+(date[1] if date else '')
            converted=[registry.context(messages[0],'system'),registry.context(messages[1],'user')]
            pending=None
            for m in messages[2:]:
                if m['role']=='assistant':
                    converted.append(registry.assistant(m))
                    calls=m.get('tool_calls',[]);pending=calls[0]['function'] if calls else None
                else:
                    if pending and pending['name']=='search':body=registry.render(search_format(m['content']))
                    else:
                        args=json.loads(pending['arguments']) if pending else {}
                        urls=args.get('url',[]);urls=[urls] if isinstance(urls,str) else urls
                        body=registry.compact(m['content'],exact_urls=[u for u in urls if u.startswith('http')],origin='page_observation')
                    converted.append(dict(m,content=body))
            converted.insert(-1,{'role':'user','content':FINAL_PROMPT})
            converted=native_tools.prepare_messages(converted)
            answer=json.loads(converted[-1]['content'])['answer']
            registry.validate_final(answer)
            metadata.update(source_map=str(registry.path),quality_status='pending_semantic_review',
                            converted_sha256=sha(converted),tools_sha256=sha(self.schemas),optimization_contract=self.contract_sha)
            row={'messages':converted,'tools':self.schemas,'metadata':metadata}
            bundle=evidence_bundle(row)
            if bundle['rule_issues']:raise ValueError(json.dumps(bundle['rule_issues']))
            if self.tokenizer is None:
                from transformers import AutoTokenizer
                self.tokenizer=AutoTokenizer.from_pretrained(ROOT/'workspace/models/Qwen3.8-27B-NVFP4',local_files_only=True)
            ids=self.tokenizer.apply_chat_template(native_tools.prepare_messages(converted,for_template=True),
                tools=self.schemas,tokenize=True,return_dict=False,add_generation_prompt=False)
            if len(ids)>65536:raise ValueError('overlength_no_truncation')
            row['metadata']['tokens']=len(ids)
            write(record_path,row);write(receipt,{'status':'pass','id':ident,'kind':metadata['kind'],'stratum':metadata['stratum']})
            return row
        except (ValueError,KeyError,TypeError) as exc:
            write(receipt,{'status':'reject','id':ident,'kind':metadata['kind'],'stratum':metadata['stratum'],'reason':str(exc)})
            return None

    def call(self, system, payload, max_tokens=4096):
        response=requests.post(self.args.endpoint.rstrip('/')+'/v1/chat/completions',json={
            'model':'qwen38-27b','messages':[{'role':'system','content':system},
                                         {'role':'user','content':json.dumps(payload,ensure_ascii=False)}],
            'temperature':0,'max_tokens':max_tokens,'chat_template_kwargs':{'enable_thinking':False},
            'response_format':{'type':'json_object'}},timeout=(15,600))
        response.raise_for_status();body=response.json()
        if body['choices'][0]['finish_reason']!='stop':raise ValueError('incomplete_judgment')
        return json.loads(body['choices'][0]['message']['content']),body

    def rubric(self,row):
        key=row['metadata']['question_sha256'];path=self.out/'rubrics'/(key+'.json')
        with self.locks[key]:
            original=self.original_rubrics.lookup(row['metadata'])
            write(path,original)
            return original

    def review(self,row):
        ident=row['metadata']['id'];path=self.out/'decisions'/(ident+'.json')
        if path.exists():
            previous=json.loads(path.read_text())
            if previous.get('contract')!=self.contract_sha:
                raise RuntimeError('Do not reuse a decision from a different review contract')
            if previous['status']!='error':return previous
        decision={'id':ident,'question_sha256':row['metadata']['question_sha256'],'kind':row['metadata']['kind'],
                  'stratum':row['metadata']['stratum'],'status':'review','contract':self.contract_sha,'passes':[]}
        try:
            rubric=self.rubric(row)
            if rubric['status']!='ready':
                decision.update(status='quarantine',reason=rubric.get('reason','original_rubric_unavailable'),
                                task_gate={'status':'quarantine','origin':rubric['origin']},
                                trajectory_gate={'status':'not_reviewed','rules':'pass'})
                write(path,decision);return decision
            decision.update(original_rubric_origin=rubric['origin'],original_tree_sha256=rubric['tree_sha256'],
                            original_rubric_path=str(self.out/'rubrics'/(row['metadata']['question_sha256']+'.json')))
            bundle=evidence_bundle(row);payload=prepare_payload(row,rubric,bundle)
            # Oversized judge inputs are held, never silently truncated.
            if len(json.dumps(payload,ensure_ascii=False))>300000:raise ValueError('judge_input_too_large_no_truncation')
            for phase,system in (('primary',ORIGINAL_REVIEW_PROMPT),('challenge',ORIGINAL_CHALLENGE_PROMPT)):
                accepted=None
                for attempt in range(2):
                    answer,raw=self.call(system,payload,max_tokens=min(12288,max(4096,len(payload['required_leaf_ids'])*180)))
                    receipt={'answer':answer,'raw_response':raw,'input_sha256':sha(payload)}
                    try:
                        assessed=validate_assessment(answer,rubric,payload)
                        verdict=assessed['status'];receipt.update(assessment=assessed)
                    except (ValueError,TypeError,KeyError) as exc:
                        receipt['validation_error']=str(exc)
                        write(self.out/'reviews'/(ident+f'-{phase}-{attempt}.json'),receipt)
                        if attempt==1:raise
                        system += '\nYour output must satisfy original-node coverage and evidence-block references. Previous structural validation failed: '+str(exc)
                        continue
                    write(self.out/'reviews'/(ident+f'-{phase}-{attempt}.json'),receipt)
                    decision['passes'].append({'phase':phase,'verdict':verdict,'receipt':str(self.out/'reviews'/(ident+f'-{phase}-{attempt}.json'))})
                    decision['task_gate']=assessed['task_gate']
                    decision['trajectory_gate']=assessed['trajectory_gate']
                    accepted=verdict;break
                if accepted!='pass':
                    decision['status']=accepted or 'review';break
            else:decision['status']='pass'
        except requests.RequestException as exc:
            decision['status']='error';decision['error']=type(exc).__name__
            write(path,decision)
            raise RuntimeError('Evaluator request failed; stop rather than mislabel data quality') from exc
        except (ValueError,TypeError,KeyError) as exc:
            decision['status']='review';decision['error']=type(exc).__name__+':'+str(exc)[:500]
        write(path,decision)
        return decision

    def accepted(self):
        rows=[];seen=set();counts=collections.Counter()
        decisions={p.stem:json.loads(p.read_text()) for p in (self.out/'decisions').glob('*.json')}
        # Prefer original candidates when both an original and a reserve pass.
        ids=list(self.original_meta)+[r['id'] for r in self.plan if r['id'] not in self.original_meta]
        ids += sorted(set(decisions)-set(ids))
        for ident in ids:
            if ident not in decisions:continue
            path=self.out/'decisions'/(ident+'.json')
            d=decisions[ident];key=(d['kind'],d['stratum']);quota=192 if d['kind']=='objective' else 64
            if d['status']!='pass' or d['question_sha256'] in seen or counts[key]>=quota:continue
            row=json.loads((self.out/'records'/(ident+'.json')).read_text())
            row['metadata']['quality_status']='two_pass_original_rubric_and_trajectory_review'
            row['metadata']['quality_receipt']=str(path)
            rows.append(row);seen.add(d['question_sha256']);counts[key]+=1
        return rows,counts

    def progress(self,stage):
        rows,counts=self.accepted();decisions=[json.loads(p.read_text()) for p in (self.out/'decisions').glob('*.json')]
        rules=[json.loads(p.read_text()) for p in (self.out/'rules').glob('*.json')]
        report={'stage':stage,'selected':len(rows),'target':1024,'reviewed':len(decisions),
                'decision_counts':dict(collections.Counter(d['status'] for d in decisions)),
                'rules':dict(collections.Counter(r['status'] for r in rules)),
                'selected_by_stratum':{f'{k[0]}:{k[1]}':v for k,v in counts.items()},
                'original_reviewed':sum(d['id'] in self.original_meta for d in decisions),
                'training_started':False,'updated_epoch':time.time()}
        write(self.out/'status.json',report);jsonl(self.out/'accepted-partial.jsonl',rows)
        print(json.dumps(report),flush=True);return rows,counts

    def batch(self,metas,stage):
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.args.workers) as pool:
            pending={}
            for meta in metas:
                row=self.convert(meta)
                if row is not None:pending[pool.submit(self.review,row)]=meta['id']
                if len(pending)>=self.args.workers*2:
                    done,_=concurrent.futures.wait(pending,return_when=concurrent.futures.FIRST_COMPLETED)
                    for f in done:f.result();pending.pop(f)
                    self.progress(stage)
            for f in concurrent.futures.as_completed(pending):f.result();self.progress(stage)

    def fill_reserve(self):
        """Keep one executor fed across the reserve, without batch barriers.

        Buffer up to twice the worker count so conversion and progress writes
        can overlap reviews. Recheck quotas before every refill; a bounded
        number of already submitted reviews may finish after a quota is met.
        """
        rows,counts=self.progress('reserve_fill')
        candidates=iter(self.plan);exhausted=False
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.args.workers) as pool:
            pending={}
            while True:
                seen={r['metadata']['question_sha256'] for r in rows}
                while not exhausted and len(rows)<1024 and len(pending)<self.args.workers*2:
                    meta=next(candidates,None)
                    if meta is None:
                        exhausted=True;break
                    key=(meta['kind'],meta['stratum'])
                    if (meta['id'] in self.original_meta or meta['question_sha256'] in seen
                            or counts[key]>=(192 if meta['kind']=='objective' else 64)):
                        continue
                    receipt=self.out/'decisions'/(meta['id']+'.json')
                    if receipt.exists() and json.loads(receipt.read_text())['status']!='error':
                        continue
                    row=self.convert(meta)
                    if row is not None:pending[pool.submit(self.review,row)]=meta['id']
                if not pending:break
                done,_=concurrent.futures.wait(pending,return_when=concurrent.futures.FIRST_COMPLETED)
                for f in done:f.result();pending.pop(f)
                rows,counts=self.progress('reserve_fill')
        return rows,counts

    def execute(self):
        if self.args.prepare:
            for meta in self.original_meta.values():self.convert(meta)
            self.progress('original_rules_complete');return
        if self.args.pilot:
            samples=list(map(json.loads,(self.source/'sample16-aligned-v2.jsonl').read_text().splitlines()))
            self.batch([self.original_meta[r['metadata']['id']] for r in samples],'pilot')
            self.progress('pilot_complete');return
        self.batch(list(self.original_meta.values()),'original_full_review')
        historical=self.out/'reevaluation-ids.json'
        if historical.exists():
            metas=[self.plan_by_id[i] for i in json.loads(historical.read_text())
                   if i not in self.original_meta and i in self.plan_by_id]
            self.batch(metas,'historical_decisions_reevaluation')
            # Previously generated candidates are evidence-bearing records,
            # not raw pool rows, and must also receive new-contract judgments.
            for ident in json.loads(historical.read_text()):
                if ident not in self.plan_by_id and (self.out/'records'/(ident+'.json')).exists():
                    self.review(json.loads((self.out/'records'/(ident+'.json')).read_text()))
        rows,counts=self.fill_reserve()
        if len(rows)!=1024:
            from regenerate_optimization import fill
            fill(self)
            rows,counts=self.progress('regeneration_complete')
            if (self.out/'generation-halted.json').exists():
                self.progress('generation_halted_for_diagnosis');return
        if len(rows)!=1024:
            self.progress('insufficient_qualified_reserve');return
        jsonl(self.out/'candidates1024.jsonl',rows)
        samples=[]
        for kind,n in (('objective',3),('openended',1)):
            for b in range(4):
                group=[r for r in rows if r['metadata']['kind']==kind and r['metadata']['stratum']==b]
                samples.extend(sorted(group,key=lambda r:sha(('optimized-regression',r['metadata']['id'])))[:n])
        for i,r in enumerate(samples):r['metadata']=dict(r['metadata'],case=f'case{i:02d}')
        jsonl(self.out/'sample16-static.jsonl',samples)
        self.progress('qualified_1024_pending_token_export_and_regression')


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--output',required=True)
    p.add_argument('--endpoint',default='http://127.0.0.1:19300');p.add_argument('--workers',type=int,default=4)
    mode=p.add_mutually_exclusive_group(required=True)
    for name in ('prepare','pilot','run'):mode.add_argument('--'+name,action='store_true')
    args=p.parse_args();Pipeline(args).execute()


if __name__=='__main__':main()
