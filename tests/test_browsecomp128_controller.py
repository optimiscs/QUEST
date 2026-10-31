"""Offline checks for the 27B experiment's visible-answer judge contract."""
import importlib.util
from pathlib import Path

source = Path(__file__).resolve().parents[1] / 'inference/scripts/run_browsecomp128_27b.py'
spec = importlib.util.spec_from_file_location('browsecomp128_controller', source)
controller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controller)


def test_judge_never_receives_thinking_or_tool_queries():
    result = {'messages': [{'content': '<think>secret</think>Visible<tool_call>{"query":"private"}</tool_call>'}]}
    assert controller.visible_judge_response(result) == 'Visible'
    assert controller.visible_judge_response({'messages': [{'content': '<think>unfinished'}]}) == ''


def test_contradictory_and_unknown_verdicts_are_not_silently_accepted():
    assert controller.contradictory_judgment('extracted_final_answer: None\ncorrect: yes')
    assert not controller.contradictory_judgment('extracted_final_answer: None\ncorrect: no')
    assert controller.parse_verdict('undetermined') is None


def test_original_summary_uses_local_model_and_does_not_require_retrieval():
    opts = controller.visit_settings({'VISIT_EXPERIMENT_METHOD': 'bm25_embedding'}, 'qwen38-27b')
    assert opts['VISIT_EXPERIMENT_DELIVERY'] == 'direct'
    opts = controller.visit_settings({'QUEST_VISIT_MODE': 'original_summary'}, 'qwen38-27b')
    assert opts['VISIT_EXPERIMENT_METHOD'] == ''
    assert opts['QUEST_VISIT_USE_LOCAL_27B'] == 'true'
    assert opts['VISIT_LOCAL_MODEL_NAME'] == 'qwen38-27b'
    assert opts['VISIT_CACHE_ENABLED'] == 'true'
    assert controller.visit_settings({'QUEST_VISIT_MODE': 'original_summary', 'VISIT_CACHE_ENABLED': 'false'}, 'qwen38-27b')['VISIT_CACHE_ENABLED'] == 'false'


def test_unknown_visit_mode_fails_loudly():
    import pytest
    with pytest.raises(ValueError):
        controller.visit_settings({'QUEST_VISIT_MODE': 'typo'}, 'model')
