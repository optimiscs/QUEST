"""Single-process Qdrant local vector service for per-trajectory search evidence.

Qdrant local mode owns its storage lock; multiple Agent processes connect to
this one loopback service rather than opening the storage directory directly.
"""
import argparse
import hashlib
import math
import threading
import uuid

import requests
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from qdrant_client import QdrantClient, models

TASK = 'Given a web search query, retrieve relevant passages that answer the query'


class Entry(BaseModel):
    title: str = ''
    url: str = ''
    snippet: str = ''
    query: str = ''


class IndexRequest(BaseModel):
    scope: str = Field(pattern=r'^[0-9a-f]{64}$')
    evidence_id: str = Field(pattern=r'^E[0-9a-f]{64}$')
    entries: list[Entry]


class SearchRequest(BaseModel):
    scope: str = Field(pattern=r'^[0-9a-f]{64}$')
    query: str = Field(min_length=1)
    limit: int = Field(default=8, ge=1, le=50)
    evidence_id: str | None = Field(default=None, pattern=r'^E[0-9a-f]{64}$')
    source_query: str | None = None


def create_app(path, embedding_base, model, dimension=4096, client=None):
    app = FastAPI()
    db = client or QdrantClient(path=path)
    lock = threading.RLock()
    collection = 'search_' + hashlib.sha256(model.encode()).hexdigest()[:16] + '_' + str(dimension)
    with lock:
        if not db.collection_exists(collection):
            db.create_collection(collection, vectors_config=models.VectorParams(size=dimension, distance=models.Distance.COSINE))
        elif db.get_collection(collection).config.params.vectors.size != dimension:
            raise RuntimeError('Vector dimension differs from existing collection')

    def embed(texts, query=False):
        if not texts:
            return []
        inputs = [f'Instruct: {TASK}\nQuery:{x}' for x in texts] if query else texts
        r = requests.post(embedding_base.rstrip('/') + '/v1/embeddings', json={
            'model': model, 'input': inputs, 'truncate_prompt_tokens': 2048}, timeout=(5, 120))
        r.raise_for_status()
        data = sorted(r.json()['data'], key=lambda x: x['index'])
        vectors = [x['embedding'] for x in data]
        if len(vectors) != len(inputs) or any(len(v) != dimension or not all(math.isfinite(t) for t in v) for v in vectors):
            raise ValueError('invalid embedding vectors')
        return vectors

    @app.get('/health')
    def health():
        try:
            r = requests.get(embedding_base.rstrip('/') + '/v1/models', timeout=3)
            r.raise_for_status()
            ok = any(item.get('id') == model for item in r.json().get('data', []))
            return {'database': 'qdrant-local', 'collection': collection, 'embedding_ready': ok, 'model': model}
        except requests.RequestException:
            return {'database': 'qdrant-local', 'collection': collection, 'embedding_ready': False, 'model': model}

    @app.post('/index')
    def index(req: IndexRequest):
        try:
            entries = [x for x in req.entries if x.title or x.snippet]
            points = []
            for start in range(0, len(entries), 16):
                batch = entries[start:start + 16]
                vectors = embed([f'Title: {x.title}\nSnippet: {x.snippet}' for x in batch])
                for index, (entry, vector) in enumerate(zip(batch, vectors), start):
                    key = str(uuid.uuid5(uuid.NAMESPACE_URL, f'{req.scope}:{req.evidence_id}:{index}'))
                    points.append(models.PointStruct(id=key, vector=vector, payload={
                        'scope': req.scope, 'evidence_id': req.evidence_id, **entry.model_dump()}))
            with lock:
                if points:
                    db.upsert(collection_name=collection, points=points, wait=True)
            return {'indexed': len(points)}
        except (requests.RequestException, ValueError, KeyError, OSError) as exc:
            raise HTTPException(502, f'indexing failed: {type(exc).__name__}') from exc

    @app.post('/search')
    def search(req: SearchRequest):
        try:
            vector = embed([req.query], query=True)[0]
            filters = [models.FieldCondition(key='scope', match=models.MatchValue(value=req.scope))]
            if req.evidence_id:
                filters.append(models.FieldCondition(key='evidence_id', match=models.MatchValue(value=req.evidence_id)))
            if req.source_query is not None:
                filters.append(models.FieldCondition(key='query', match=models.MatchValue(value=req.source_query)))
            with lock:
                result = db.query_points(collection_name=collection, query=vector, limit=req.limit,
                    query_filter=models.Filter(must=filters), with_payload=True)
            return {'hits': [{'score': x.score, **x.payload} for x in result.points]}
        except (requests.RequestException, ValueError, KeyError, OSError) as exc:
            raise HTTPException(502, f'vector search failed: {type(exc).__name__}') from exc

    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--path', required=True)
    parser.add_argument('--embedding-base', default='http://127.0.0.1:19004')
    parser.add_argument('--model', default='QWEN3-EMBEDDING-8B')
    parser.add_argument('--port', type=int, default=18216)
    args = parser.parse_args()
    uvicorn.run(create_app(args.path, args.embedding_base, args.model), host='127.0.0.1', port=args.port, workers=1)
