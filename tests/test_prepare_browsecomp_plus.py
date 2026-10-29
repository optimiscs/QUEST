import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "evaluation/official_dataset/prepare_browsecomp_plus.py"
spec = importlib.util.spec_from_file_location("prepare_bcp", path)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class PrepareTests(unittest.TestCase):
    def test_search_and_answer(self):
        task = {"filename": "769", "question": "question?"}
        trajectory = [{"question": "question?", "prediction": "answer"}]
        events = [
            {"kind": "fixed_corpus_search", "event": "span_start"},
            {"kind": "fixed_corpus_search", "event": "span_end",
             "output": "bm25://z/page bm25://a/page bm25://a/other"},
            {"kind": "visit", "event": "span_start"},
        ]
        result = m.build_record(task, trajectory, events)
        self.assertEqual(result["retrieved_docids"], ["a", "z"])
        self.assertEqual(result["tool_call_counts"]["search"], 1)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"][0]["output"], "answer")

    def test_cli_separates_manifest_from_author_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "task.json").write_text(json.dumps({"filename": "769", "question": "question?"}))
            (root / "trajectory.jsonl").write_text(json.dumps({"question": "question?", "prediction": "answer"}) + "\n")
            (root / "events.jsonl").write_text("")
            out = root / "output"
            subprocess.run([sys.executable, str(path), "--task", str(root / "task.json"),
                            "--trajectory", str(root / "trajectory.jsonl"),
                            "--events", str(root / "events.jsonl"), "--out", str(out)],
                           check=True, capture_output=True, text=True)
            self.assertEqual([p.name for p in (out / "input").glob("*.json")], ["run_769.json"])
            self.assertEqual(json.loads((out / "manifest.json").read_text())["status"], "prepared_not_scored")
            self.assertEqual(json.loads((out / "input/run_769.json").read_text())["status"], "completed")

    def test_missing_answer_and_invalid_input(self):
        task = {"filename": "769", "question": "question?"}
        self.assertEqual(m.build_record(task, [{"question": "question?", "prediction": "  "}], [])["status"], "failed")
        with self.assertRaises(ValueError):
            m.build_record(task, [{"question": "different", "prediction": "answer"}], [])
        with self.assertRaises(ValueError):
            m.build_record({"filename": "../escape", "question": "question?"}, [], [])
        with self.assertRaises(ValueError):
            m.build_record(task, [{"question": "question?", "prediction": 5}], [])


if __name__ == "__main__":
    unittest.main()
