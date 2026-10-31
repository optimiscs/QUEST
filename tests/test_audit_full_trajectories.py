import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("audit_full_trajectories", ROOT / "training_scripts/sft/audit_full_trajectories.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_tool_audit_accepts_valid_json_and_flags_invalid_json():
    messages = [{"role": "assistant", "content": '<tool_call>{"name":"search","arguments":{"query":["x"]}}</tool_call>'}]
    result, names = audit.tool_diagnostics(messages)
    assert result["json_blocks"] == 1 and not result["invalid_json"]
    assert names["search"] == 1
    messages[0]["content"] = '<tool_call>{"name": "search", "arguments":</tool_call>'
    result, _ = audit.tool_diagnostics(messages)
    assert result["invalid_json"] == 1


def test_non_json_and_incomplete_calls_are_flagged_not_misclassified_as_invalid_json():
    messages = [{"role": "assistant", "content": "<tool_call><function=search>abc</tool_call><tool_call>"}]
    result, _ = audit.tool_diagnostics(messages)
    assert result["non_json_form"] == 1
    assert result["tag_open"] == 2 and result["tag_close"] == 1
    assert not result["invalid_json"]


def test_question_normalization_and_message_hash_are_stable():
    assert audit.normalize_question(" Ａ\n B  ") == "a b"
    assert audit.sha_messages([{"role": "user", "content": "x"}]) == audit.sha_messages([{"content": "x", "role": "user"}])
