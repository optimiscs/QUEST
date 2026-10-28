"""Opt-in normalization of DeepSeek textual tool calls without losing prose."""
import json
import re

_MARK = r'[｜|]{1,2}DSML[｜|]{1,2}'
_INVOKE = re.compile(r'<'+_MARK+r'\s*invoke\s+name="([^"]+)"[^>]*>(.*?)</'+_MARK+r'\s*invoke\s*>', re.S)
_PARAMETER = re.compile(r'<'+_MARK+r'\s*parameter\s+name="([^"]+)"([^>]*)>(.*?)</'+_MARK+r'\s*parameter\s*>', re.S)
_WRAPPER = re.compile(r'</?'+_MARK+r'\s*function_calls\s*>')


def normalize_dsml(content):
    """Convert complete DSML invocations, preserving all text outside them.

    Malformed or incomplete invocations remain unchanged rather than being
    silently treated as a successful tool call.
    """
    if not isinstance(content, str) or 'DSML' not in content:
        return content
    if '<tool_call>' in content and '</tool_call>' in content:
        return content
    matches = list(_INVOKE.finditer(content))
    if not matches:
        return content
    def convert(match):
        name, body = match.groups()
        arguments = {}
        for key, attrs, raw in _PARAMETER.findall(body):
            raw = raw.strip()
            if re.search(r'\bstring\s*=\s*"true"', attrs, re.I):
                value = raw
            else:
                try:value = json.loads(raw)
                except (ValueError, TypeError):value = raw
            arguments[key] = value
        # Refuse partially parsed arguments or unknown content inside invocation.
        remainder = _PARAMETER.sub('', body).strip()
        if remainder:
            return match.group(0)
        return '<tool_call>\n' + json.dumps({'name':name,'arguments':arguments},ensure_ascii=False) + '\n</tool_call>'
    output = _INVOKE.sub(convert, content)
    if output == content:
        return content
    # Only strip wrappers when no unconverted invocation remains inside them.
    if not _INVOKE.search(output):
        output = _WRAPPER.sub('', output)
    return output


def close_incomplete_tool_call(content):
    """Complete a parseable unclosed tool call while preserving adjacent text."""
    if not isinstance(content, str) or '<tool_call>' not in content or '</tool_call>' in content:
        return content
    prefix, tail = content.split('<tool_call>',1)
    leading = len(tail)-len(tail.lstrip())
    stripped=tail.lstrip()
    try: obj, end = json.JSONDecoder().raw_decode(stripped)
    except (ValueError, TypeError):return content
    if not isinstance(obj,dict) or not obj.get('name'):
        return content
    return prefix+'<tool_call>\n'+json.dumps(obj,ensure_ascii=False)+'\n</tool_call>'+stripped[end:]
