import json,random,importlib.util
import pytest
from pathlib import Path
R=Path(__file__).resolve().parents[1];spec=importlib.util.spec_from_file_location('bc_runner',R/'inference/scripts/run_browsecomp25_sft.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

def test_verdict_only_accepts_explicit_official_result():
 assert mod.parse_verdict('reasoning: matches\ncorrect: yes\nconfidence: 99') is True
 assert mod.parse_verdict('reasoning: mismatch\ncorrect: no') is False
 assert mod.parse_verdict('I cannot judge.') is None

def test_frozen_subset_and_no_answer_in_agent_configs():
 root=R/'workspace/strict-reproduction/browsecomp-sft-25pct-pool64-20261029-r1'
 if not (root/'manifest.json').is_file() or not (root/'judge/ground-truth/references.json').is_file():
  pytest.skip('private experiment fixtures are not installed')
 manifest=json.loads((root/'manifest.json').read_text());refs=json.loads((root/'judge/ground-truth/references.json').read_text())
 assert manifest['sample_count']==317 and manifest['full_count']==1266
 assert manifest['source_indices']==random.Random(0).sample(range(1266),317)
 for ref in refs:
  row=json.loads((root/'configs'/f"{ref['case']}.jsonl").read_text())
  assert row['answer']=='' and row['question']==ref['prompt'] and ref['answer']

def test_local_judge_retries_only_unparseable_output_and_keeps_raw(tmp_path,monkeypatch):
 from types import SimpleNamespace
 (tmp_path/'configs').mkdir();(tmp_path/'checks').mkdir()
 (tmp_path/'configs/grader-template.txt').write_text('{question}|{correct_answer}|{response}')
 result=tmp_path/'result.jsonl';result.write_text(json.dumps({'messages':[{'role':'assistant','content':'<think>private thoughts</think>actual response'}]})+'\n')
 replies=iter(['reasoning: mismatch','correct: no']);calls=[]
 def create(**kwargs):calls.append(kwargs);return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=next(replies)))])
 monkeypatch.setattr(mod,'RUN',tmp_path);monkeypatch.setattr(mod,'OpenAI',lambda **kw:SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
 out=mod.judge('row0000',12345,{'question':'Q','answer':'A'},str(result),'local-judge-retry')
 assert out['status']=='scored' and out['is_correct'] is False
 assert out['raw']=='reasoning: mismatch' and out['format_retry_raw']=='correct: no'
 assert len(calls)==2 and (tmp_path/'checks/row0000-local-judge-retry.json').exists()
 assert 'actual response' in calls[0]['messages'][0]['content'] and 'private thoughts' not in calls[0]['messages'][0]['content']
 assert out['response_filter']=='visible_final_only' and out['graded_response']=='actual response'


def test_judge_input_excludes_thoughts_and_protocol_tool_queries():
 assert mod.visible_judge_response({'messages':[{'content':'<think>Secret Gold</think>Exact Answer: Other'}]})=='Exact Answer: Other'
 assert mod.visible_judge_response({'messages':[{'content':'<think>Secret Gold without a closing tag'}]})==''
 assert mod.visible_judge_response({'messages':[{'content':'<tool_call>{"name":"search","arguments":{"query":["Secret Gold"]}}</tool_call>'}]})==''
 assert mod.visible_judge_response({'messages':[{'content':'<think>candidate</think><answer>final</answer>\nConfidence: 90%'}]})=='<answer>final</answer>\nConfidence: 90%'
