"""Shared, bounded process pool for QUEST webpage preparation and BM25."""
import argparse
import asyncio
import contextlib
import multiprocessing
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from inference.retrieval_experiment import bm25_rank, count_tokens, split_chunks


class PrepareRequest(BaseModel):
    text: str
    goal: str
    need_bm25: bool = True


def prepare_page(text, goal, need_bm25=True):
    count = count_tokens(text)
    if count <= 2000:
        return {'input_tokens': count, 'short_page': True, 'chunks': [], 'lexical': []}
    chunks = split_chunks(text)
    lexical = bm25_rank(chunks, goal) if need_bm25 else []
    return {'input_tokens': count, 'short_page': False,
            'chunks': [x.text for x in chunks], 'lexical': lexical}


def create_app(workers=8, queue_limit=128, admission_timeout=120):
    if workers < 1 or queue_limit < 0:
        raise ValueError('invalid worker or queue limit')
    # "admitted" includes jobs waiting inside ProcessPoolExecutor; it must not
    # be presented as the number of CPU workers currently executing.
    state = {'admitted': 0, 'waiting_for_admission': 0, 'completed': 0}

    @contextlib.asynccontextmanager
    async def lifespan(app):
        app.state.pool = ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context('spawn'))
        app.state.capacity = asyncio.Semaphore(workers + queue_limit)
        try:
            # Fail startup if a worker cannot import the retrieval dependencies.
            await asyncio.get_running_loop().run_in_executor(app.state.pool, prepare_page, 'startup check', 'check', True)
            yield
        finally:
            app.state.pool.shutdown(wait=True, cancel_futures=True)

    app = FastAPI(lifespan=lifespan)

    @app.get('/health')
    async def health():
        return {'workers': workers, 'queue_limit': queue_limit, **state}

    @app.post('/prepare')
    async def prepare(request: PrepareRequest):
        state['waiting_for_admission'] += 1
        try:
            try:
                await asyncio.wait_for(app.state.capacity.acquire(), timeout=admission_timeout)
            except asyncio.TimeoutError as exc:
                raise HTTPException(503, 'BM25 pool queue is full') from exc
        finally:
            state['waiting_for_admission'] -= 1
        state['admitted'] += 1
        future = None
        def release(done):
            state['admitted'] -= 1
            if not done.cancelled() and done.exception() is None:
                state['completed'] += 1
            app.state.capacity.release()
        try:
            future = asyncio.get_running_loop().run_in_executor(
                app.state.pool, prepare_page, request.text, request.goal, request.need_bm25)
            return await asyncio.shield(future)
        finally:
            if future is None:
                state['admitted'] -= 1
                app.state.capacity.release()
            elif future.done():
                release(future)
            else:
                # A disconnected/cancelled HTTP client must not free the slot
                # while its CPU job is still running in a worker.
                future.add_done_callback(release)

    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--queue-limit', type=int, default=128)
    parser.add_argument('--port', type=int, default=18215)
    args = parser.parse_args()
    uvicorn.run(create_app(args.workers, args.queue_limit), host='127.0.0.1', port=args.port, access_log=False)
