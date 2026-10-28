import copy,importlib.util,json,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];FILE=ROOT/'task/obj_eval/summary_audit.py';spec=importlib.util.spec_from_file_location('objective_audit',FILE);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def node(ident,score=1,status='passed',children=None):return {'id':ident,'score':score,'status':status,'critical':False,'strategy':'parallel','children':children or []}
def summary():return {'final_score':1,'eval_breakdown':[{'verification_tree':node('root',children=[node('check')])}]}
class ObjectiveAuditTests(unittest.TestCase):
 def test_structural_pass_never_authorizes_training(self):
  result=m.audit_summary(summary());self.assertEqual(result['structural_status'],'full_credit_consistent');self.assertFalse(result['training_eligible']);self.assertEqual(result['provenance_status'],'unverified')
 def test_full_score_with_bad_nodes_is_rejected(self):
  for mutation in ('failed','duplicate','missing','mismatch','nan'):
   x=summary();tree=x['eval_breakdown'][0]['verification_tree']
   if mutation=='failed':tree['children'][0].update(score=0,status='failed')
   if mutation=='duplicate':tree['children'].append(copy.deepcopy(tree['children'][0]))
   if mutation=='missing':tree['children']=[]
   if mutation=='mismatch':tree['score']=0
   if mutation=='nan':x['final_score']=float('nan')
   with self.subTest(mutation=mutation),self.assertRaises(ValueError):m.audit_summary(x)
 def test_partial_score_never_approved(self):
  x=summary();x['final_score']=0;x['eval_breakdown'][0]['verification_tree'].update(score=0,status='failed');x['eval_breakdown'][0]['verification_tree']['children'][0].update(score=0,status='failed')
  self.assertEqual(m.audit_summary(x)['structural_status'],'not_full_credit');self.assertFalse(m.audit_summary(x)['training_eligible'])
 def test_cli_never_overwrites(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);source=p/'summary.json';dest=p/'audit.json';source.write_text(json.dumps(summary()))
   cmd=[sys.executable,str(FILE),'--summary',str(source),'--output',str(dest)]
   self.assertEqual(subprocess.run(cmd,capture_output=True).returncode,0);self.assertFalse(json.loads(dest.read_text())['training_eligible']);self.assertEqual(dest.stat().st_mode&0o777,0o600)
   self.assertNotEqual(subprocess.run(cmd,capture_output=True).returncode,0)
if __name__=='__main__':unittest.main()
