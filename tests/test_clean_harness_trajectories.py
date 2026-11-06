import copy
import json

import pytest

from training_scripts.sft.clean_harness_trajectories import Rejected, parse_trajectory, schemas_from_source


@pytest.fixture
def schemas():
    return schemas_from_source()


@pytest.fixture
def trajectory():
    return [
        {"role": "system", "content": "Research."},
        {"role": "user", "content": "Find the date."},
        {"role": "assistant", "content": '<think>Look up the date.</think><tool_call>{"name":"search","arguments":{"query":["event date"]}}</tool_call>'},
        {"role": "user", "content": "<tool_response>Event: 1999. https://example.com</tool_response>"},
        {"role": "assistant", "content": "<think>The evidence says 1999.</think><answer>1999</answer>"},
    ]


def test_native_conversion_keeps_observation_and_pairs_ids(trajectory, schemas):
    original = copy.deepcopy(trajectory)
    messages, facts = parse_trajectory(trajectory, schemas)
    assert trajectory == original
    assert messages[2]["tool_calls"][0]["id"] == messages[3]["tool_call_id"]
    assert messages[3]["content"] == "Event: 1999. https://example.com"
    assert json.loads(messages[-1]["content"]) == {"answer": "1999"}
    assert facts["tool_calls"] == 1


def test_incomplete_snapshot_is_not_a_trajectory(trajectory, schemas):
    with pytest.raises(Rejected, match="no_complete_final_answer"):
        parse_trajectory(trajectory[:4], schemas)


@pytest.mark.parametrize("raw", [
    '{"name":"search","name":"visit","arguments":{"query":["q"]}}',
    '{"name":"search","arguments":{"query":[NaN]}}',
    '{"name":"search","arguments":{"query":[],"extra":1}}',
])
def test_reject_invalid_calls_without_repairing_semantics(trajectory, schemas, raw):
    trajectory[2]["content"] = "<tool_call>" + raw + "</tool_call>"
    with pytest.raises(Rejected):
        parse_trajectory(trajectory, schemas)


def test_reject_missing_and_orphan_results(trajectory, schemas):
    with pytest.raises(Rejected, match="missing_tool_result"):
        parse_trajectory(trajectory[:3] + trajectory[4:], schemas)
    with pytest.raises(Rejected, match="orphan_tool_result"):
        parse_trajectory(trajectory[:2] + trajectory[3:], schemas)


def test_reject_memory_without_original_history(trajectory, schemas):
    trajectory[1]["content"] += "\nRESEARCH STATE SUMMARY (prev_state)"
    with pytest.raises(Rejected, match="compressed_history"):
        parse_trajectory(trajectory, schemas)


def test_scalar_conversion_is_logged(trajectory, schemas):
    trajectory[2]["content"] = '<tool_call>{"name":"Visit","arguments":{"url":"https://example.com","goal":"date"}}</tool_call>'
    _, facts = parse_trajectory(trajectory, schemas)
    assert facts["visits"][0]["urls"] == ["https://example.com"]
    assert len(facts["repairs"]) == 2


def test_policy_cannot_create_source_from_future(tmp_path):
    from training_scripts.sft.replay_cleaning_pilot import compact_known
    from inference.source_ids import SourceRegistry
    registry = SourceRegistry(tmp_path)
    registry.compact("https://known.example")
    assert compact_known(registry, "Read https://known.example") == "Read S1"
    with pytest.raises(ValueError, match="unseen_url"):
        compact_known(registry, "Read https://future.example")


def test_cached_error_is_not_raw_evidence():
    from training_scripts.sft.replay_cleaning_pilot import readable_body
    assert not readable_body("[visit] Error " + "x" * 200)
    assert not readable_body("Warning: Target URL returned error 404: Not Found" + "x" * 200)
    assert readable_body("Title: Example\nMarkdown Content:\n" + "A paragraph. " * 30)


def test_summary_mode_retains_memory_as_context(trajectory, schemas):
    trajectory[1]['content'] += '\nRESEARCH STATE SUMMARY (prev_state)\nHistorical evidence.'
    converted, _ = parse_trajectory(trajectory, schemas, allow_memory=True)
    assert converted[1]['content'] == trajectory[1]['content']


def test_native_reasoning_is_lossless_in_both_transports():
    from inference import native_tools
    original = [{'role': 'assistant', 'content': '<think>Check the source.</think>Next.'}]
    api = native_tools.prepare_messages(original)
    hf = native_tools.prepare_messages(original, for_template=True)
    assert api[0]['reasoning'] == hf[0]['reasoning_content'] == 'Check the source.'
    assert api[0]['content'] == hf[0]['content'] == 'Next.'
    assert native_tools.prepare_messages(api) == api
    assert original[0]['content'].startswith('<think>')
