#!/usr/bin/env python3
"""Continue a saved reference-agent session; outputs are provisional evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path

PROMPT = ("The tool budget is exhausted. Using only evidence already present above, "
          "write your best final research report now. Do not call tools or invent "
          "sources; explicitly state any unsupported items. Include source URLs inline.")


def create_private(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def run(source, trace, output, client, model='deepseek-flash'):
    source, trace, output = map(Path, (source, trace, output))
    if trace.resolve() == output.resolve() or any(p.exists() or p.is_symlink() for p in (trace, output)):
        raise FileExistsError('trace and output must be distinct new files')
    raw = source.read_bytes()
    sessions = [json.loads(line) for line in raw.splitlines() if line.strip()]
    if not sessions or not isinstance(sessions[-1], dict) or sessions[-1].get('is_final') is not True:
        raise ValueError('last source session must be final')
    last = sessions[-1]
    question, messages = last.get('question'), last.get('messages')
    if not isinstance(question, str) or not question.strip() or not isinstance(messages, list) or not messages:
        raise ValueError('final session must contain a question and messages')
    if any(not isinstance(m, dict) or not isinstance(m.get('role'), str)
           or not isinstance(m.get('content'), str) for m in messages):
        raise ValueError('unsupported message in session')
    request = messages + [{'role':'user','content':PROMPT}]
    trace.parent.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    record = {'source':str(source.resolve()),'source_sha256':hashlib.sha256(raw).hexdigest(),
              'messages':request,'model':model,'reference_kind':'provisional_continuation'}
    try:
        response = client.chat.completions.create(model=model, messages=request, max_tokens=8192,
                                                   extra_body={'thinking':{'type':'disabled'}})
        choice = response.choices[0]
        answer = choice.message.content or ''
        record.update(response=answer, finish_reason=choice.finish_reason,
                      usage=response.usage.model_dump() if response.usage else None)
        valid = isinstance(answer, str) and len(answer.strip()) >= 100 and choice.finish_reason == 'stop'
        record['status'] = 'completed_provisional' if valid else 'invalid_response'
    except Exception as exc:
        record.update(status='request_failed', error_type=type(exc).__name__)
        create_private(trace, record)
        raise
    create_private(trace, record)
    if not valid:
        raise ValueError('continuation is incomplete; trace retained, no reference exported')
    result = {'question':question,'answer':answer,'termination':'continuation_after_tool_limit',
              'iter':last.get('iter',1),'reference_kind':'provisional_continuation',
              'source_sha256':record['source_sha256']}
    # JSONL remains compatible with the original reference input.
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        stream.write(json.dumps(result, ensure_ascii=False)+'\n')
    return {'status':record['status'],'trace':str(trace),'output':str(output)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True, help='Existing agent trajectory JSONL')
    p.add_argument('--trace', type=Path, required=True, help='New private trace JSON')
    p.add_argument('--output', type=Path, required=True, help='New provisional reference JSONL')
    p.add_argument('--model', default='deepseek-flash')
    p.add_argument('--base-url', default='https://api.deepseek.com/v1')
    a = p.parse_args()
    key = os.environ.get('DEEPSEEK_API_KEY')
    if not key:
        raise RuntimeError('DEEPSEEK_API_KEY must be set')
    from openai import OpenAI
    print(json.dumps(run(a.source, a.trace, a.output,
                         OpenAI(api_key=key, base_url=a.base_url, timeout=180), a.model)))


if __name__ == '__main__':
    main()
