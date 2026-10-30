"""Read-only source/runtime audit for the frozen BrowseComp experiment.

This audit can run before completion. It deliberately does not certify that all
cases have finished or that a local model's semantic judgments are infallible.
"""
import ast
import csv
import hashlib
import json
import random
import subprocess
import time
import urllib.request
import warnings
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
RUN=ROOT/'workspace/strict-reproduction/browsecomp-sft-25pct-pool64-20261029-r1'


def template_value(node):
    if (isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)
            and node.func.attr=='strip' and not node.args and not node.keywords):
        return ast.literal_eval(node.func.value).strip()
    return ast.literal_eval(node)


def audit():
    manifest=json.loads((RUN/'manifest.json').read_text())
    refs=json.loads((RUN/'judge/ground-truth/references.json').read_text())
    state=json.loads((RUN/'status.json').read_text())
    checks={};issues=[]
    source=ROOT/'workspace/strict-reproduction/native-multibench-smoke-20261027-r1/assets/browse_comp_test_set.csv'
    checks['official_dataset_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()==manifest['source_sha256']
    with source.open() as handle:
        checks['official_dataset_row_count']=sum(1 for _ in csv.DictReader(handle))==1266
    checks['sample_reproducible']=manifest['source_indices']==random.Random(0).sample(range(1266),317)
    checks['unique_source_indices']=len(set(manifest['source_indices']))==317
    checks['case_set_complete']=set(state['cases'])=={x['case'] for x in refs} and len(refs)==317
    official=ROOT/'workspace/strict-reproduction/official-dataset-eval-20261028/sources/simple-evals'
    checks['official_revision_matches']=subprocess.check_output(['git','-C',str(official),'rev-parse','HEAD'],text=True).strip()==manifest['official_revision']
    constants={}
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',SyntaxWarning)
        tree=ast.parse((official/'browsecomp_eval.py').read_text())
    for node in tree.body:
        if isinstance(node,ast.Assign):
            for target in node.targets:
                if isinstance(target,ast.Name) and target.id in ['QUERY_TEMPLATE','GRADER_TEMPLATE']:
                    constants[target.id]=template_value(node.value)
    checks['official_query_template_unchanged']=(RUN/'configs/query-template.txt').read_text()==constants['QUERY_TEMPLATE']
    checks['official_grader_template_unchanged']=(RUN/'configs/grader-template.txt').read_text()==constants['GRADER_TEMPLATE']
    for ref in refs:
        item=json.loads((RUN/'configs'/f"{ref['case']}.jsonl").read_text())
        expected=constants['QUERY_TEMPLATE'].format(Question=ref['question'])
        if item.get('answer')!='' or item.get('question')!=ref['prompt'] or ref['prompt']!=expected:
            issues.append({'case':ref['case'],'issue':'agent_input_mismatch_or_nonempty_gold'})
    checks['all_agent_inputs_frozen_and_gold_free']=not issues
    servers=[]
    for gpu,pid,port in [(0,109334,18210),(1,109336,18201),(2,109338,18202),(3,109340,18203),(4,109342,18204)]:
        try:
            argv=Path(f'/proc/{pid}/cmdline').read_bytes().decode().split('\0')
            env=dict(x.split('=',1) for x in Path(f'/proc/{pid}/environ').read_bytes().decode().split('\0') if '=' in x)
            values={k:argv[argv.index(k)+1] if k in argv else None for k in ['--max-num-seqs','--max-model-len','--gpu-memory-utilization','--tensor-parallel-size','--lora-modules']}
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/v1/models',timeout=3) as response:
                models=json.load(response)['data']
            servers.append({'gpu':gpu,'pid':pid,'port':port,'cuda_visible_devices':env.get('CUDA_VISIBLE_DEVICES'),'settings':values,'enforce_eager':'--enforce-eager' in argv,'language_model_only':'--language-model-only' in argv,'models':[{k:m.get(k) for k in ['id','root','parent','max_model_len']} for m in models]})
        except Exception as exc:
            servers.append({'gpu':gpu,'port':port,'error_type':type(exc).__name__})
    checks['five_sft_servers_configured']=len(servers)==5 and all(
        not s.get('error_type') and s['settings']['--max-num-seqs']=='8'
        and s['settings']['--gpu-memory-utilization']=='0.92'
        and s['settings']['--max-model-len']=='65536'
        and s['settings']['--tensor-parallel-size']=='1'
        and s['language_model_only'] and not s['enforce_eager']
        and s['cuda_visible_devices']==str(s['gpu'])
        and {'QWEN35-BASE','QWEN35-SFT10'}<={m['id'] for m in s['models']}
        and any(m['id']=='QWEN35-SFT10' and m['parent']=='QWEN35-BASE'
                and m['root']==s['settings']['--lora-modules'].split('=',1)[1] for m in s['models'])
        for s in servers)
    try:
        with urllib.request.urlopen('http://127.0.0.1:18215/health',timeout=3) as response:
            pool=json.load(response)
        checks['shared_pool_64_workers']=pool.get('workers')==64
    except Exception as exc:
        pool={'error_type':type(exc).__name__};checks['shared_pool_64_workers']=False
    rounds=[]
    for case,row in state['cases'].items():
        if row.get('agent_state')=='terminal' and row.get('result_path'):
            item=json.loads(Path(row['result_path']).read_text().splitlines()[-1])
            rounds.append(item.get('num_rounds'))
    checks['completed_cases_within_100_rounds']=all(isinstance(n,int) and 0<n<=100 for n in rounds)
    active=[]
    for row in state['cases'].values():
        if row['agent_state']!='running':continue
        pid=row['agent_pid']
        try:
            env=dict(x.split('=',1) for x in Path(f'/proc/{pid}/environ').read_bytes().decode().split('\0') if '=' in x)
            active.append({'pid':pid,'page_concurrency':env.get('VISIT_PAGE_CONCURRENCY'),'pool_url':env.get('VISIT_BM25_POOL_URL'),'method':env.get('VISIT_EXPERIMENT_METHOD'),'delivery':env.get('VISIT_EXPERIMENT_DELIVERY'),'memory_base':env.get('QUEST_AB_MEMORY_BASE')})
        except FileNotFoundError:pass
    checks['active_agent_retrieval_settings']=all(a['page_concurrency']=='16' and a['pool_url']=='http://127.0.0.1:18215' and a['method']=='bm25' and a['delivery']=='direct' and str(a['memory_base']).startswith('http://127.0.0.1:') for a in active)
    return {'epoch':time.time(),'scope':'Configuration and source audit; not a completion certificate.','checks':checks,'input_issues':issues,'completed_original_results_checked':len(rounds),'max_completed_rounds':max(rounds) if rounds else None,'server_evidence':servers,'pool_evidence':pool,'active_agent_count_checked':len(active),'active_agent_evidence':active}


if __name__=='__main__':
    data=audit();out=RUN/'checks/configuration-audit.json';tmp=out.with_suffix('.tmp')
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');tmp.replace(out)
    print(json.dumps({'checks':data['checks'],'completed_results':data['completed_original_results_checked'],'active_agents':data['active_agent_count_checked']}))
    raise SystemExit(0 if all(data['checks'].values()) else 1)
