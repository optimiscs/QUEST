import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("post_eval_27b", ROOT / "training_scripts/sft/post_eval_27b.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_waits_for_all_128_scored_cases(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "EVAL", tmp_path)
    cases = {str(i): {"agent_state": "terminal", "judge_state": "scored"} for i in range(128)}
    path = tmp_path / "status.json"
    path.write_text(json.dumps({"cases": cases}))
    assert module.evaluation_done()
    cases["0"]["judge_state"] = "pending"
    path.write_text(json.dumps({"cases": cases}))
    assert not module.evaluation_done()
    del cases["127"]
    path.write_text(json.dumps({"cases": cases}))
    with pytest.raises(ValueError):
        module.evaluation_done()


def test_only_explicit_cuda_oom_selects_fallback():
    assert module.OOM.search("torch.OutOfMemoryError: CUDA out of memory")
    assert module.OOM.search("torch.cuda.OutOfMemoryError: CUDA out of memory")
    assert not module.OOM.search("FileNotFoundError: model not found")
    assert not module.OOM.search("process killed with exit code 137")


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [("ok", None, ["bf16-lora"]), ("oom", "ok", ["bf16-lora", "qlora"])],
)
def test_workflow_selects_training_after_success(tmp_path, monkeypatch, first, second, expected):
    (tmp_path / "checks").mkdir()
    (tmp_path / "checks/dataset-lengths.json").write_text("{}")
    monkeypatch.setattr(module, "RUN", tmp_path)
    monkeypatch.setattr(module, "evaluation_done", lambda: True)
    monkeypatch.setattr(module, "stop_evaluation_server", lambda: None)
    monkeypatch.setattr(sys, "argv", ["workflow"])
    seen, trained = [], []

    def smoke(mode):
        seen.append(mode)
        return first if len(seen) == 1 else second

    monkeypatch.setattr(module, "smoke", smoke)
    monkeypatch.setattr(module, "train", trained.append)
    module.main()
    assert seen == expected
    assert trained == [expected[-1]]


def test_non_oom_failure_does_not_trigger_qlora_or_training(tmp_path, monkeypatch):
    (tmp_path / "checks").mkdir()
    (tmp_path / "checks/dataset-lengths.json").write_text("{}")
    monkeypatch.setattr(module, "RUN", tmp_path)
    monkeypatch.setattr(module, "evaluation_done", lambda: True)
    monkeypatch.setattr(module, "stop_evaluation_server", lambda: None)
    monkeypatch.setattr(sys, "argv", ["workflow"])
    seen, trained = [], []
    monkeypatch.setattr(module, "smoke", lambda mode: seen.append(mode) or "failed")
    monkeypatch.setattr(module, "train", trained.append)
    with pytest.raises(RuntimeError, match="smoke test failed"):
        module.main()
    assert seen == ["bf16-lora"]
    assert trained == []
