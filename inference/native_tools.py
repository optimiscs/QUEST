"""OpenAI-compatible tool transport; never execute calls parsed from prose."""
import copy
import json
import os
import re

from jsonschema import Draft202012Validator


def enabled():
    return os.getenv('QUEST_NATIVE_TOOL_CALLS', '').lower() in {'1', 'true', 'yes'}


def tool_schemas(tool_map):
    schemas = []
    for name in ('search', 'visit', 'PythonInterpreter', 'google_scholar'):
        if name not in tool_map:
            continue
        tool = tool_map[name]
        parameters = copy.deepcopy(tool.parameters)
        parameters['additionalProperties'] = False
        if name == 'visit':
            parameters['properties']['url']['type'] = 'array'
            parameters['properties']['url']['description'] = 'URLs to read, including for a single page.'
        Draft202012Validator.check_schema(parameters)
        schemas.append({'type': 'function', 'function': {
            'name': name, 'description': tool.description,
            'parameters': parameters, 'strict': True,
        }})
    return schemas


def system_prompt(prompt, visit_disabled=False):
    from tool_prompt_plugin import OLD_FORMAT
    prompt = re.sub(r'You are provided with function signatures within <tools></tools> XML tags:\s*', '', prompt)
    prompt = re.sub(r'<tools>.*?</tools>', '', prompt, flags=re.S)
    prompt = prompt.replace(OLD_FORMAT, '')
    instruction = (
        'Use the tools provided by the API to obtain evidence. Call one function at a time. '
        'Supply arguments according to its schema. Python code belongs in the code string argument. '
        'Do not write tool calls or code blocks in your conversational response. '
        'When research is complete, give your final answer inside <answer>...</answer>.\n'
    )
    if visit_disabled:
        instruction += 'The visit tool is unavailable; gather evidence with search.\n'
    return instruction + prompt


class NativeResponse(str):
    """String-compatible for observers, with lossless structured message storage."""
    def __new__(cls, message, finish_reason=None):
        content = message.content or ''
        reasoning = getattr(message, 'reasoning_content', None) or getattr(message, 'reasoning', None)
        if reasoning:
            content = '<think>\n' + reasoning + '\n</think>\n' + content
        obj = super().__new__(cls, content)
        obj.message = {'role': 'assistant', 'content': content}
        calls = getattr(message, 'tool_calls', None) or []
        if calls:
            obj.message['tool_calls'] = [
                {'id': c.id, 'type': 'function', 'function': {
                    'name': c.function.name, 'arguments': c.function.arguments,
                }} for c in calls
            ]
            ids = [c['id'] for c in obj.message['tool_calls']]
            if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
                raise ValueError('Native tool calls require unique nonempty IDs')
        obj.finish_reason = finish_reason
        return obj


def assistant_message(response):
    if isinstance(response, NativeResponse):
        return copy.deepcopy(response.message)
    return {'role': 'assistant', 'content': (response or '').strip()}


def prepare_messages(messages, *, for_template=False):
    """HF templates need argument objects; the API needs JSON strings.

    Invalid calls stay verbatim in saved trajectories. For replay to the server,
    represent their arguments as {} alongside the paired validation error, so
    a rejected call cannot make the next request fail during template parsing.
    """
    result = copy.deepcopy(messages)
    for message in result:
        for call in message.get('tool_calls', []):
            raw = call['function']['arguments']
            try:
                args = json.loads(raw, object_pairs_hook=_object, parse_constant=_invalid_constant)
                if not isinstance(args, dict):
                    raise ValueError('Expected object')
            except (ValueError, TypeError):
                args = {}
            call['function']['arguments'] = args if for_template else json.dumps(args, ensure_ascii=False)
    return result


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate argument key: ' + key)
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError('Non-JSON numeric constant: ' + value)


def execute_calls(response, schemas, execute):
    """Validate every call before dispatch; return one tool response per ID."""
    definitions = {s['function']['name']: s['function']['parameters'] for s in schemas}
    results = []
    for call in response.message.get('tool_calls', []):
        name = call['function']['name']
        try:
            if response.finish_reason == 'length':
                raise ValueError('Generation was truncated; regenerate the complete call')
            if name not in definitions:
                raise ValueError('Tool is not available: ' + name)
            arguments = json.loads(call['function']['arguments'], object_pairs_hook=_object,
                                   parse_constant=_invalid_constant)
            errors = list(Draft202012Validator(definitions[name]).iter_errors(arguments))
            if errors:
                raise ValueError(errors[0].message)
        except (ValueError, TypeError) as exc:
            result = '[Tool Error] Invalid native arguments: ' + str(exc)
        else:
            try:
                result = execute(name, arguments)
            except Exception as exc:
                result = '[Tool Error] ' + str(exc)
        results.append({'role': 'tool', 'tool_call_id': call['id'], 'content': str(result)})
    return results
