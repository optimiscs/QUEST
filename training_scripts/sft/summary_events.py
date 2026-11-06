"""Select attributable events without changing the raw experiment log.

The four restarted preflight cases shared a log path with terminating workers.
For these cases only the new process-start and task threads are unambiguous.
Auxiliary reader timing is omitted; tool calls and full tool responses remain.
"""
import json


def read_events(run, case):
    path = run / 'logs' / (case + '-agent-events.jsonl')
    events = []
    lines = path.read_text().splitlines()
    for index, line in enumerate(lines):
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            # A live writer may not yet have finished the final line.
            if index != len(lines) - 1:
                raise
    previous = run / 'preflight-before-reasoning-fix' / path.name
    if not previous.exists():
        return events, {'excluded_events': 0}
    main = next(e['thread_id'] for e in events if e['event'] == 'process_start')
    task = next(e['thread_id'] for e in events if e['event'] == 'span_start' and e.get('kind') == 'task')
    selected = [e for e in events if e['thread_id'] in (main, task)]
    return selected, {
        'included_thread_ids': [main, task],
        'excluded_events': len(events) - len(selected),
        'reason': 'Exclude preflight worker events and unattributed auxiliary timing; retain primary policy/tool events. Raw log preserved.',
    }
