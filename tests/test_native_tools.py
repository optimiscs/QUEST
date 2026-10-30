import copy
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'inference'))
os.environ.setdefault('VISIT_CACHE_ENABLED', 'false')
os.environ.setdefault('SEARCH_CACHE_ENABLED', 'false')
import native_tools
import react_agent


def reply(name=None, arguments=None, content=None, finish='tool_calls', call_id='call_1'):
    calls = [SimpleNamespace(id=call_id, function=SimpleNamespace(
        name=name, arguments=arguments))] if name else None
    return SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=content, tool_calls=calls), finish_reason=finish)])


@pytest.fixture
def schemas():
    return native_tools.tool_schemas(react_agent.TOOL_MAP)


@pytest.mark.parametrize('name,args', [
    ('search', {'query': ['a "quote"', '中文\\path']}),
    ('visit', {'url': ['https://example.com/a?x=1&y=2'], 'goal': 'find date'}),
    ('PythonInterpreter', {'code': 'text = "a\\nb"\nprint(text)\nprint("</code>")'}),
])
def test_arguments_round_trip_without_text_repair(schemas, name, args):
    response = reply(name, json.dumps(args)).choices[0]
    native = native_tools.NativeResponse(response.message, response.finish_reason)
    executed = []
    output = native_tools.execute_calls(native, schemas, lambda n, a: executed.append((n, a)) or 'ok')
    assert executed == [(name, args)]
    assert output == [{'role': 'tool', 'tool_call_id': 'call_1', 'content': 'ok'}]
    assert json.loads(native.message['tool_calls'][0]['function']['arguments']) == args


@pytest.mark.parametrize('name,args', [
    ('search', '{"query":["missing brace"]'),
    ('search', '{"query":"not an array"}'),
    ('search', '{"query":[]}'),
    ('search', '{"query":["x"],"extra":true}'),
    ('search', '{"query":["x"],"query":["y"]}'),
    ('visit', '{"url":["https://example.com"]}'),
    ('visit', '{"url":"https://example.com","goal":"x"}'),
    ('PythonInterpreter', '{}'),
    ('PythonInterpreter', '{"code":null}'),
    ('PythonInterpreter', '{"code":NaN}'),
    ('unknown', '{}'),
])
def test_invalid_calls_return_paired_error_without_execution(schemas, name, args):
    c = reply(name, args).choices[0]
    native = native_tools.NativeResponse(c.message, c.finish_reason)
    output = native_tools.execute_calls(native, schemas, lambda *_: pytest.fail('must not execute'))
    assert output[0]['tool_call_id'] == 'call_1'
    assert output[0]['content'].startswith('[Tool Error]')


def test_truncated_call_is_not_executed_even_if_json_is_valid(schemas):
    c = reply('search', '{"query":["x"]}', finish='length').choices[0]
    output = native_tools.execute_calls(native_tools.NativeResponse(c.message, c.finish_reason),
                                        schemas, lambda *_: pytest.fail('truncated call'))
    assert 'truncated' in output[0]['content']


def test_native_prompt_ignores_legacy_profile_and_disabled_tools(monkeypatch):
    monkeypatch.setenv('QUEST_NATIVE_TOOL_CALLS', 'true')
    monkeypatch.setenv('QUEST_TOOL_PROMPT_PROFILE', '/does/not/exist')
    monkeypatch.setenv('DISABLE_VISIT_TOOL', 'true')
    prompt = react_agent.build_system_prompt(True)
    assert '<tools>' not in prompt and '<tool_call>' not in prompt and '<code>' not in prompt
    assert 'visit tool is unavailable' in prompt
    reduced = {k: v for k, v in react_agent.TOOL_MAP.items() if k not in {'visit', 'PythonInterpreter'}}
    assert [s['function']['name'] for s in native_tools.tool_schemas(reduced)] == ['search']


def agent_with_api(monkeypatch, tmp_path, responses, max_rounds=7):
    monkeypatch.setenv('QUEST_NATIVE_TOOL_CALLS', 'true')
    monkeypatch.delenv('QUEST_DEEPSEEK_TEACHER', raising=False)
    monkeypatch.setenv('MEMORY_ENABLED', 'false')
    monkeypatch.setenv('TASK_LOG_DIR', str(tmp_path))
    monkeypatch.setattr(react_agent, 'MAX_LLM_CALL_PER_RUN', max_rounds)
    pending = iter(responses)
    requests = []
    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=self)
        def create(self, **kwargs):
            requests.append(copy.deepcopy(kwargs))
            return next(pending)
    monkeypatch.setattr(react_agent, 'OpenAI', FakeOpenAI)
    agent = react_agent.MultiTurnReactAgent(llm={'generate_cfg': {}, 'model_path': 'unused'})
    agent._load_server_endpoints = lambda: (['127.0.0.1'], [18000], 'test')
    agent.count_tokens = lambda _: 100
    return agent, requests


def test_three_tools_native_api_history_and_final_answer(monkeypatch, tmp_path):
    responses = [
        reply('search', '{"query":["example"]}', call_id='s'),
        reply('visit', '{"url":["https://example.com"],"goal":"facts"}', call_id='v'),
        reply('PythonInterpreter', '{"code":"print(1 + 1)"}', call_id='p'),
        reply(content='<answer>2</answer>', finish='stop'),
        reply(content='{"answer":"2"}', finish='stop'),
    ]
    agent, requests = agent_with_api(monkeypatch, tmp_path, responses)
    executed = []
    agent.custom_call_tool = lambda n, a: executed.append((n, a)) or 'evidence'
    result = agent._run({'item': {'question': 'test', 'answer': '2'}}, 'test-model')
    assert result['prediction'] == '2'
    assert [n for n, _ in executed] == ['search', 'visit', 'PythonInterpreter']
    assert [m['tool_call_id'] for m in result['messages'] if m['role'] == 'tool'] == ['s', 'v', 'p']
    assert any(m['role'] == 'tool' for m in requests[-1]['messages'])
    assert all(r['tool_choice'] == 'auto' and r['parallel_tool_calls'] is False and 'stop' not in r for r in requests[:-1])
    assert requests[-1]['tool_choice'] == 'none'
    assert all(s['function']['strict'] for s in requests[0]['tools'])
    assert json.loads(json.dumps(result)) == result  # persisted messages retain tool IDs and arguments


def test_finalizer_disables_native_tools(monkeypatch, tmp_path):
    agent, requests = agent_with_api(monkeypatch, tmp_path, [
        reply('search', '{"query":["x"]}'), reply(content='{"answer":"done"}', finish='stop')], max_rounds=4)
    agent.custom_call_tool = lambda *_: 'evidence'
    result = agent._run({'item': {'question': 'test', 'answer': 'done'}}, 'test-model')
    assert result['prediction'] == 'done'
    assert [r['tool_choice'] for r in requests] == ['auto', 'none']


def test_native_mode_does_not_execute_prose_calls(monkeypatch, tmp_path):
    agent, requests = agent_with_api(monkeypatch, tmp_path, [
        reply(content='<tool_call>{"name":"search","arguments":{"query":["x"]}}</tool_call>'),
        reply(content='<answer>done</answer>', finish='stop'),
        reply(content='{"answer":"done"}', finish='stop')])
    agent.custom_call_tool = lambda *_: pytest.fail('text is not a tool call')
    agent._run({'item': {'question': 'test', 'answer': 'done'}}, 'test-model')
    assert any('not executed' in str(m.get('content','')) for m in requests[-1]['messages'])


def test_hide_results_keeps_native_pairs(monkeypatch, tmp_path):
    agent, _ = agent_with_api(monkeypatch, tmp_path, [])
    agent._save_memory_log = lambda *a: None
    agent._save_trajectory_for_distillation = lambda *a, **k: None
    agent._init_thread_state()
    messages = [{'role': 'system', 'content': 's'}, {'role': 'user', 'content': 'q'}]
    for i in range(2):
        c = reply('search', '{"query":["x"]}', call_id=str(i)).choices[0]
        messages.append(native_tools.assistant_message(native_tools.NativeResponse(c.message)))
        messages.append({'role': 'tool', 'tool_call_id': str(i), 'content': 'evidence ' + str(i)})
    agent._hide_old_tool_results(messages)
    assert messages[3]['tool_call_id'] == '0'
    assert 'omitted' in messages[3]['content']
    assert messages[5]['content'] == 'evidence 1'


def test_invalid_call_can_be_replayed_without_corrupting_saved_trajectory(monkeypatch, tmp_path):
    agent, requests = agent_with_api(monkeypatch, tmp_path, [
        reply('search', '{"query":["broken"]'),
        reply(content='<answer>done</answer>', finish='stop'),
        reply(content='{"answer":"done"}', finish='stop')])
    agent.custom_call_tool = lambda *_: pytest.fail('invalid call')
    result = agent._run({'item': {'question': 'test', 'answer': 'done'}}, 'test-model')
    assert result['messages'][2]['tool_calls'][0]['function']['arguments'] == '{"query":["broken"]'
    assert requests[1]['messages'][2]['tool_calls'][0]['function']['arguments'] == '{}'
    assert requests[1]['messages'][3]['role'] == 'tool'


def test_qwen_template_accepts_native_history(schemas):
    from transformers import AutoTokenizer
    model_path = ROOT / 'workspace/models/Qwen3.5-4B'
    if not model_path.exists():
        pytest.skip('local Qwen tokenizer is not installed')
    tokenizer = AutoTokenizer.from_pretrained(str(model_path), local_files_only=True)
    c = reply('PythonInterpreter', json.dumps({'code': 'print("hello")'})).choices[0]
    history = [{'role': 'user', 'content': 'Run Python'},
               native_tools.assistant_message(native_tools.NativeResponse(c.message)),
               {'role': 'tool', 'tool_call_id': 'call_1', 'content': 'hello'}]
    rendered = tokenizer.apply_chat_template(native_tools.prepare_messages(history, for_template=True),
                                             tools=schemas, tokenize=False)
    assert 'print("hello")' in rendered
    assert '<parameter=code>' in rendered
    assert 'hello' in rendered


def test_multiple_calls_are_all_paired_even_after_a_tool_error(schemas):
    first = reply('search', '{"query":["x"]}', call_id='a').choices[0].message
    second = reply('PythonInterpreter', '{"code":"print(2)"}', call_id='b').choices[0].message
    first.tool_calls += second.tool_calls
    seen = []
    def dispatch(name, args):
        seen.append(name)
        if name == 'search':
            raise RuntimeError('service unavailable')
        return '2'
    results = native_tools.execute_calls(native_tools.NativeResponse(first), schemas, dispatch)
    assert seen == ['search', 'PythonInterpreter']
    assert [r['tool_call_id'] for r in results] == ['a', 'b']
    assert 'service unavailable' in results[0]['content']
    assert results[1]['content'] == '2'
