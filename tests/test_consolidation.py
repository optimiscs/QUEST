import ast,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ADAPTER=ROOT/"contrib/deepseek_data"
class SafetyTests(unittest.TestCase):
 def test_answer_extraction_ignores_think(self):
  tree=ast.parse((ROOT/"inference/react_agent.py").read_text());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="extract_non_thinking_answer")
  scope={};exec("import re\nfrom typing import Optional",scope);exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),"answer","exec"),scope)
  f=scope["extract_non_thinking_answer"];self.assertEqual(f("<think><answer>wrong</answer></think><answer>right</answer>"),"right");self.assertIsNone(f("<think><answer>secret</answer>"))
 def test_export_requires_scored_and_threshold(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);(p/"sessions.jsonl").write_text(json.dumps({"messages":[{"role":"user","content":"q"},{"role":"assistant","content":"a"}]})+"\n")
   rows=[{"task_id":"a","rollout_id":"1","kind":"objective","score_status":"scored","score":1,"sessions_path":"sessions.jsonl"},{"task_id":"b","rollout_id":"1","kind":"openended","score_status":"provisional_reference","score":0.99,"sessions_path":"sessions.jsonl"},{"task_id":"c","rollout_id":"1","kind":"openended","score_status":"scored","score":0.25,"sessions_path":"sessions.jsonl"}]
   (p/"ledger.jsonl").write_text("\n".join(map(json.dumps,rows))+"\n")
   subprocess.run([sys.executable,str(ADAPTER/"export_sft.py"),"--ledger",str(p/"ledger.jsonl"),"--output",str(p/"out.json"),"--manifest",str(p/"manifest.json")],check=True,capture_output=True)
   self.assertEqual(json.loads((p/"out.json").read_text()),[])
   decisions=json.loads((p/"manifest.json").read_text())["decisions"]
   self.assertEqual([x["excluded_reason"] for x in decisions],["objective_verifier_unverified","not_scored_or_below_threshold","not_scored_or_below_threshold"])
 def test_duplicate_rollout_is_rejected_before_export(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);(p/"sessions.jsonl").write_text(json.dumps({"messages":[{"role":"user","content":"q"},{"role":"assistant","content":"a"}]})+"\n")
   row={"task_id":"a","rollout_id":"1","kind":"objective","score_status":"scored","score":1,"sessions_path":"sessions.jsonl"}
   (p/"ledger.jsonl").write_text(json.dumps(row)+"\n"+json.dumps(row)+"\n")
   r=subprocess.run([sys.executable,str(ADAPTER/"export_sft.py"),"--ledger",str(p/"ledger.jsonl"),"--output",str(p/"out.json"),"--manifest",str(p/"manifest.json")],capture_output=True,text=True)
   self.assertNotEqual(r.returncode,0);self.assertFalse((p/"out.json").exists())
 def test_missing_reference_fails_before_network(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);(p/"candidate").write_text(json.dumps({"question":"q","answer":"x"*120})+"\n");(p/"reference").write_text(json.dumps({"question":"q","prediction":"answer not found.","termination":"answer not found."})+"\n");(p/"criteria").write_text(json.dumps({"id":1,"prompt":"q","dimension_weight":{"d":1},"criterions":{"d":[{"criterion":"x","explanation":"reason","weight":1}]}})+"\n")
   r=subprocess.run([sys.executable,str(ADAPTER/"score_openended.py"),"--criteria",str(p/"criteria"),"--candidate",str(p/"candidate"),"--reference",str(p/"reference"),"--out",str(p/"out")],capture_output=True,text=True,env={**os.environ,"DEEPSEEK_API_KEY":"not-used"})
   self.assertNotEqual(r.returncode,0);self.assertIn("incomplete or failed answer",r.stderr);self.assertFalse((p/"out").exists())
if __name__=="__main__":unittest.main()
