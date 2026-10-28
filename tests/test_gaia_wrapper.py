import json, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'workspace/strict-reproduction/official-sources/gaia-leaderboard/scorer.py'
class GaiaWrapperTests(unittest.TestCase):
 @unittest.skipUnless(SOURCE.is_file(),'pinned upstream GAIA source not installed')
 def test_synthetic_exact_match_and_no_overwrite(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);submission=p/'submission.jsonl';reference=p/'reference.json';out=p/'out'
   submission.write_text('\n'.join(json.dumps(x) for x in [{'task_id':'fake-1','model_answer':'Paris'},{'task_id':'fake-2','model_answer':'Lyon'}])+'\n')
   reference.write_text(json.dumps([{'task_id':'fake-1','answer':'Paris'},{'task_id':'fake-2','answer':'London'}]))
   cmd=[sys.executable,str(ROOT/'evaluation/official_dataset/gaia.py'),'--submission',str(submission),'--reference',str(reference),'--out',str(out)]
   r=subprocess.run(cmd,capture_output=True,text=True,timeout=20);self.assertEqual(r.returncode,0,r.stderr)
   manifest=json.loads((out/'manifest.json').read_text());self.assertEqual((manifest['correct'],manifest['scored']),(1,2));self.assertIsNone(manifest['judge_model'])
   self.assertNotEqual(subprocess.run(cmd,capture_output=True,timeout=20).returncode,0)
if __name__=='__main__':unittest.main()
