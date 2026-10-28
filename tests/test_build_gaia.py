import json, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SCRIPT=ROOT/'web/build_gaia.py'
class BuilderTests(unittest.TestCase):
 def test_stopped_partial_and_finished_never_overwrite(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)/'run';(root/'logs').mkdir(parents=True); out=Path(d)/'view'
   result=root/'native.jsonl';result.write_text(json.dumps({'question':'Q','prediction':'42','messages':[{'content':'42'}],'num_rounds':1})+'\n')
   status={'cases':{'row0000':{'agent_state':'terminal','result_path':str(result),'judge_state':'scored','is_correct':True},'row0001':{'agent_state':'running'}}}
   original=json.dumps(status);(root/'status.json').write_text(original)
   def event(kind,partial=False):
    start=[{'event':'span_start','span_id':'task','kind':'task','epoch':100,'input':{'question':'Q'}},{'event':'span_start','span_id':'policy','kind':'policy_model','epoch':101}]
    end=[{'event':'span_end','span_id':'policy','kind':'policy_model','epoch':103,'seconds':2,'output':'answer'}]
    if not partial:
     start.append({'event':'span_start','span_id':'tool','kind':'tool','epoch':104,'input':{'tool_name':'search','tool_args':{'query':'q'}}})
     end.append({'event':'span_end','span_id':'tool','kind':'tool','epoch':106,'seconds':2,'output':'search result'})
     end.append({'event':'span_end','span_id':'task','kind':'task','epoch':110,'seconds':10})
    return '\n'.join(json.dumps(x) for x in start+end)+'\n'
   (root/'logs/row0000-agent-events.jsonl').write_text(event('task'));(root/'logs/row0001-agent-events.jsonl').write_text(event('task',True))
   cmd=[sys.executable,str(SCRIPT),'--run-root',str(root),'--output-dir',str(out),'--label','fake','--requested-cases','2','--include-running','--stopped-at','140']
   p=subprocess.run(cmd,text=True,capture_output=True);self.assertEqual(p.returncode,0,p.stderr)
   data=json.loads((out/'traces.json').read_text());self.assertEqual(len(data['cases']),2)
   self.assertTrue(data['run']['stopped']);self.assertEqual(data['run']['judgePassed'],1)
   self.assertEqual(data['cases'][0]['answer'],'42');self.assertEqual(data['cases'][1]['durationSeconds'],3)
   self.assertIn('已记录事件窗口',data['cases'][1]['answerNote'])
   self.assertTrue(data['cases'][1]['inProgress']);self.assertEqual((root/'status.json').read_text(),original)
   self.assertNotEqual(subprocess.run(cmd,capture_output=True).returncode,0)
if __name__=='__main__':unittest.main()
