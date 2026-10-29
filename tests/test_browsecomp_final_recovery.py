import importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];spec=importlib.util.spec_from_file_location('recover_final',ROOT/'inference/scripts/recover_browsecomp_final_answers.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def test_only_old_100_turn_unanswered_tool_call_is_eligible():
 item={'num_rounds':100,'termination':'answer not found.','messages':[{'content':'<tool_call>{"name":"search","arguments":{}}</tool_call>'}]}
 assert m.eligible(item,'old logs')
 assert not m.eligible(item,'[Final answer] Retrying final-answer format')
 assert not m.eligible(dict(item,num_rounds=99),'old logs')
 assert not m.eligible(dict(item,messages=[{'content':'Exact Answer: verified\n'}]),'old logs')
