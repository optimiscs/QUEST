import asyncio
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from aiohttp import ClientSession, web

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('quest_local_model_gateway', ROOT / 'inference/local_model_gateway.py')
APP_NAME = web.AppKey('name', str)
gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)

class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runs = []
        self.received = []
        async def upstream(request):
            body = await request.json()
            self.received.append((request.app[APP_NAME], body))
            await asyncio.sleep(.05)
            return web.json_response({'choices':[{'message':{'content':'ok'}}], 'usage':{'completion_tokens':1}})
        async def launch(app):
            runner = web.AppRunner(app); await runner.setup()
            site = web.TCPSite(runner, '127.0.0.1', 0); await site.start(); self.runs.append(runner)
            return 'http://127.0.0.1:%s' % site._server.sockets[0].getsockname()[1]
        urls=[]
        for name in ('policy','aux0','aux1'):
            app=web.Application();app[APP_NAME]=name;app.router.add_post('/v1/chat/completions',upstream)
            urls.append((await launch(app))+'/v1')
        self.few = Path(self.tmp.name)/'few.json'
        self.few.write_text(json.dumps([{'role':'user','content':'example'},{'role':'assistant','content':'result'}]))
        args=SimpleNamespace(policy_upstream=urls[0],aux_upstream=urls[1:],policy_alias='p',summary_alias='s',memory_alias='m',policy_model='policy-real',aux_model='aux-real',fewshot=self.few,disable_aux_thinking=True,timeout=2,metrics=Path(self.tmp.name)/'metrics.jsonl')
        self.gateway_url=(await launch(gateway.make_app(args)))+'/v1/chat/completions'
        self.session=ClientSession()
        self.metrics=args.metrics

    async def asyncTearDown(self):
        await self.session.close()
        for runner in reversed(self.runs): await runner.cleanup()
        self.tmp.cleanup()

    async def post(self, model):
        async with self.session.post(self.gateway_url,json={'model':model,'messages':[{'role':'user','content':'query'}]}) as r:
            return r.status, await r.json()

    async def test_routing_fewshot_thinking_and_metrics(self):
        results=await asyncio.gather(self.post('s'),self.post('s'),self.post('p'),self.post('m'))
        self.assertTrue(all(status==200 for status,_ in results))
        summaries=[body for _,body in self.received if len(body['messages'])==3]
        self.assertEqual(len(summaries),2)
        self.assertEqual({name for name,body in self.received if len(body['messages'])==3},{'aux0','aux1'})
        self.assertTrue(all(body['chat_template_kwargs']['enable_thinking'] is False for body in summaries))
        policy=next(body for name,body in self.received if name=='policy')
        self.assertEqual(policy['model'],'policy-real')
        self.assertNotIn('chat_template_kwargs',policy)
        rows=[json.loads(line) for line in self.metrics.read_text().splitlines()]
        self.assertEqual(len(rows),4)
        self.assertNotIn('query',self.metrics.read_text())
        self.assertEqual((await self.post('bad'))[0],400)

    async def test_fewshot_validation(self):
        self.few.write_text('[{"role":"assistant","content":"x"}]')
        with self.assertRaises(ValueError):gateway.validate_fewshot(self.few)

if __name__=='__main__': unittest.main()

class MetricsFailureTests(GatewayTests):
    async def test_metrics_failure_does_not_replace_response(self):
        self.metrics.mkdir()
        status, body = await self.post('p')
        self.assertEqual(status, 200)
        self.assertEqual(body['choices'][0]['message']['content'], 'ok')
