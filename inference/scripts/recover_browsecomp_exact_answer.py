"""Score a stopped BrowseComp trajectory's recorded, complete final response.

This never calls the agent again and never edits original event or result files.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from inference.final_answer import recognize_benchmark_answer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-root', required=True, type=Path)
    parser.add_argument('--case', required=True)
    parser.add_argument('--judge-port', required=True, type=int)
    parser.add_argument('--model', required=True)
    args = parser.parse_args()
    if not args.case.startswith('row') or not args.case[3:].isdigit():
        parser.error('invalid case')
    run = args.run_root.resolve(strict=True)
    state = json.loads((run / 'status.json').read_text())['cases'][args.case]
    if state.get('agent_state') != 'terminal' or state.get('result_path'):
        raise RuntimeError('Recovery requires a stopped agent without a native result')
    refs = {r['case']: r for r in json.loads((run / 'judge/ground-truth/references.json').read_text())}
    starts, candidates, calls = {}, [], 0
    for line in (run / 'logs' / f'{args.case}-agent-events.jsonl').read_text().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get('kind') != 'policy_model':
            continue
        if event.get('event') == 'span_start':
            starts[event['span_id']] = event
        elif event.get('event') == 'span_end':
            calls += 1
            start = starts.get(event['span_id'])
            choice = ((event.get('api_response') or {}).get('choices') or [{}])[0]
            message = choice.get('message') or {}
            text = message.get('content') or ''
            found = recognize_benchmark_answer(text, 'browsecomp', finish_reason=choice.get('finish_reason'),
                                               has_tool_calls=bool(message.get('tool_calls')))
            if found and start:
                candidates.append((found, text, start, event, calls))
    if not candidates or len({c[0].answer for c in candidates}) != 1:
        raise RuntimeError('No unambiguous complete recorded answer')
    found, raw, start, end, rounds = candidates[-1]
    messages = (start.get('input') or {}).get('msgs')
    if not isinstance(messages, list):
        raise RuntimeError('Recorded request messages are unavailable')
    messages = list(messages) + [{'role': 'assistant', 'content': raw}]
    result = {'question': refs[args.case]['question'], 'answer': '', 'messages': messages,
              'prediction': found.answer, 'termination': found.source, 'num_rounds': rounds,
              'filename': '', 'rollout_idx': 1, 'rollout_id': 1,
              'recovered_from_recorded_span': end['span_id'], 'recovery_time': time.time()}
    out = run / 'checks' / 'recognized-answer-recovery' / args.case / 'iter1.jsonl'
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('x') as f:
        f.write(json.dumps(result, ensure_ascii=False) + '\n')
    os.environ['QUEST_BROWSE128_RUN'] = str(run)
    os.environ['QUEST_BROWSE128_MODEL'] = args.model
    spec = importlib.util.spec_from_file_location('browsecomp128_controller', ROOT / 'inference/scripts/run_browsecomp128_27b.py')
    controller = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(controller)
    receipt = controller.judge(args.case, args.judge_port, refs[args.case], str(out), receipt_tag='recognized-answer-judge')
    summary = {'case': args.case, 'status': receipt['status'], 'is_correct': receipt.get('is_correct'),
               'source_span': end['span_id'], 'recovery_result_path': str(out),
               'judge_receipt': str(run / 'checks' / f'{args.case}-recognized-answer-judge.json')}
    controller.save(run / 'checks' / f'{args.case}-recognized-answer-recovery.json', summary)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
