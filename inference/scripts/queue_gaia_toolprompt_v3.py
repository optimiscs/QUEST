"""Wait for the V1 run to finish before submitting the V3 full comparison."""
import fcntl,json,os,subprocess,sys
from pathlib import Path
repo=Path(__file__).resolve().parents[2]
run=repo/'workspace/strict-reproduction/gaia-bm25-5gpu-base-toolprompt-v1-20261029-r1'
with (run/'controller.lock').open('a+') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX)
 status=json.loads((run/'status.json').read_text())
 if any(x.get('agent_state')!='terminal' for x in status['cases'].values()):
  raise RuntimeError('V1 controller exited before all samples became terminal')
 env=dict(os.environ,QUEST_GAIA_RUN_ID='gaia-bm25-5gpu-base-toolprompt-v3-20261029-r1',QUEST_TOOL_PROMPT_PROFILE=str(repo/'inference/tool_prompts/portable_v3.json'))
 target=repo/'workspace/strict-reproduction'/env['QUEST_GAIA_RUN_ID'];target.mkdir(parents=True,exist_ok=True)
 with (target/'controller.log').open('a') as output:
  proc=subprocess.Popen([sys.executable,'-u',str(repo/'inference/scripts/run_gaia_bm25_5gpu.py')],env=env,cwd=repo,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
 print('Started V3 controller',proc.pid,flush=True)
 env=dict(os.environ,QUEST_COMPARISON_ORIGINAL=run.name,QUEST_COMPARISON_OPTIMIZED=target.name,QUEST_COMPARISON_OUTPUT=str(repo/'web/trace-viewer/datasets/gaia-toolprompt-v1-v3-comparison.json'))
 with (target/'comparison.log').open('a') as output:
  proc=subprocess.Popen([sys.executable,'-u',str(repo/'inference/scripts/publish_gaia_toolprompt_comparison.py')],env=env,cwd=repo,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
 print('Started V1/V3 metrics publisher',proc.pid,flush=True)
