import ast, importlib.util, json, unittest
from pathlib import Path
root=Path(__file__).resolve().parents[1];spec=importlib.util.spec_from_file_location('dsml',root/'contrib/deepseek_data/dsml.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
class DSMLTests(unittest.TestCase):
 def test_multiple_calls_preserve_prose_and_types(self):
  raw='Before. <｜DSML｜function_calls><｜DSML｜invoke name="search"><｜DSML｜parameter name="query" string="false">["abc"]</｜DSML｜parameter></｜DSML｜invoke><｜DSML｜invoke name="visit"><｜DSML｜parameter name="goal" string="true">123</｜DSML｜parameter></｜DSML｜invoke></｜DSML｜function_calls> After.'
  out=mod.normalize_dsml(raw)
  self.assertIn('Before.',out);self.assertIn('After.',out);self.assertEqual(out.count('<tool_call>'),2)
  calls=[json.loads(x.split('</tool_call>')[0]) for x in out.split('<tool_call>')[1:]]
  self.assertEqual(calls[0]['arguments']['query'],['abc']);self.assertEqual(calls[1]['arguments']['goal'],'123')
 def test_malformed_preserved(self):
  raw='prefix <｜DSML｜invoke name="search"><bad>raw</bad></｜DSML｜invoke> suffix'
  self.assertEqual(mod.normalize_dsml(raw),raw)
 def test_four_runtime_entrypoints_use_shared_adapter(self):
  for rel in ('inference/react_agent.py','task/obj_task/generation_agent.py','task/open_ended_task/generation_agent_longform.py','task/open_ended_task/ref_gen/react_agent_ref_gen.py'):
   tree=ast.parse((root/rel).read_text())
   self.assertTrue(any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='normalize_dsml' for n in ast.walk(tree)),rel)
 def test_incomplete_tool_call_preserves_adjacent_text(self):
  out=mod.close_incomplete_tool_call('prose <tool_call> {"name":"search","arguments":{"q":1}} trailing')
  self.assertIn('prose ',out);self.assertIn('</tool_call> trailing',out)
  self.assertEqual(mod.close_incomplete_tool_call('x <tool_call> broken'),'x <tool_call> broken')
if __name__=='__main__':unittest.main()
