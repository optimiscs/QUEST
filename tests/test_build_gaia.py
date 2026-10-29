import json, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SCRIPT=ROOT/'web/build_gaia.py'
class BuilderTests(unittest.TestCase):
 def test_browsecomp_displays_final_exact_answer_without_changing_source(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)/'run';(root/'logs').mkdir(parents=True);out=Path(d)/'view'
   source=root/'native.jsonl';source.write_text(json.dumps({'question':'Q','prediction':'answer not found.','messages':[{'content':'</think>\nExact Answer: Morris Museum\nConfidence: 75%'}],'num_rounds':100})+'\n')
   (root/'status.json').write_text(json.dumps({'cases':{'row0000':{'agent_state':'terminal','result_path':str(source),'judge_state':'scored','is_correct':True}}}))
   events=[{'event':'span_start','span_id':'task','kind':'task','epoch':100,'input':{'question':'Q'}},{'event':'span_start','span_id':'policy','kind':'policy_model','epoch':101},{'event':'span_end','span_id':'policy','kind':'policy_model','epoch':103,'seconds':2,'output':'final'},{'event':'span_end','span_id':'task','kind':'task','epoch':110,'seconds':10}]
   (root/'logs/row0000-agent-events.jsonl').write_text('\n'.join(json.dumps(x) for x in events)+'\n')
   cmd=[sys.executable,str(SCRIPT),'--run-root',str(root),'--output-dir',str(out),'--label','fake','--benchmark','BrowseComp','--requested-cases','1']
   result=subprocess.run(cmd,text=True,capture_output=True);self.assertEqual(result.returncode,0,result.stderr)
   case=json.loads((out/'traces.json').read_text())['cases'][0]
   self.assertEqual(case['answer'],'Morris Museum');self.assertIn('原生预测未识别',case['answerNote']);self.assertTrue(case['correct'])
   self.assertEqual(json.loads(source.read_text())['prediction'],'answer not found.')
 def test_running_retry_replaces_stale_scored_view(self):
  with tempfile.TemporaryDirectory() as d:
   base=Path(d);root=base/'embedding-direct';(root/'logs').mkdir(parents=True);(base/'checks').mkdir();retry=base/'retry';(retry/'logs').mkdir(parents=True)
   result=root/'native.jsonl';result.write_text(json.dumps({'question':'Q','prediction':'42','messages':[],'num_rounds':1})+'\n')
   (root/'status.json').write_text(json.dumps({'cases':{'row0000':{'agent_state':'terminal','result_path':str(result),'judge_state':'scored','is_correct':True}}}))
   (base/'checks/retry-required.json').write_text(json.dumps({'cases':[{'group':'embedding-direct','case':'row0000','status':'running_retry','retry_root':str(retry)}]}))
   events=[{'event':'span_start','span_id':'task','kind':'task','epoch':100,'input':{'question':'Q'}},{'event':'span_start','span_id':'policy','kind':'policy_model','epoch':101},{'event':'span_end','span_id':'policy','kind':'policy_model','epoch':103,'seconds':2,'output':'retry output'}]
   (retry/'logs/row0000-agent-events.jsonl').write_text('\n'.join(json.dumps(x) for x in events)+'\n')
   out=base/'view';cmd=[sys.executable,str(SCRIPT),'--run-root',str(root),'--output-dir',str(out),'--label','fake','--requested-cases','1','--include-running']
   result=subprocess.run(cmd,text=True,capture_output=True);self.assertEqual(result.returncode,0,result.stderr)
   case=json.loads((out/'traces.json').read_text())['cases'][0]
   self.assertTrue(case['inProgress']);self.assertIsNone(case['correct']);self.assertIn('正在重跑',case['judge'])
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
   (root/'checks').mkdir();(root/'checks/row0000-score-receipt.json').write_text(json.dumps({'status':'scored','is_correct':False,'judgment':'false'}))
   alternate=Path(d)/'view-wide';other=[sys.executable,str(SCRIPT),'--run-root',str(root),'--output-dir',str(alternate),'--label','fake','--requested-cases','2','--include-running','--stopped-at','140','--benchmark','widesearch']
   result=subprocess.run(other,text=True,capture_output=True);self.assertEqual(result.returncode,0,result.stderr)
   wide=json.loads((alternate/'traces.json').read_text());self.assertEqual(wide['run']['benchmark'],'widesearch');self.assertEqual(wide['cases'][0]['field'],'widesearch');self.assertFalse(wide['cases'][0]['correct']);self.assertEqual(wide['run']['judgeScored'],1)

if __name__=='__main__':unittest.main()
