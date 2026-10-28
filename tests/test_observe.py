import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class ObserverTests(unittest.TestCase):
 def test_stage_spans_and_redaction(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d);source=path/'src';source.mkdir();events=path/'logs/events.jsonl'
   (source/'tool_visit.py').write_text('def jina_readpage(url):\n return "web:"+url\ndef call_server(msgs):\n return "summary:"+msgs[0]["content"]\n')
   (source/'run.py').write_text('import tool_visit\nprint(tool_visit.jina_readpage("https://example.test"))\nprint(tool_visit.call_server([{"content":"secret-test-value"}]))\n')
   env={**os.environ,'FAKE_API_KEY':'secret-test-value'}
   p=subprocess.run([sys.executable,str(ROOT/'inference/observe.py'),'--events',str(events),'--source-root',str(source),str(source/'run.py')],env=env,text=True,capture_output=True)
   self.assertEqual(p.returncode,0,p.stderr)
   rows=[json.loads(x) for x in events.read_text().splitlines()]
   self.assertEqual([r['kind'] for r in rows if r['event']=='span_end'],['reader','summary'])
   self.assertTrue(all(r['seconds']>=0 for r in rows if r['event']=='span_end'))
   self.assertNotIn('secret-test-value',events.read_text())
   self.assertIn('[REDACTED]',events.read_text())
   self.assertEqual(events.stat().st_mode & 0o777,0o600)
if __name__=='__main__':unittest.main()
