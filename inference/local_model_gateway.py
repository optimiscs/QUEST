#!/usr/bin/env python3
"""Route QUEST policy, webpage summary, and memory calls to OpenAI-compatible servers.

This optional gateway preserves the original inference entry point. It injects the
selected few-shot examples only for summaries and can disable auxiliary thinking.
The gateway does not start models or evaluation jobs.
"""
import argparse
import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from aiohttp import ClientError, ClientSession, ClientTimeout, web


def build_parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', type=int, default=18300)
    p.add_argument('--policy-upstream', required=True, help='OpenAI API base, e.g. http://127.0.0.1:8000/v1')
    p.add_argument('--aux-upstream', action='append', required=True, help='Auxiliary API base; repeat to distribute requests')
    p.add_argument('--policy-alias', default='QWEN38-POLICY')
    p.add_argument('--memory-alias', default='QWEN38-MEMORY')
    p.add_argument('--summary-alias', default='QWEN38-SUMMARY')
    p.add_argument('--policy-model', required=True)
    p.add_argument('--aux-model', required=True)
    p.add_argument('--fewshot', type=Path, help='JSON array of user/assistant messages, inserted only for summaries')
    p.add_argument('--disable-aux-thinking', action='store_true')
    p.add_argument('--timeout', type=float, default=900)
    p.add_argument('--metrics', type=Path, help='Append metadata-only JSONL; no prompt or response text')
    return p


def validate_fewshot(path):
    if not path:
        return []
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, list) or len(data) % 2:
        raise ValueError('few-shot file must contain user/assistant message pairs')
    for i, msg in enumerate(data):
        if not isinstance(msg, dict) or msg.get('role') != ('user' if i % 2 == 0 else 'assistant') or not isinstance(msg.get('content'), str):
            raise ValueError('invalid few-shot message')
    return data


class Router:
    def __init__(self, args, fewshot):
        self.args = args
        self.fewshot = fewshot
        self.active = [0] * len(args.aux_upstream)
        self.policy_active = 0
        self.tie = 0
        self.session = None

    async def start(self, app):
        self.session = ClientSession(timeout=ClientTimeout(total=self.args.timeout))

    async def close(self, app):
        if self.session:
            await self.session.close()

    def choose_aux(self):
        index = min(range(len(self.active)), key=lambda i: (self.active[i], (i - self.tie) % len(self.active)))
        self.tie = (index + 1) % len(self.active)
        return index

    def record(self, info):
        if self.args.metrics:
            self.args.metrics.parent.mkdir(parents=True, exist_ok=True)
            with self.args.metrics.open('a', encoding='utf-8') as out:
                out.write(json.dumps(info, ensure_ascii=False) + '\n')

    async def handle(self, request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({'error': 'invalid JSON'}, status=400)
        if not isinstance(body, dict) or body.get('stream'):
            return web.json_response({'error': 'object requests only; streaming is not supported'}, status=400)
        alias = body.get('model')
        aliases = {self.args.policy_alias:'policy', self.args.summary_alias:'summary', self.args.memory_alias:'memory'}
        kind = aliases.get(alias)
        if kind is None:
            return web.json_response({'error': 'unknown model alias'}, status=400)
        if kind == 'summary':
            msgs = body.get('messages')
            if not isinstance(msgs, list) or not msgs:
                return web.json_response({'error': 'summary messages must be a nonempty array'}, status=400)
            body['messages'] = msgs[:-1] + self.fewshot + msgs[-1:]
        if kind == 'policy':
            upstream = self.args.policy_upstream
            body['model'] = self.args.policy_model
            index = None
            self.policy_active += 1
        else:
            index = self.choose_aux()
            upstream = self.args.aux_upstream[index]
            body['model'] = self.args.aux_model
            if self.args.disable_aux_thinking:
                body['chat_template_kwargs'] = {**body.get('chat_template_kwargs', {}), 'enable_thinking': False}
            self.active[index] += 1
        started = time.monotonic()
        status = 502
        info = {'id':uuid.uuid4().hex, 'kind':kind, 'upstream_index':index, 'epoch':time.time(),
                'active_aux_at_start':list(self.active), 'active_policy_at_start':self.policy_active}
        try:
            async with self.session.post(upstream.rstrip('/') + '/chat/completions', json=body) as response:
                payload = await response.read()
                status = response.status
                ctype = response.headers.get('Content-Type', 'application/json').split(';')[0]
                return web.Response(body=payload, status=status, content_type=ctype)
        except (asyncio.TimeoutError, ClientError, OSError) as exc:
            status = 504 if isinstance(exc, asyncio.TimeoutError) else 502
            return web.json_response({'error':type(exc).__name__}, status=status)
        finally:
            if index is None:
                self.policy_active -= 1
            else:
                self.active[index] -= 1
            info.update(status=status, wall_seconds=round(time.monotonic()-started, 6))
            try:
                await asyncio.to_thread(self.record, info)
            except Exception:
                logging.exception("Unable to write gateway metrics")


def make_app(args):
    router = Router(args, validate_fewshot(args.fewshot))
    app = web.Application(client_max_size=32 * 1024 * 1024)
    app.router.add_post('/v1/chat/completions', router.handle)
    app.on_startup.append(router.start)
    app.on_cleanup.append(router.close)
    return app


def main():
    args = build_parser().parse_args()
    aliases = {args.policy_alias, args.memory_alias, args.summary_alias}
    if len(aliases) != 3 or args.timeout <= 0:
        raise SystemExit('aliases must be distinct and timeout must be positive')
    web.run_app(make_app(args), host=args.host, port=args.port)

if __name__ == '__main__':
    main()
