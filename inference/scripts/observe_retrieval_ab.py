"""Run the existing GAIA observer with experiment-specific paths and models."""
import os
from pathlib import Path

repo = Path(__file__).resolve().parents[2]
source = repo / 'workspace/strict-reproduction/gaia-sft32-27b-2plus2-20261028-r2/scripts/observe-native.py'
code = source.read_text()
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
code = code.replace(old, " os.environ.pop('VISIT_LOCAL_PROMPT_ENABLED', None)\n os.environ.pop('MEMORY_LOCAL_PROMPT_ENABLED', None)\n if os.environ.get('QUEST_AB_MEMORY_BASE'):\n  os.environ['MEMORY_ENABLED']='true'\n  os.environ['MEMORY_MODEL_NAME']='openai/QWEN35-BASE'\n  os.environ['MEMORY_API_BASE']=os.environ['QUEST_AB_MEMORY_BASE']\n  os.environ['MEMORY_API_KEY']='EMPTY'\n  os.environ['MEMORY_DISABLE_THINKING']='true'")
if os.environ.get('QUEST_AB_POLICY_BASE') == 'true':
    code = code.replace('QWEN35-SFT10', 'QWEN35-BASE')
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
exec(compile(code, str(source), 'exec'), {'__name__': '__main__', '__file__': str(source)})
