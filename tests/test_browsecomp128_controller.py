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
