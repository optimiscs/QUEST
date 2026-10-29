"""Narrow, opt-in JSON closure repair for search/visit tool calls."""
import json

def _validated_search_or_visit(obj):
    if not isinstance(obj,dict) or set(obj)!={'name','arguments'} or not isinstance(obj['arguments'],dict):return None
    args=obj['arguments']
    if obj['name']=='search':
        q=args.get('query')
        if set(args)!={'query'} or not isinstance(q,list) or not q or not all(isinstance(x,str) for x in q):return None
    elif obj['name']=='visit':
        urls=args.get('url');goal=args.get('goal')
        if set(args)!={'url','goal'} or not isinstance(urls,list) or not urls or not all(isinstance(x,str) for x in urls) or not isinstance(goal,str):return None
    else:return None
    return obj

def append_missing_object_brace(raw):
    """Accept only inputs made valid by appending exactly one closing brace.

    The function never changes characters inside the submitted payload. It
    validates tool name and argument shapes before returning the parsed value.
    """
    try:
        json.loads(raw)
        return None
    except (ValueError,TypeError):
        pass
    if not isinstance(raw,str):return None
    try: obj=json.loads(raw.rstrip()+'}')
    except ValueError:return None
    return _validated_search_or_visit(obj)


def insert_missing_array_bracket(raw):
    """Insert one ] before the first mismatched } outside JSON strings.

    Only search/visit calls with the exact expected argument shapes are accepted.
    Quotes, escapes, argument text, and all other submitted characters stay intact.
    Other syntax errors, incomplete strings and payloads needing two edits fail.
    """
    if not isinstance(raw,str):return None
    stack=[];quoted=False;escaped=False
    for i,char in enumerate(raw):
        if quoted:
            if escaped:escaped=False
            elif char=='\\':escaped=True
            elif char=='"':quoted=False
            continue
        if char=='"':quoted=True
        elif char in '[{':stack.append(char)
        elif char in ']}':
            if not stack:return None
            if char=='}' and stack[-1]=='[':
                try:obj=json.loads(raw[:i]+']'+raw[i:])
                except ValueError:return None
                return _validated_search_or_visit(obj)
            if (stack[-1],char) not in (('{','}'),('[',']')):return None
            stack.pop()
    return None
