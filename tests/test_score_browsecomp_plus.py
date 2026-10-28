import importlib.util
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


if __name__ == "__main__":
    unittest.main()
