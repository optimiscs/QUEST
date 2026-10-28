import importlib.util
import contextlib
import io
import os
from unittest.mock import patch
import json
from pathlib import Path
import sys
import tempfile
import unittest

directory = Path(__file__).resolve().parents[1] / "evaluation/official_dataset"
sys.path.insert(0, str(directory))
spec = importlib.util.spec_from_file_location("score_bcp", directory / "score_browsecomp_plus.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class ScoringResultTests(unittest.TestCase):
    def test_only_single_complete_boolean_verdict_is_scored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file = root / "run_1_eval.json"
            row = {"query_id": "1", "is_completed": True,
                   "judge_result": {"parse_error": False, "correct": False}}
            file.write_text(json.dumps(row))
            self.assertEqual(m.find_verdict(root, "1")[1], False)
            row["judge_result"]["correct"] = "yes"
            file.write_text(json.dumps(row))
            self.assertIsNone(m.find_verdict(root, "1"))
            row["judge_result"]["correct"] = True
            row["judge_result"]["parse_error"] = True
            file.write_text(json.dumps(row))
            self.assertIsNone(m.find_verdict(root, "1"))
            row["judge_result"]["parse_error"] = False
            file.write_text(json.dumps(row))
            (root / "duplicate_eval.json").write_text(json.dumps(row))
            self.assertIsNone(m.find_verdict(root, "1"))


class LauncherTests(unittest.TestCase):
    def test_local_subprocess_success_and_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            task = root / "task.json"
            record = root / "record.json"
            ref = root / "reference.jsonl"
            qrels = root / "qrels.txt"
            task.write_text(json.dumps({"filename": "1", "question": "question"}))
            record.write_text(json.dumps({"query_id": "1", "status": "completed", "result": [{"type": "output_text", "output": "answer"}]}))
            ref.write_text(json.dumps({"query_id": "1", "query": "question", "answer": "truth"}) + "\n")
            qrels.write_text("1 0 doc 1\n")

            def run_case(suffix, exitcode):
                out = root / suffix
                args = ["score", "--source", str(source), "--task", str(task), "--record", str(record),
                        "--reference", str(ref), "--qrels", str(qrels), "--out", str(out), "--model", "dummy"]
                def fake_run(cmd, **kwargs):
                    score_dir = Path(cmd[cmd.index("--eval_dir") + 1])
                    snapshot_dir = Path(cmd[cmd.index("--input_dir") + 1])
                    self.assertEqual(json.loads((snapshot_dir / "run_1.json").read_text())["query_id"], "1")
                    if exitcode == 0:
                        (score_dir / "run_1_eval.json").write_text(json.dumps({
                            "query_id": "1", "is_completed": True,
                            "judge_result": {"parse_error": False, "correct": False}}))
                    return type("Result", (), {"returncode": exitcode})()
                with patch.object(m, "check_source"), patch.object(m.subprocess, "run", side_effect=fake_run), \
                     patch.dict(os.environ, {"OPENAI_API_KEY": "dummy"}), patch.object(sys, "argv", args), \
                     contextlib.redirect_stdout(io.StringIO()):
                    if exitcode:
                        with self.assertRaises(SystemExit):
                            m.main()
                    else:
                        m.main()
                return json.loads((out / "receipt.json").read_text())

            success = run_case("success", 0)
            self.assertEqual(success["status"], "scored")
            self.assertIs(success["correct"], False)
            failure = run_case("failure", 2)
            self.assertEqual(failure["status"], "unscored")
            self.assertIsNone(failure["correct"])


if __name__ == "__main__":
    unittest.main()
