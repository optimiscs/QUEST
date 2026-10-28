"""Validation shared by the open-ended ledger and SFT exporter."""
import hashlib
import json
import math
import re
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read_rows(path):
    rows = [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]
    if not rows or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f'invalid or empty JSONL: {path}')
    return rows


def validate(score_path, candidate_path, reference_path, sessions_path, status_path, reference_kind):
    scores, candidates, refs, sessions = map(read_rows, (score_path, candidate_path, reference_path, sessions_path))
    if len(scores) != 1 or len(candidates) != 1 or len(refs) != 1:
        raise ValueError('expected exactly one score, candidate and reference')
    score, candidate, ref = scores[0], candidates[0], refs[0]
    status = json.loads(Path(status_path).read_text())
    if (not isinstance(status, dict) or status.get('complete') is not True or status.get('exit_code') != 0
            or status.get('result_rows') != 1 or status.get('valid_scores') != 1
            or status.get('output_sha256') != digest(score_path)):
        raise ValueError('score status or output hash invalid')
    for role, path in (('candidate', candidate_path), ('reference', reference_path)):
        if status.get('input_sha256', {}).get(role) != digest(path):
            raise ValueError(f'{role} hash mismatch against score status')
    query, question, iteration = score.get('query'), candidate.get('question'), candidate.get('iter')
    value = score.get('final_score')
    answer = candidate.get('prediction', candidate.get('answer'))
    if (not isinstance(query, str) or not query or not isinstance(question, str) or not question.startswith(query)
            or not isinstance(ref.get('question'), str) or not ref['question'].startswith(query)
            or score.get('id') is None or not isinstance(iteration, (str, int)) or isinstance(iteration, bool)
            or iteration == '' or score.get('iter') != iteration
            or not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or not 0 <= value <= 1
            or not isinstance(answer, str) or not answer.strip()):
        raise ValueError('score and candidate provenance mismatch')
    ref_answer = ref.get('prediction', ref.get('answer', ''))
    termination = str(ref.get('termination', '')).lower()
    if (not isinstance(ref_answer, str) or len(ref_answer.strip()) < 100 or 'answer not found' in ref_answer.lower()
            or 'answer not found' in termination or 'timeout' in termination):
        raise ValueError('reference incomplete')
    if reference_kind not in ('independent_agent', 'provisional_generator'):
        raise ValueError('invalid reference kind')
    if reference_kind == 'independent_agent' and (ref.get('reference_kind') == 'provisional_continuation' or termination == 'continuation_after_tool_limit'):
        raise ValueError('continued reference cannot be declared independent')
    final = [s for s in sessions if s.get('is_final') is True]
    if len(final) != 1 or sessions[-1] is not final[0]:
        raise ValueError('trajectory must end with exactly one final session')
    # Legacy snapshots without iteration cannot establish rollout identity.
    if any(s.get('question') != question or 'iter' not in s or s['iter'] != iteration for s in sessions):
        raise ValueError('trajectory question or iteration mismatch')
    if any(s.get('task_id') is None or str(s['task_id']) != str(score['id']) for s in sessions):
        raise ValueError('trajectory task ID mismatch')
    messages = final[0].get('messages')
    if not isinstance(messages, list) or not messages or any(not isinstance(m, dict) or not isinstance(m.get('role'), str) or not isinstance(m.get('content'), str) for m in messages):
        raise ValueError('invalid final messages')
    assistants = [m['content'] for m in messages if m['role'] == 'assistant']
    if not assistants:
        raise ValueError('final session missing assistant')
    content = assistants[-1].rsplit('</think>', 1)[-1].split('<think>', 1)[0]
    matches = re.findall(r'<answer>((?:(?!<answer>|</answer>)[\s\S])*?)</answer>', content)
    final_answer = matches[-1].strip() if matches else content.strip()
    if final_answer != answer.strip():
        raise ValueError('trajectory final answer does not match candidate')
    return {'task_id': str(score['id']), 'rollout_id': str(iteration if iteration is not None else 1),
            'score': value, 'score_status': 'scored' if reference_kind == 'independent_agent' else 'provisional_reference',
            'sessions': sessions}
