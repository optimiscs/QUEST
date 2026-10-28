import ast,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];FILE=ROOT/'task/open_ended_eval/evaluate_criteria_args_parallel_open_ended.py'
tree=ast.parse(FILE.read_text());names={'normalize_result_types','validate_score'};functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names];scope={};exec(compile(ast.fix_missing_locations(ast.Module(body=functions,type_ignores=[])),str(FILE),'exec'),scope)
class ScoreTypeTests(unittest.TestCase):
 def test_malformed_scores_never_turn_into_valid_zero(self):
  for raw in ('not-a-number',None,True,float('nan')):
   value=scope['normalize_result_types']({'score_a':raw,'score_b':5})
   self.assertFalse(scope['validate_score'](value),str(raw))
 def test_numeric_strings_still_work(self):
  value=scope['normalize_result_types']({'score_a':'3','score_b':'5'})
  self.assertTrue(scope['validate_score'](value));self.assertEqual(value['score_a'],3.0)
if __name__=='__main__':unittest.main()
