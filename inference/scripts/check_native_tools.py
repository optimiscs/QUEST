"""Live vLLM transport smoke test with explicitly synthetic tool results.

Does not call search/visit/sandbox services or modify benchmark results.
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('VISIT_CACHE_ENABLED', 'false')
os.environ.setdefault('SEARCH_CACHE_ENABLED', 'false')
from openai import OpenAI
from native_tools import NativeResponse, assistant_message, execute_calls, prepare_messages, tool_schemas
from react_agent import TOOL_MAP


def check(base_url, model):
    client = OpenAI(base_url=base_url, api_key='EMPTY', timeout=120, max_retries=0)
    schemas = tool_schemas(TOOL_MAP)
    checks = []
    prompts = {
        'search': 'Call search once with query ["OpenAI official website"]. Do not answer without calling it.',
        'visit': 'Call visit once with url ["https://example.com"] and goal "Find the page title".',
        'PythonInterpreter': 'Call PythonInterpreter once with code that assigns a string containing a quote and prints it. Put the full Python program in code.',
    }
    for name, prompt in prompts.items():
        messages = [{'role': 'system', 'content': 'This is a tool transport test. Use the supplied API tools.'},
                    {'role': 'user', 'content': prompt}]
        response = client.chat.completions.create(
            model=model, messages=messages, tools=schemas, tool_choice='auto', parallel_tool_calls=False,
            temperature=0, max_tokens=1024,
            extra_body={'chat_template_kwargs': {'enable_thinking': False}})
        choice = response.choices[0]
        native = NativeResponse(choice.message, choice.finish_reason)
        calls = native.message.get('tool_calls', [])
        assert len(calls) == 1 and calls[0]['function']['name'] == name, response.model_dump_json()
        executed = []
        def fixture(tool, arguments):
            executed.append(tool)
            return 'Synthetic transport-test result: OK'
        outputs = execute_calls(native, schemas, fixture)
        assert executed == [name], outputs
        messages += [assistant_message(native), *outputs,
                     {'role': 'user', 'content': 'Finish the test with <answer>OK</answer>. Do not call tools.'}]
        final = client.chat.completions.create(
            model=model, messages=prepare_messages(messages), tools=schemas, tool_choice='none',
            temperature=0, max_tokens=128,
            extra_body={'chat_template_kwargs': {'enable_thinking': False}})
        assert not final.choices[0].message.tool_calls
        assert '<answer>OK</answer>' in (final.choices[0].message.content or '')
        checks.append({'tool': name, 'arguments': json.loads(calls[0]['function']['arguments']),
                       'finish_reason': choice.finish_reason, 'schema_valid': True,
                       'paired_tool_result_accepted': True, 'final_tool_choice_none_passed': True})
    return {'base_url': base_url, 'model': model, 'tool_execution': 'synthetic fixture only', 'checks': checks}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:18210/v1')
    parser.add_argument('--model', default='QWEN35-SFT10')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = check(args.base_url, args.model)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload)
    print(payload)
