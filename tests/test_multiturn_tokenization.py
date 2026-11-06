import copy
import sys
from pathlib import Path
import pytest
from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'training_scripts/sft'))
from tokenize_multiturn_sessions import encode_session, fixed_system_template, classify


@pytest.fixture
def sample():
    return {'metadata': {'id': 'example'}, 'tools': [], 'messages': [
        {'role': 'system', 'content': 'Research the question.'},
        {'role': 'user', 'content': 'Who wrote it?'},
        {'role': 'assistant', 'content': '<think>Find a source.</think>', 'tool_calls': [
            {'id': 'a', 'type': 'function', 'function': {'name': 'search', 'arguments': '{"query":["author"]}'}}]},
        {'role': 'tool', 'tool_call_id': 'a', 'content': 'Ada wrote it.'},
        {'role': 'user', 'content': 'Return the final answer as JSON.'},
        {'role': 'assistant', 'content': '{"answer":"Ada"}'}]}


def test_all_assistant_turns_share_exact_serving_prefixes(sample):
    tokenizer = AutoTokenizer.from_pretrained(ROOT / 'workspace/models/Qwen3.8-27B-NVFP4', local_files_only=True)
    with pytest.raises(AssertionError, match='Unstable'):
        encode_session(sample, tokenizer)
    tokenizer.chat_template = fixed_system_template(tokenizer.chat_template)
    encoded = encode_session(sample, tokenizer)
    assert len(encoded['assistant_spans']) == 2
    mask = set()
    for span in encoded['assistant_spans']:
        mask.update(range(span['start'], span['end']))
    assert all(label == (encoded['input_ids'][i] if i in mask else -100)
               for i, label in enumerate(encoded['labels']))
    assert 'Find a source.' in tokenizer.decode(encoded['input_ids'])
    with pytest.raises(ValueError, match='exceeds'):
        encode_session(sample, tokenizer, limit=1)


def test_compressed_input_is_not_a_compression_target(sample):
    assert classify(sample) == 'question_to_answer'
    compressed = copy.deepcopy(sample)
    compressed['messages'][1]['content'] += '\nRESEARCH STATE SUMMARY (prev_state)\nSaved evidence.'
    assert classify(compressed) == 'compression_to_answer'


def test_empty_tool_thought_has_a_prefix_stable_boundary(sample):
    tokenizer = AutoTokenizer.from_pretrained(ROOT / 'workspace/models/Qwen3.8-27B-NVFP4', local_files_only=True)
    tokenizer.chat_template = fixed_system_template(tokenizer.chat_template)
    sample['messages'][2]['content'] = '<think>'
    encoded = encode_session(sample, tokenizer)
    first = encoded['assistant_spans'][0]
    target = tokenizer.decode(encoded['input_ids'][first['start']:first['end']])
    assert target.startswith('</think>\n\n<tool_call>')
    assert '<think>' not in target
