import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'inference'))
from tool_call_repair import append_missing_object_brace as repair
from tool_call_repair import insert_missing_array_bracket as array_repair

def test_one_missing_closing_brace_is_repaired_without_changing_arguments():
 assert repair('{"name":"search","arguments":{"query":["one", "two"]}') == {'name':'search','arguments':{'query':['one','two']}}
 assert repair('{"name":"visit","arguments":{"url":["https://example.com"],"goal":"date"}') == {'name':'visit','arguments':{'url':['https://example.com'],'goal':'date'}}

def test_ambiguous_or_other_cases_are_never_modified():
 for raw in ['{"name":"search","arguments":{"query":["one"]}}','{"name="search", "arguments":{"query":["one"]}','{"name":"search","arguments":{"query":"one"}','{"name":"search","arguments":{"query":["one"]','{"name":"PythonInterpreter","arguments":{}']:
  assert repair(raw) is None

def test_agent_parser_repair_is_opt_in_and_preserves_original_payload(monkeypatch):
 from react_agent import MultiTurnReactAgent
 raw='{"name":"search","arguments":{"query":["example"]}'
 agent=object.__new__(MultiTurnReactAgent)
 monkeypatch.delenv('QUEST_REPAIR_TOOL_JSON',raising=False)
 assert agent._normalize_tool_call(raw)[2] is not None
 monkeypatch.setenv('QUEST_REPAIR_TOOL_JSON','true')
 name,args,error=agent._normalize_tool_call(raw)
 assert (name,args,error)==('search',{'query':['example']},None)


def test_array_repair_preserves_queries_escapes_and_url_goal():
 import json
 for obj in [
  {'name':'search','arguments':{'query':['a "quoted" query with } and ] and \\','second query']}},
  {'name':'visit','arguments':{'goal':'find the year ] }','url':['https://example.com/a?b=1']}},
 ]:
  original=json.dumps(obj);position=original.rfind(']')
  malformed=original[:position]+original[position+1:]
  assert array_repair(malformed)==obj
  assert array_repair(original) is None


def test_array_repair_rejects_ambiguous_or_multi_edit_payloads():
 for raw in [
  '{"name":"search","arguments":{"query":["unterminated}}',
  '{"name":"search","arguments":{"query":["a"}',
  '{"name":"search","arguments":{"query":["a",}}',
  '{"name":"search","arguments":{"query":[1}}',
  '{"name":"search","arguments":{"query":["a"},"extra":1}',
  '{"name":"visit","arguments":{"url":["a"}}',
  '{"name":"visit","arguments":{"url":["a", "goal":"date"}}',
  '{"name":"PythonInterpreter","arguments":{"code":["a"}}',
  '{"name":"search","arguments":{"query":["a"}} trailing',
 ]:
  assert array_repair(raw) is None


def test_agent_array_repair_is_separately_opt_in(monkeypatch):
 from react_agent import MultiTurnReactAgent
 agent=object.__new__(MultiTurnReactAgent)
 raw='{"name":"search","arguments":{"query":["keep this exact query"}}'
 monkeypatch.delenv('QUEST_REPAIR_TOOL_ARRAY_BRACKET',raising=False)
 assert agent._normalize_tool_call(raw)[2] is not None
 monkeypatch.setenv('QUEST_REPAIR_TOOL_ARRAY_BRACKET','true')
 assert agent._normalize_tool_call(raw)==('search',{'query':['keep this exact query']},None)
