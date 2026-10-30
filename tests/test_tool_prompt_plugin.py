import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'inference'))
from tool_prompt_plugin import apply, PYTHON_SCHEMA, OLD_FORMAT

PROFILE=ROOT/'inference/tool_prompts/portable_v1.json'

def make_prompt(names=('search','visit','PythonInterpreter')):
    schemas=[PYTHON_SCHEMA if name=='PythonInterpreter' else {'type':'function','function':{'name':name,'parameters':{'type':'object'}}} for name in names]
    return 'You may call one or more functions to assist with the user query.\n<tools>\n'+'\n'.join(json.dumps(s) for s in schemas)+'\n</tools>\n'+OLD_FORMAT

def test_profiles_render_valid_schemas_and_examples():
    result=apply(make_prompt(),PROFILE)
    body=result.split('<tools>\n',1)[1].split('\n</tools>',1)[0]
    assert [json.loads(line)['function']['name'] for line in body.splitlines()]==['search','visit','PythonInterpreter']
    assert '{"name": "search", "arguments":' in result
    assert '{"name": "visit", "arguments":' in result
    assert 'one function at a time' in result
    assert '<args-json-object>' not in result

def test_examples_only_for_available_tools():
    result=apply(make_prompt(('search',)),PROFILE)
    assert '{"name": "search", "arguments":' in result
    assert '{"name": "visit", "arguments":' not in result
    assert 'PythonInterpreter' not in result

def test_v2_contrastive_examples_filter_disabled_tools():
    result=apply(make_prompt(('search',)),ROOT/'inference/tool_prompts/portable_v2.json')
    assert 'WRONG JSON (do not copy)' in result
    assert 'The outer JSON object is not closed' in result
    assert 'url must be an array even when there is one URL' not in result
    assert result.count('<tool_call>\n') == 1

def test_v1_has_no_negative_examples():
    assert 'WRONG JSON (do not copy)' not in apply(make_prompt(),PROFILE)
