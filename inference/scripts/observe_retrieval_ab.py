"""Run the existing GAIA observer with experiment-specific paths and models."""
import os
from pathlib import Path

repo = Path(__file__).resolve().parents[2]
# A run-local profile can be changed for subsequently launched agents without
# replacing an already-running experiment controller.
if not os.environ.get('QUEST_FINAL_ANSWER_PROFILE') and os.environ.get('QUEST_AB_GROUP_ROOT'):
    profile_file = Path(os.environ['QUEST_AB_GROUP_ROOT']) / 'final-answer-profile'
    if profile_file.is_file():
        profile = profile_file.read_text().strip()
        if profile:
            os.environ['QUEST_FINAL_ANSWER_PROFILE'] = profile
source = repo / 'workspace/strict-reproduction/gaia-sft32-27b-2plus2-20261028-r2/scripts/observe-native.py'
code = source.read_text()
# The legacy observer loads shared credentials after inheriting the environment.
# Allow a run-local proxy to override a stale proxy in that shared configuration.
if os.environ.get('QUEST_HTTPS_PROXY_OVERRIDE'):
    old_config = "os.environ.update({k:str(v) for k,v in CFG.items()})"
    if code.count(old_config) != 1:
        raise RuntimeError('upstream observer API configuration changed')
    code = code.replace(old_config, old_config + "\nos.environ['HTTPS_PROXY']=os.environ['QUEST_HTTPS_PROXY_OVERRIDE']\nos.environ['HTTP_PROXY']=os.environ['QUEST_HTTPS_PROXY_OVERRIDE']")
# Preserve the legacy observer while attaching measurements from newer agents.
old_extra = "def extra(kind,loc):\n data={}"
new_extra = """def extra(kind,loc):
 data={}
 if kind=='policy_model':
  if isinstance(loc.get('ttft_seconds'),(int,float)):
   data['ttft_seconds']=loc['ttft_seconds']
  if isinstance(loc.get('context_measurement'),dict):
   data['context_measurement']=safe(loc['context_measurement'])"""
if code.count(old_extra) != 1:
    raise RuntimeError('upstream observer telemetry layout changed')
code = code.replace(old_extra, new_extra)
if os.environ.get('QUEST_AUDIT_SEQ_BASE'):
    old_sequence='SEQ=0;CACHE={}'
    if code.count(old_sequence)!=1:raise RuntimeError('upstream observer sequence layout changed')
    code=code.replace(old_sequence,f"SEQ={int(os.environ['QUEST_AUDIT_SEQ_BASE'])};CACHE={{}}")
if os.environ.get('QUEST_AB_RESUME_MESSAGES')=='true':
    old_resume="'--roll_out_count','1'];runpy.run_path"
    if code.count(old_resume)!=1:raise RuntimeError('upstream observer resume layout changed')
    code=code.replace(old_resume,"'--roll_out_count','1'];sys.argv += ['--resume_from_messages','--resume_overwrite_existing'];runpy.run_path")
old = "ROOT=Path(__file__).resolve().parents[1];PROJECT=ROOT.parents[1];SOURCE=(PROJECT.resolve().parent)"
new = "ROOT=Path(os.environ['QUEST_AB_GROUP_ROOT']);PROJECT=Path(os.environ['QUEST_AB_PROJECT']);SOURCE=PROJECT.parent"
if code.count(old) != 1:
    raise RuntimeError('upstream observer layout changed')
code = code.replace(old, new)
old = " os.environ['VISIT_LOCAL_PROMPT_ENABLED']='true'\n os.environ['LOCAL_PROMPT_MODEL_NAME']='QWEN38-27B-NVFP4'\n os.environ['MEMORY_MODEL_NAME']='openai/QWEN38-MEMORY'\n os.environ['MEMORY_API_BASE']='http://127.0.0.1:18110/v1'\n os.environ['MEMORY_API_KEY']='EMPTY'"
if code.count(old) != 1:
    raise RuntimeError('upstream observer model configuration changed')
code = code.replace(old, " if os.environ.get('QUEST_VISIT_USE_LOCAL_27B') == 'true':\n  os.environ['VISIT_LOCAL_PROMPT_ENABLED']='true'\n else:\n  os.environ.pop('VISIT_LOCAL_PROMPT_ENABLED', None)\n os.environ.pop('MEMORY_LOCAL_PROMPT_ENABLED', None)\n if os.environ.get('QUEST_AB_MEMORY_BASE'):\n  os.environ['MEMORY_ENABLED']='true'\n  os.environ['MEMORY_MODEL_NAME']='openai/QWEN35-BASE'\n  os.environ['MEMORY_API_BASE']=os.environ['QUEST_AB_MEMORY_BASE']\n  os.environ['MEMORY_API_KEY']='EMPTY'\n  os.environ['MEMORY_DISABLE_THINKING']='true'")
if os.environ.get('QUEST_AB_POLICY_BASE') == 'true':
    code = code.replace('QWEN35-SFT10', 'QWEN35-BASE')
if os.environ.get('QUEST_AB_POLICY_MODEL'):
    model = os.environ['QUEST_AB_POLICY_MODEL']
    model_path = os.environ['QUEST_AB_POLICY_MODEL_PATH']
    code = code.replace('QWEN35-SFT10', model).replace("PROJECT/'models/Qwen3.5-4B'", f"Path({model_path!r})")
    code = code.replace('openai/QWEN35-BASE', 'openai/' + model)
if os.environ.get('QUEST_AB_NO_GAIA') == 'true':
    if code.count(' plugin.install()') != 1:
        raise RuntimeError('upstream GAIA plugin wiring changed')
    code = code.replace(' plugin.install()', " os.environ['QUEST_REPAIR_TOOL_JSON']='true'; os.environ['QUEST_SERPER_RATE_LIMIT_ROTATE']='1'; os.environ['MEMORY_RETRY_INVALID_JSON']='true'; os.environ['QUEST_FINAL_ANSWER_RETRIES']='2'  # Non-GAIA run: conservative fixes")
    print('[Tool JSON repair] optional conservative closure repair enabled for this agent', flush=True)
    os.environ['QUEST_REPAIR_TOOL_ARRAY_BRACKET']='true'
    print('[Tool JSON repair] optional single array bracket repair enabled for this agent', flush=True)
    os.environ['VISIT_READER_BOUNDED_RETRIES']='true'
    print('[Reader retry] bounded page retries enabled for this agent', flush=True)
if os.environ.get('QUEST_AB_MAX_TURNS'):
    turns = int(os.environ['QUEST_AB_MAX_TURNS'])
    if not 1 <= turns <= 10000:
        raise ValueError('invalid QUEST_AB_MAX_TURNS')
    for key in ('MAX_LLM_CALL_PER_RUN', 'MAX_TURN'):
        old_setting = f"'{key}':'400'"
        if code.count(old_setting) != 1:
            raise RuntimeError(f'upstream observer {key} configuration changed')
        code = code.replace(old_setting, f"'{key}':'{turns}'")
if os.environ.get('QUEST_AB_MEMORY_THRESHOLD'):
    threshold = int(os.environ['QUEST_AB_MEMORY_THRESHOLD'])
    if threshold < 1:
        raise ValueError('invalid QUEST_AB_MEMORY_THRESHOLD')
    old_setting = "'MEMORY_THRESHOLD':'40000'"
    if code.count(old_setting) != 1:
        raise RuntimeError('upstream observer memory threshold configuration changed')
    code = code.replace(old_setting, f"'MEMORY_THRESHOLD':'{threshold}'")
exec(compile(code, str(source), 'exec'), {'__name__': '__main__', '__file__': str(source)})
