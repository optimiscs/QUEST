"""Optional, model-independent tool-prompt profile; default prompts stay unchanged."""
import json
from pathlib import Path

PYTHON_SCHEMA = {
    'type': 'function', 'function': {
        'name': 'PythonInterpreter',
        'description': 'Execute Python in the sandbox. Supply empty arguments and put the Python code in <code>...</code> immediately after the JSON object inside the tool_call block. Print values to see them.',
        'parameters': {'type': 'object', 'properties': {}}
    }
}
PYTHON_EXAMPLE = '<tool_call>\n{"name":"PythonInterpreter","arguments":{}}\n<code>\nprint(1 + 1)\n</code>\n</tool_call>'
OLD_FORMAT = 'For each function call, return a json object with function name and arguments within <tool_call></tool_call> XML tags:\n<tool_call>\n{"name": <function-name>, "arguments": <args-json-object>}\n</tool_call>'

def apply(prompt, profile_path):
    profile = json.loads(Path(profile_path).read_text(encoding='utf-8'))
    if not isinstance(profile.get('instruction'), str) or not isinstance(profile.get('examples'), dict):
        raise ValueError('tool prompt profile must contain instruction and examples')
    if prompt.count('<tools>\n') != 1 or prompt.count('\n</tools>') != 1:
        raise ValueError('expected exactly one tool definition block')
    start=prompt.index('<tools>\n')+len('<tools>\n'); end=prompt.index('\n</tools>',start)
    schemas=[]
    for line in prompt[start:end].splitlines():
        if line.strip():
            obj=json.loads(line)
            if not isinstance(obj,dict) or not isinstance(obj.get('function',{}).get('name'),str): raise ValueError('invalid tool schema')
            schemas.append(obj)
    names={x['function']['name'] for x in schemas}
    tools='\n'.join(json.dumps(x,ensure_ascii=False) for x in schemas)
    prompt=prompt[:start]+tools+prompt[end:]
    examples=[]
    for name,obj in profile['examples'].items():
        if name not in names: continue
        if not isinstance(obj,dict) or obj.get('name')!=name or not isinstance(obj.get('arguments'),dict): raise ValueError('invalid example for '+name)
        examples.append('<tool_call>\n'+json.dumps(obj,ensure_ascii=False)+'\n</tool_call>')
    if 'PythonInterpreter' in names: examples.append(PYTHON_EXAMPLE)
    corrections=[]
    for example in profile.get('negative_examples', []):
        if example.get('tool') not in names: continue
        if not isinstance(example.get('bad'),str) or not isinstance(example.get('reason'),str) or not isinstance(example.get('good'),dict) or example['good'].get('name')!=example['tool']:
            raise ValueError('invalid contrastive tool example')
        corrections.append('WRONG JSON (do not copy): '+example['bad']+'\nWhy wrong: '+example['reason']+'\nCorrect JSON: '+json.dumps(example['good'],ensure_ascii=False))
    contrast = '\n\nCommon mistakes and corrections:\n'+'\n\n'.join(corrections) if corrections else ''
    replacement=profile['instruction']+contrast+'\n\nCorrect tool call examples:\n'+'\n\n'.join(examples)
    if prompt.count(OLD_FORMAT)!=1: raise ValueError('unsupported prompt tool-call instruction')
    return prompt.replace('You may call one or more functions to assist with the user query.', 'You may call one function at a time to assist with the user query.').replace(OLD_FORMAT,replacement,1)
