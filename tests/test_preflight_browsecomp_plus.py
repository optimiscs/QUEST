import importlib.util
import unittest
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "evaluation/official_dataset/preflight_browsecomp_plus.py"
spec = importlib.util.spec_from_file_location("preflight_bcp", path)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class PreflightTests(unittest.TestCase):
    def test_reference_and_evidence(self):
        task = {"filename": "769", "question": "question?"}
        record = {"query_id": "769", "status": "completed"}
        references = [{"query_id": "769", "query": "question?", "answer": "answer"}]
        result = m.validate(task, record, iter(references), iter(["769 0 doc1 1\n"]))
        self.assertEqual(result["qrel_entries"], 1)
        self.assertEqual(result["prediction_status"], "completed")
        with self.assertRaises(ValueError):
            m.validate(task, record, iter(references), iter([]))
        with self.assertRaises(ValueError):
            m.validate(task, record, iter(references * 2), iter(["769 0 doc1 1"]))
        with self.assertRaises(ValueError):
            m.validate(task, record, iter([dict(references[0], query="wrong")]), iter(["769 0 doc1 1"]))
        with self.assertRaises(ValueError):
            m.validate(task, record, iter(references), iter(["malformed"]))


if __name__ == "__main__":
    unittest.main()
