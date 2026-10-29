import importlib.util,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('bcmetrics',ROOT/'inference/scripts/publish_browsecomp25_metrics.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def test_original_json_and_repair_are_counted_separately(tmp_path,monkeypatch):
 run=tmp_path/'run';(run/'logs').mkdir(parents=True);(run/'checks').mkdir()
 (run/'status.json').write_text(json.dumps({'cases':{'row0000':{'agent_state':'running','judge_state':'pending'},'row0001':{'agent_state':'running','judge_state':'pending'}}}))
 (run/'logs/row0000-agent.stdout.log').write_text('old process\n')
 (run/'logs/row0001-agent.stdout.log').write_text('[Tool JSON repair] optional conservative closure repair enabled for this agent\n[Tool JSON repair] appended one missing closing brace; original tool call retained\n')
 for case,content in [('row0000','<tool_call>{"name":"search","arguments":{"query":["a"]}}</tool_call>'),('row0001','<tool_call>{"name":"search","arguments":{"query":["a"]}</tool_call>')]:
  (run/f'logs/{case}-agent-events.jsonl').write_text(json.dumps({'event':'span_end','kind':'policy_model','output':content})+'\n')
 monkeypatch.setattr(module,'RUN',run);monkeypatch.setattr(module,'R',tmp_path)
 d=module.calc();assert d['counts']['tool_attempts']==2 and d['counts']['json_valid']==1 and d['counts']['repair_actions']==1
 assert d['repair_phases']['marker_not_recorded']['json_valid']==1
 assert d['repair_phases']['repair_marker_enabled']['attempts']==1 and d['repair_phases']['repair_marker_enabled'].get('json_valid',0)==0

def test_batched_search_error_is_not_hidden_by_earlier_success():
 assert module.explicit_tool_error('first result\n\n[Search Error] HTTP 429','search')
 assert not module.explicit_tool_error('first result\n\n[Search Error] HTTP 429','visit')


def test_array_repairs_do_not_count_as_raw_valid_json(tmp_path,monkeypatch):
 run=tmp_path/'run';(run/'logs').mkdir(parents=True);(run/'checks').mkdir()
 (run/'status.json').write_text(json.dumps({'cases':{'row0000':{'agent_state':'running','judge_state':'pending'}}}))
 (run/'logs/row0000-agent.stdout.log').write_text('[Tool JSON repair] optional conservative closure repair enabled for this agent\n[Tool JSON repair] optional single array bracket repair enabled for this agent\n[Tool JSON repair] inserted one missing array bracket; original tool call retained\n')
 (run/'logs/row0000-agent-events.jsonl').write_text(json.dumps({'event':'span_end','kind':'policy_model','output':'<tool_call>{"name":"search","arguments":{"query":["a"}}</tool_call>'})+'\n')
 monkeypatch.setattr(module,'RUN',run);monkeypatch.setattr(module,'R',tmp_path)
 d=module.calc();c=d['counts']
 assert c['tool_attempts']==1 and c.get('json_valid',0)==0
 assert c['repair_actions']==c['repair_array_bracket_actions']==1 and c['repair_brace_actions']==0
 assert c['array_bracket_repair_enabled_cases']==1


def test_truncated_judge_diagnostic_is_not_a_completed_second_verdict(tmp_path,monkeypatch):
 run=tmp_path/'run';(run/'logs').mkdir(parents=True);(run/'checks').mkdir()
 (run/'status.json').write_text(json.dumps({'cases':{}}))
 for case in ['row0000','row0001']:
  (run/f'checks/{case}-local-judge.json').write_text(json.dumps({'is_correct':False}))
 (run/'checks/judge-equivalence-diagnostics.json').write_text(json.dumps({'cases':[{'case':'row0000','is_correct':True,'finish_reason':'length'},{'case':'row0001','is_correct':True,'finish_reason':'stop'}]}))
 (run/'checks/judge-review-queue.json').write_text(json.dumps({'cases':[{'case':'row0001'}],'unreviewed':0,'unresolved':1}))
 monkeypatch.setattr(module,'RUN',run);monkeypatch.setattr(module,'R',tmp_path)
 c=module.calc()['counts']
 assert c['judge_diagnostic_compared']==c['judge_diagnostic_disagreements']==1
 assert c['judge_review_unresolved']==1


def test_completed_recovery_stays_counted_after_authoritative_state_merge(tmp_path,monkeypatch):
 run=tmp_path/'run';(run/'logs').mkdir(parents=True);(run/'checks').mkdir()
 retry=run/'checks/row0000-local-judge-retry.json';retry.write_text(json.dumps({'status':'scored','is_correct':True}))
 (run/'status.json').write_text(json.dumps({'cases':{'row0000':{'agent_state':'terminal','judge_state':'scored','is_correct':True,'judge_recovery_path':str(retry)}}}))
 monkeypatch.setattr(module,'RUN',run);monkeypatch.setattr(module,'R',tmp_path)
 c=module.calc()['counts']
 assert c['scored']==c['correct']==c['judge_recovered']==1
