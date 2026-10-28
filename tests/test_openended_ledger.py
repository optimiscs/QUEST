import hashlib,json,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SCRIPT=ROOT/'contrib/deepseek_data/build_openended_ledger.py'
class LedgerTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.p=Path(self.tmp.name)
  self.candidate=self.p/'candidate.jsonl';self.reference=self.p/'reference.jsonl';self.sessions=self.p/'sessions.jsonl';self.score=self.p/'score.jsonl';self.out=self.p/'ledger.jsonl'
  self.candidate.write_text(json.dumps({'question':'Test question with source requirement','iter':1,'prediction':'a'*120})+'\n')
  self.reference.write_text(json.dumps({'question':'Test question with independent reference requirement','prediction':'b'*120,'termination':'answer'})+'\n')
  self.sessions.write_text(json.dumps({'is_final':True,'messages':[{'role':'user','content':'q'},{'role':'assistant','content':'a'}]})+'\n')
  self.score.write_text(json.dumps({'id':'task-1','iter':1,'query':'Test question','final_score':0.8})+'\n')
  self.status={'complete':True,'exit_code':0,'result_rows':1,'valid_scores':1,'output_sha256':self.sha(self.score),'input_sha256':{'candidate':self.sha(self.candidate),'reference':self.sha(self.reference)}}
 def tearDown(self):self.tmp.cleanup()
 def sha(self,p):return hashlib.sha256(p.read_bytes()).hexdigest()
 def execute(self):
  self.score.with_suffix('.status.json').write_text(json.dumps(self.status))
  return subprocess.run([sys.executable,str(SCRIPT),'--score',str(self.score),'--candidate',str(self.candidate),'--reference',str(self.reference),'--sessions',str(self.sessions),'--reference-kind','independent_agent','--out',str(self.out)],capture_output=True,text=True)
 def test_incomplete_status_is_not_accepted(self):
  self.status['complete']=False;r=self.execute();self.assertNotEqual(r.returncode,0);self.assertFalse(self.out.exists())
 def test_reference_must_match_scored_question(self):
  self.reference.write_text(json.dumps({'question':'Different question','prediction':'b'*120,'termination':'answer'})+'\n');self.status['input_sha256']['reference']=self.sha(self.reference)
  r=self.execute();self.assertNotEqual(r.returncode,0);self.assertFalse(self.out.exists())
 def test_partial_counts_and_iteration_mismatch_are_rejected(self):
  self.status['valid_scores']=0;r=self.execute();self.assertNotEqual(r.returncode,0);self.assertFalse(self.out.exists())
  self.status['valid_scores']=1;self.score.write_text(json.dumps({'id':'task-1','iter':2,'query':'Test question','final_score':0.8})+'\n')
  self.status['output_sha256']=self.sha(self.score)
  r=self.execute();self.assertNotEqual(r.returncode,0);self.assertFalse(self.out.exists())
 def test_legacy_status_without_score_time_hash_is_rejected(self):
  self.status.pop('output_sha256');r=self.execute();self.assertNotEqual(r.returncode,0);self.assertFalse(self.out.exists())
 def test_tampered_score_output_is_rejected(self):
  self.score.write_text(self.score.read_text().replace('0.8','0.9'))
  r=self.execute();self.assertNotEqual(r.returncode,0);self.assertFalse(self.out.exists())
 def test_missing_iteration_matches_author_none_and_defaults_ledger(self):
  row=json.loads(self.candidate.read_text());row.pop('iter');self.candidate.write_text(json.dumps(row)+'\n');self.status['input_sha256']['candidate']=self.sha(self.candidate)
  score=json.loads(self.score.read_text());score['iter']=None;self.score.write_text(json.dumps(score)+'\n');self.status['output_sha256']=self.sha(self.score)
  r=self.execute();self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(json.loads(self.out.read_text())['rollout_id'],'1')
 def test_export_requires_unchanged_scoring_evidence(self):
  r=self.execute();self.assertEqual(r.returncode,0,r.stderr)
  exporter=ROOT/'contrib/deepseek_data/export_sft.py'
  def run_export(suffix):
   out=self.p/('out'+suffix+'.json');manifest=self.p/('manifest'+suffix+'.json')
   result=subprocess.run([sys.executable,str(exporter),'--ledger',str(self.out),'--output',str(out),'--manifest',str(manifest)],capture_output=True,text=True)
   return result,out
  result,out=run_export('valid');self.assertEqual(result.returncode,0,result.stderr);self.assertTrue(out.exists())
  for name in ('sessions','candidate','reference','score'):
   file=getattr(self,name);original=file.read_text()
   file.write_text(original+' ')
   result,out=run_export(name);self.assertNotEqual(result.returncode,0,name);self.assertFalse(out.exists());file.write_text(original)
  status=self.score.with_suffix('.status.json');status.write_text(status.read_text()+' ')
  result,out=run_export('status');self.assertNotEqual(result.returncode,0);self.assertFalse(out.exists())
 def test_continued_reference_cannot_be_declared_independent(self):
  ref=json.loads(self.reference.read_text());ref['reference_kind']='provisional_continuation';ref['termination']='continuation_after_tool_limit'
  self.reference.write_text(json.dumps(ref)+'\n');self.status['input_sha256']['reference']=self.sha(self.reference)
  r=self.execute();self.assertNotEqual(r.returncode,0);self.assertFalse(self.out.exists())
 def test_complete_aligned_inputs_are_accepted(self):
  r=self.execute();self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(json.loads(self.out.read_text())['score_status'],'scored')
if __name__=='__main__':unittest.main()
