import contextlib,importlib.util,io,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];file=ROOT/'contrib/deepseek_data/score_openended.py';spec=importlib.util.spec_from_file_location('score_openended',file);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class ScoreSafetyTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.p=Path(self.tmp.name)
  (self.p/'criteria').write_text(json.dumps({'id':1,'prompt':'q','dimension_weight':{'d':1},'criterions':{'d':[{'criterion':'x','explanation':'reason','weight':1}]}})+'\n')
  (self.p/'candidate').write_text(json.dumps({'question':'q with sources','iter':1,'prediction':'a'*120})+'\n')
  (self.p/'reference').write_text(json.dumps({'question':'q reference','prediction':'b'*120})+'\n')
  self.out=self.p/'score.jsonl';self.argv=['--criteria',str(self.p/'criteria'),'--candidate',str(self.p/'candidate'),'--reference',str(self.p/'reference'),'--out',str(self.out)]
 def tearDown(self):self.tmp.cleanup()
 def call(self,runner):
  with patch.dict(os.environ,{'DEEPSEEK_API_KEY':'fake-not-network'}),contextlib.redirect_stdout(io.StringIO()):return m.main(self.argv,runner=runner)
 def good_result(self,query='q'):
  return {'id':1,'query':query,'iter':1,'final_score':0.8,'total_score_a':8,'total_score_b':2,'detailed_evaluations':{'d':[{'criterion_name':'x','category':'d','weight':1,'score_a':8,'score_b':2}]}}
 def test_complete_result_is_hashed_and_no_overwrite(self):
  def fake(cmd,**kw):self.out.write_text(json.dumps(self.good_result())+'\n');return SimpleNamespace(returncode=0)
  self.assertEqual(self.call(fake),0);meta=json.loads(self.out.with_suffix('.status.json').read_text());self.assertTrue(meta['complete']);self.assertEqual(meta['output_sha256'],m.sha(self.out))
  with self.assertRaises(FileExistsError):self.call(fake)
 def test_synthetic_scoring_ledger_and_export_chain(self):
  def fake(cmd,**kw):self.out.write_text(json.dumps(self.good_result())+'\n');return SimpleNamespace(returncode=0)
  self.assertEqual(self.call(fake),0)
  meta=json.loads(self.out.with_suffix('.status.json').read_text())
  sessions=self.p/'sessions.jsonl';sessions.write_text(json.dumps({'is_final':True,'messages':[{'role':'user','content':'q'},{'role':'assistant','content':'a'}]})+'\n')
  ledger=self.p/'ledger.jsonl';base=ROOT/'contrib/deepseek_data'
  cmd=[sys.executable,str(base/'build_openended_ledger.py'),'--score',str(self.out),'--candidate',meta['input_snapshots']['candidate'],'--reference',meta['input_snapshots']['reference'],'--sessions',str(sessions),'--reference-kind','independent_agent','--out',str(ledger)]
  result=subprocess.run(cmd,text=True,capture_output=True);self.assertEqual(result.returncode,0,result.stderr)
  output=self.p/'sft.json';manifest=self.p/'sft.manifest.json'
  result=subprocess.run([sys.executable,str(base/'export_sft.py'),'--ledger',str(ledger),'--output',str(output),'--manifest',str(manifest)],text=True,capture_output=True)
  self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(len(json.loads(output.read_text())),1)
 def test_evaluator_uses_frozen_inputs(self):
  original=(self.p/'candidate').read_bytes()
  def fake(cmd,**kw):
   snapshot=Path(cmd[cmd.index('--answer_to_eval')+1]);self.assertEqual(snapshot.read_bytes(),original)
   (self.p/'candidate').write_text('changed after snapshot')
   self.out.write_text(json.dumps(self.good_result())+'\n');return SimpleNamespace(returncode=0)
  self.assertEqual(self.call(fake),0);meta=json.loads(self.out.with_suffix('.status.json').read_text())
  self.assertEqual(meta['input_sha256']['candidate'],m.sha(Path(meta['input_snapshots']['candidate'])))
  self.assertNotEqual(meta['input_sha256']['candidate'],m.sha(self.p/'candidate'))
 def test_timeout_preserves_partial_result_and_failure(self):
  def fake(cmd,**kw):self.out.write_text('partial');raise subprocess.TimeoutExpired(cmd,1)
  self.assertEqual(self.call(fake),1);meta=json.loads(self.out.with_suffix('.status.json').read_text());self.assertFalse(meta['complete']);self.assertEqual(meta['error_type'],'TimeoutExpired');self.assertEqual(self.out.read_text(),'partial');self.assertTrue(meta['output_sha256'])
 def test_success_exit_with_wrong_result_is_not_complete(self):
  def fake(cmd,**kw):self.out.write_text(json.dumps(self.good_result('wrong'))+'\n');return SimpleNamespace(returncode=0)
  self.assertEqual(self.call(fake),1);self.assertFalse(json.loads(self.out.with_suffix('.status.json').read_text())['complete'])
 def test_zero_denominator_and_missing_criterion_are_rejected(self):
  expected=m.validate_inputs(m.read_jsonl(self.p/'criteria'),m.read_jsonl(self.p/'candidate'),m.read_jsonl(self.p/'reference'))
  row=self.good_result();row['total_score_a']=row['total_score_b']=0;row['final_score']=0
  self.assertFalse(m.validate_results([row],expected))
  row=self.good_result();row['detailed_evaluations']['d']=[]
  self.assertFalse(m.validate_results([row],expected))
 def test_inconsistent_aggregate_is_rejected(self):
  expected=m.validate_inputs(m.read_jsonl(self.p/'criteria'),m.read_jsonl(self.p/'candidate'),m.read_jsonl(self.p/'reference'))
  row=self.good_result();row['detailed_evaluations']['d'][0]['score_a']=1
  self.assertFalse(m.validate_results([row],expected))
 def test_ambiguous_prompt_fails_before_child(self):
  self.p.joinpath('criteria').write_text('\n'.join(json.dumps(x) for x in [{'id':1,'prompt':'q','dimension_weight':{'d':1},'criterions':{'d':[{'criterion':'x','explanation':'reason','weight':1}]}},{'id':2,'prompt':'q with','dimension_weight':{'d':1},'criterions':{'d':[{'criterion':'x','explanation':'reason','weight':1}]}}])+'\n')
  with self.assertRaises(ValueError):self.call(lambda *a,**k:self.fail('must not run'))
  self.assertFalse(self.out.exists())
if __name__=='__main__':unittest.main()
