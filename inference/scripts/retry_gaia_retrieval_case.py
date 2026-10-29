"""Rerun a flagged case without overwriting the original experimental trace."""
import contextlib
import importlib.util
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import time

repo = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo))
from inference.retry_manifest import complete_retry
project = repo/'workspace'
run = project/'strict-reproduction/gaia-retrieval-ab-20261029-r1'
source = project/'strict-reproduction/gaia-sft32-27b-2plus2-20261028-r2'
group, case = sys.argv[1:3] if len(sys.argv)==3 else ('bm25-direct', 'row0003')
methods={'baseline':'', 'bm25-direct':'bm25', 'embedding-direct':'embedding',
         'bm25-reranker-direct':'bm25_reranker', 'hybrid-direct':'hybrid',
         'hybrid-reranker-direct':'hybrid_reranker'}
if group not in methods or not case.startswith('row') or not case[3:].isdigit():
    raise ValueError('invalid retry group or case')
root = run/'retries'/group/case/str(time.time_ns())
for name in ('configs','logs','checks','results','traces','cache'):
    (root/name).mkdir(parents=True,exist_ok=True)
complete_retry(run/'checks/retry-required.json', group, case,
               {'status':'running_retry','retry_root':str(root),'started_at':time.time()})
(root/'configs'/f'{case}.jsonl').write_bytes((source/'configs'/f'{case}.jsonl').read_bytes())
port=int(os.environ.get('QUEST_RETRY_PORT', [18210,18201,18202][int(case[3:])%3]))
if port not in (18210, 18201, 18202):
    raise ValueError('invalid 4B retry endpoint')
(root/'configs'/f'{case}-server_endpoints.conf').write_text(f'HOSTNAME_LIST=127.0.0.1\nPORTS={port}\n')
env = dict(os.environ, QUEST_AB_PROJECT=str(project), QUEST_AB_GROUP_ROOT=str(root), QUEST_AUDIT_CASE=case, QUEST_AUDIT_MODE='agent', VISIT_EXPERIMENT_METHOD=methods[group], VISIT_EXPERIMENT_DELIVERY='summary' if group=='baseline' else 'direct', VISIT_EMBEDDING_URL='http://127.0.0.1:18213', VISIT_RERANKER_URL='http://127.0.0.1:18214', VISIT_EXPERIMENT_AUDIT=str(root/'logs'/f'{case}-retrieval.jsonl'))
with (root/'logs'/f'{case}-agent.stdout.log').open('w') as output:
    rc = subprocess.call([str(project/'env/bin/python'),'-u',str(repo/'inference/scripts/observe_retrieval_ab.py')],env=env,cwd=root,stdout=output,stderr=subprocess.STDOUT)
log = (root/'logs'/f'{case}-agent.stdout.log').read_text(errors='replace')
if re.search(r'Summary Content \[visit\] Error:.*127\.0\.0\.1.*Read timed out|All Jina keys are exhausted or invalid', log):
    raise RuntimeError('retrieval or reader service unavailable again; retry remains unscored')
files = list((root/'results'/case).rglob('iter1.jsonl'))
if rc or len(files)!=1:
    raise RuntimeError(f'retry failed: exit={rc}, results={len(files)}')
record = json.loads(files[0].read_text().splitlines()[-1]); answer=record.get('prediction')
references = json.loads((source/'judge/ground-truth/gaia-103-org.json').read_text())
matching = [x for x in references if x['Question']==record.get('question')]
if len(matching)!=1 or not isinstance(answer,str) or not answer.strip() or answer.lower() in ('no answer found.','answer not found.'):
    raise RuntimeError('retry has no unique reference or final answer')
scorer_source = project/'strict-reproduction/official-sources/gaia-leaderboard'
if subprocess.check_output(['git','-C',str(scorer_source),'rev-parse','HEAD'],text=True).strip()!='9f133d71362e77b3539f1514f31b9c101a545fec':
    raise RuntimeError('official scorer revision mismatch')
spec=importlib.util.spec_from_file_location('gaia_scorer',scorer_source/'scorer.py');scorer=importlib.util.module_from_spec(spec);spec.loader.exec_module(scorer)
with (root/'logs'/'score.log').open('w') as output, contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
    correct=bool(scorer.question_scorer(answer,matching[0]['answer']))
path=run/'checks/retry-required.json'
complete_retry(path, group, case, {'status':'completed','is_correct':correct,'result_path':str(files[0]),'retry_root':str(root),'completed_at':time.time()})
print('retry complete',group,case,'correct',correct,flush=True)
