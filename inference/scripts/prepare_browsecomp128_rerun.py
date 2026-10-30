"""Create an isolated rerun with the exact previously sampled 128 cases."""
import argparse,json,shutil
from pathlib import Path
R=Path(__file__).resolve().parents[2];base=R/'workspace/strict-reproduction';source=base/'browsecomp-27b-rerank64-16-128-20261029-r1'
p=argparse.ArgumentParser();p.add_argument('run_id');args=p.parse_args()
if not args.run_id or Path(args.run_id).name!=args.run_id or args.run_id in ('.','..'):p.error('run_id must be a simple directory name')
run=base/args.run_id
run.mkdir(exist_ok=False)
for d in ['configs','checks','judge/ground-truth','results','traces','cache','logs','server-logs']:(run/d).mkdir(parents=True,exist_ok=True)
manifest=json.loads((source/'manifest.json').read_text());cases=manifest['case_ids'];assert len(cases)==128 and len(set(cases))==128
for case in cases:shutil.copy2(source/'configs'/f'{case}.jsonl',run/'configs'/f'{case}.jsonl')
shutil.copy2(source/'configs/grader-template.txt',run/'configs/grader-template.txt');shutil.copy2(source/'judge/ground-truth/references.json',run/'judge/ground-truth/references.json')
manifest.update(sample_source_run=str(source),mtp_tokens=3,max_rounds=200,agent_ports=[19000,19001,19002],reranker_vllm_port=19003,reranker_adapter_port=18314)
(run/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
print(run)
