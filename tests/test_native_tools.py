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


def test_browsecomp_exact_answer_finishes_without_regeneration(monkeypatch, tmp_path):
    monkeypatch.setenv('QUEST_FINAL_ANSWER_PROFILE', 'browsecomp')
    monkeypatch.setenv('QUEST_TELEMETRY_STREAM', '0')
    original = 'Explanation: Evidence.\nExact Answer: Clare Wigfall\nConfidence: 90%'
    agent, requests = agent_with_api(monkeypatch, tmp_path, [reply(content=original, finish='stop')])
    result = agent._run({'item': {'question': 'test', 'answer': ''}}, 'test-model')
    assert len(requests) == 1
    assert result['prediction'] == 'Clare Wigfall'
    assert result['termination'] == 'browsecomp_exact_answer'
    assert result['messages'][-1]['content'] == original


def test_browsecomp_tag_answer_finishes_without_regeneration(monkeypatch, tmp_path):
    monkeypatch.setenv('QUEST_FINAL_ANSWER_PROFILE', 'browsecomp')
    monkeypatch.setenv('QUEST_TELEMETRY_STREAM', '0')
    original = 'Explanation: Evidence.\n<answer>Clare Wigfall</answer>'
    agent, requests = agent_with_api(monkeypatch, tmp_path, [reply(content=original, finish='stop')])
    result = agent._run({'item': {'question': 'test', 'answer': ''}}, 'test-model')
    assert len(requests) == 1
    assert result['prediction'] == 'Clare Wigfall'
    assert result['termination'] == 'browsecomp_answer_tag'
    assert result['messages'][-1]['content'] == original


@pytest.mark.parametrize('native,text', [
    (True, 'Explanation: Evidence.\nExact Answer: Clare Wigfall'),
    (True, 'Explanation: Evidence.\n<answer>Clare Wigfall</answer>'),
    (False, 'Explanation: Evidence.\nExact Answer: Clare Wigfall'),
    (False, 'Explanation: Evidence.\n<answer>Clare Wigfall</answer>'),
])
def test_browsecomp_final_answer_precedes_memory_at_threshold(monkeypatch, tmp_path, native, text):
    monkeypatch.setenv('QUEST_FINAL_ANSWER_PROFILE', 'browsecomp')
    monkeypatch.setenv('QUEST_TELEMETRY_STREAM', '0')
    agent, requests = agent_with_api(monkeypatch, tmp_path, [reply(content=text, finish='stop')])
    monkeypatch.setenv('QUEST_NATIVE_TOOL_CALLS', 'true' if native else 'false')
    agent.memory_enabled = True
    agent.base_memory_context_threshold = 1
    monkeypatch.setattr(agent, '_call_condenser_directly', lambda *a, **k: pytest.fail('unexpected memory compression'))
    monkeypatch.setattr(agent, '_save_trajectory_for_distillation', lambda *a, **k: None)
    result = agent._run({'item': {'question': 'test', 'answer': ''}}, 'test-model')
    assert len(requests) == 1
    assert result['prediction'] == 'Clare Wigfall'
    assert result['messages'][-1]['content'] == text


def test_memory_events_strip_only_matching_embedded_state(monkeypatch, tmp_path):
    agent, _ = agent_with_api(monkeypatch, tmp_path, [])
    agent._init_thread_state()
    state = {'facts': ['a']}
    agent._get_thread_state().memory_state = state
    marker = '====================\nRESEARCH STATE SUMMARY (prev_state)\n===================='
    messages = [{'role': 'system', 'content': 'system'},
                {'role': 'user', 'content': 'Question\n\n' + marker + '\n' + json.dumps(state, indent=2)},
                {'role': 'assistant', 'content': 'searching'},
                {'role': 'tool', 'content': 'evidence', 'tool_call_id': 't'},
                {'role': 'user', 'content': marker + '\nother user data'},
                {'role': 'assistant', 'content': 'recent 1'},
                {'role': 'assistant', 'content': 'recent 2'},
                {'role': 'assistant', 'content': 'recent 3'}]
    snapshot = copy.deepcopy(messages)
    captured = {}
    class FakeMemory:
        def call(self, params):
            captured.update(copy.deepcopy(params))
            return json.dumps({'facts': ['updated']})
    monkeypatch.setitem(react_agent.TOOL_MAP, 'condenser', FakeMemory())
    monkeypatch.setattr(agent, '_update_first_user_message_with_state', lambda *args, **kwargs: None)
    agent._call_condenser_directly(messages)
    assert captured['prev_state'] == state
    assert captured['events'][0]['content'] == 'Question'
    assert captured['events'][-1]['content'] == messages[4]['content']
    assert captured['events'][2]['tool_call_id'] == 't'
    assert messages == snapshot
    assert react_agent.memory_events_without_embedded_state(messages, None)[0]['content'] == snapshot[1]['content']
    assert react_agent.memory_events_without_embedded_state(messages, {'facts': ['different']})[0]['content'] == snapshot[1]['content']


@pytest.mark.parametrize('native', [True, False])
def test_memory_summarizes_old_turns_and_keeps_three_complete_recent_turns(monkeypatch, tmp_path, native):
    agent, _ = agent_with_api(monkeypatch, tmp_path, [])
    agent._init_thread_state()
    monkeypatch.setattr(agent, '_save_memory_log', lambda *a, **kw: None)
    monkeypatch.setattr(agent, '_save_trajectory_for_distillation', lambda *a, **kw: None)
    messages = [{'role': 'system', 'content': 'system'}, {'role': 'user', 'content': 'Question'}]
    for i in range(5):
        if native:
            messages.extend([{'role': 'assistant', 'content': '', 'tool_calls': [
                {'id': str(i), 'type': 'function', 'function': {'name': 'search', 'arguments': '{}'}}]},
                {'role': 'tool', 'tool_call_id': str(i), 'content': f'result {i}'}])
        else:
            messages.extend([{'role': 'assistant', 'content': f'<tool_call>{i}</tool_call>'},
                             {'role': 'user', 'content': f'<tool_response>result {i}</tool_response>'}])
    original = copy.deepcopy(messages)
    captured = {}
    class FakeMemory:
        def call(self, params):
            captured.update(copy.deepcopy(params))
            return '{"facts":["old evidence"]}'
    monkeypatch.setitem(react_agent.TOOL_MAP, 'condenser', FakeMemory())
    assert agent._call_condenser_directly(messages) == {'facts': ['old evidence']}
    assert captured['events'] == original[1:6]  # question plus first two turns
    assert messages[2:] == original[6:]  # three complete recent turns
    assert messages[1]['content'].startswith('Question\n')
    assert 'old evidence' in messages[1]['content']


def test_memory_skips_when_no_older_turns(monkeypatch, tmp_path):
    agent, _ = agent_with_api(monkeypatch, tmp_path, [])
    agent._init_thread_state()
    messages = [{'role': 'user', 'content': 'q'}] + [{'role': 'assistant', 'content': str(i)} for i in range(3)]
    monkeypatch.setitem(react_agent.TOOL_MAP, 'condenser', SimpleNamespace(call=lambda *_: pytest.fail('unexpected summary')))
    original = copy.deepcopy(messages)
    assert agent._call_condenser_directly(messages) is None
    assert messages == original


def test_failed_memory_keeps_original_history_and_state(monkeypatch, tmp_path):
    agent, _ = agent_with_api(monkeypatch, tmp_path, [])
    agent._init_thread_state()
    agent._get_thread_state().memory_state = {'facts': ['original']}
    messages = [{'role': 'user', 'content': 'q'}] + [{'role': 'assistant', 'content': str(i)} for i in range(4)]
    original = copy.deepcopy(messages)
    monkeypatch.setitem(react_agent.TOOL_MAP, 'condenser', SimpleNamespace(call=lambda *_: 'invalid json'))
    assert agent._call_condenser_directly(messages) is None
    assert messages == original
    assert agent._get_thread_state().memory_state == {'facts': ['original']}


def test_tool_result_has_no_archive_marker_or_read_evidence(monkeypatch, tmp_path):
    agent, _ = agent_with_api(monkeypatch, tmp_path, [])
    agent._init_thread_state()
    agent._get_thread_state().task_log_dir = str(tmp_path)
    original = "A Google search for 'q' found 1 results:\n\nTitle: A\nLink: https://a\nSnipptes: fact"
    monkeypatch.setitem(react_agent.TOOL_MAP, 'search', SimpleNamespace(call=lambda *a, **k: original))
    assert agent.custom_call_tool('search', {'query': ['q']}) == original
    assert 'read_evidence' not in react_agent.TOOL_MAP
    assert not (tmp_path / 'evidence').exists()


def test_optional_vector_search_never_exposes_evidence_ids(monkeypatch, tmp_path):
    agent, _ = agent_with_api(monkeypatch, tmp_path, [])
    agent._init_thread_state()
    agent._get_thread_state().task_log_dir = str(tmp_path)
    monkeypatch.setenv('QUEST_SEARCH_VECTOR_URL', 'http://vector')
    monkeypatch.setitem(react_agent.TOOL_MAP, 'search', SimpleNamespace(call=lambda *a, **k: 'external'))
    monkeypatch.setattr(react_agent.search_vector_client, 'search', lambda *a, **k: [{'title': 'source', 'url': 'https://a', 'snippet': 'fact', 'evidence_id': 'E' + 'a' * 64}])
    monkeypatch.setattr(react_agent.search_vector_client, 'index', lambda *a, **k: 1)
    result = agent.custom_call_tool('search', {'query': ['q']})
    assert 'external' in result and 'fact' in result
    assert 'Evidence' not in result and 'E' + 'a' * 64 not in result
    assert not (tmp_path / 'evidence').exists()


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
