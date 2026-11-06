"""Replay one captured older-history subset against the local summary model."""
import json
import os
import shutil
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'inference'))
sys.path.insert(0, str(ROOT / 'training_scripts/sft'))
os.environ.update(MEMORY_MODEL_NAME='openai/qwen38-27b', MEMORY_API_BASE='http://127.0.0.1:19300/v1',
                  MEMORY_API_KEY='EMPTY', MEMORY_DISABLE_THINKING='true', MEMORY_MAX_OUTPUT_TOKENS='4096',
                  MEMORY_RETRY_INVALID_JSON='true', MEMORY_INPUT_TOKEN_BUDGET='0', QUEST_SOURCE_IDS='true',
                  VISIT_CACHE_ENABLED='false', MEMORY_TOKENIZER_PATH=str(ROOT / 'workspace/models/Qwen3.8-27B-NVFP4'))
from transformers import AutoTokenizer
from tool_memory import Memory
from react_agent import split_memory_history, memory_events_without_embedded_state
from summary_events import read_events
from inference import source_ids


def main():
    run = Path(sys.argv[1]).resolve()
    registry = run / 'memory-trigger-replay-sources'
    registry.mkdir(exist_ok=True)
    shutil.copy2(run / 'traces/case01/case01/iter1/sources.json', registry / 'sources.json')
    source_ids.bind_task(registry)
    tool = object.__new__(Memory)
    tool.tokenizer = AutoTokenizer.from_pretrained(ROOT / 'workspace/models/Qwen3.8-27B-NVFP4')
    tool.token_threshold = 40000
    events, _ = read_events(run, 'case01')
    chosen = None
    for event in reversed(events):
        context = event.get('api_request_context', {})
        messages = context.get('messages')
        if not messages or event.get('kind') != 'policy_model':
            continue
        partition = split_memory_history(messages, keep_rounds=3)
        if partition is None:
            continue
        older, recent = partition
        payload = {'events': memory_events_without_embedded_state(older, None), 'prev_state': None}
        length = tool.count_tokens(tool._format_memory_input(payload['events'], None))
        if 10000 <= length < 40000:
            chosen = (event, payload, length, recent)
            break
    assert chosen is not None
    event, payload, length, recent = chosen
    before = tool.call(payload)
    assert 'below threshold' in before
    after = tool.call(payload, _context_threshold_triggered=True)
    state = tool._extract_json_from_response(after)
    report = {'case': 'case01', 'source_policy_span': event['span_id'],
              'mode': 'isolated replay of a captured older-history subset, not a repeated full rollout',
              'older_history_tokens': length, 'threshold': 40000,
              'without_trigger_skips': True, 'with_trigger_valid_state': isinstance(state, dict),
              'recent_messages_excluded': len(recent), 'raw_summary': after}
    (run / 'memory-trigger-live-check.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'raw_summary'}))
    assert isinstance(state, dict)


if __name__ == '__main__':
    main()
