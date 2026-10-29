import json,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class ObjectiveExportGuardTests(unittest.TestCase):
 def test_caller_claimed_full_score_does_not_authorize_objective_export(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);sessions=p/'sessions.jsonl';ledger=p/'ledger.jsonl';out=p/'out.json';manifest=p/'manifest.json'
   sessions.write_text(json.dumps({'is_final':True,'messages':[{'role':'user','content':'q'},{'role':'assistant','content':'a'}]})+'\n')
   ledger.write_text(json.dumps({'task_id':'a','rollout_id':'1','kind':'objective','score_status':'scored','score':1.0,'sessions_path':str(sessions)})+'\n')
   result=subprocess.run([sys.executable,str(ROOT/'contrib/deepseek_data/export_sft.py'),'--ledger',str(ledger),'--output',str(out),'--manifest',str(manifest)],capture_output=True,text=True)
   self.assertEqual(result.returncode,0,result.stderr)
   self.assertEqual(json.loads(out.read_text()),[])
   audit=json.loads(manifest.read_text());self.assertEqual(audit['decisions'][0]['excluded_reason'],'objective_verifier_unverified')
if __name__=='__main__':unittest.main()
