"""Preserve QUEST's scoring API while vLLM serves the pooling models."""
import argparse
import math

import requests
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

TASK = 'Given a web search query, retrieve relevant passages that answer the query'
PREFIX = '<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the Instruct provided. Note that the answer can only be "yes" or "no".<|im_end|>\n<|im_start|>user\n'
SUFFIX = '<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n'


class Request(BaseModel):
    goal: str
    passages: list[str]


def create_app(role, model, upstream, tokenizer=None):
    app = FastAPI()

    @app.get('/health')
    def health():
        try:
            response = requests.get(upstream+'/health', timeout=3)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise HTTPException(503, 'vLLM unavailable') from exc
        return {'role': role, 'model': model, 'backend': 'vllm', 'max_num_seqs': 16}

    @app.post('/score')
    def score(request: Request):
        if not request.passages:
            return {'scores': []}
        try:
            if role == 'embedding':
                inputs = [f'Instruct: {TASK}\nQuery:{request.goal}'] + request.passages
                response = requests.post(upstream+'/v1/embeddings', json={'model': model, 'input': inputs, 'truncate_prompt_tokens': 2048}, timeout=(10, 7200))
                response.raise_for_status()
                rows = sorted(response.json()['data'], key=lambda row: row['index'])
                vectors = [row['embedding'] for row in rows]
                if len(vectors) != len(inputs):
                    raise ValueError('unexpected embedding count')
                query = vectors[0]
                query_norm = math.sqrt(sum(x*x for x in query))
                scores = []
                for vector in vectors[1:]:
                    norm = math.sqrt(sum(x*x for x in vector))
                    if len(vector) != len(query) or not norm or not query_norm:
                        raise ValueError('invalid embedding')
                    scores.append(sum(a*b for a,b in zip(query,vector))/(query_norm*norm))
            else:
                goal = request.goal
                if tokenizer is not None:
                    # Truncate documents before rendering the template. Truncating
                    # the combined prompt on the right would remove the assistant
                    # suffix and silently change the relevance score.
                    goal_tokens = tokenizer.encode(goal, add_special_tokens=False)
                    if len(goal_tokens) > 1500:
                        goal = tokenizer.decode(goal_tokens[:1500], skip_special_tokens=False, clean_up_tokenization_spaces=False)
                    envelope = PREFIX + f'<Instruct>: {TASK}\n<Query>: {goal}\n<Document>: ' + SUFFIX
                    budget = max(1, 2048 - len(tokenizer.encode(envelope, add_special_tokens=False)) - 16)
                else:
                    budget = 1500
                response = requests.post(upstream+'/score', json={'model': model, 'queries': [goal], 'documents': request.passages, 'max_tokens_per_doc': budget, 'truncate_prompt_tokens': 2048}, timeout=(10, 7200))
                response.raise_for_status()
                rows = sorted(response.json()['data'], key=lambda row: row['index'])
                scores = [row['score'] for row in rows]
                if len(scores) != len(request.passages):
                    raise ValueError('unexpected reranker score count')
            if not all(math.isfinite(value) for value in scores):
                raise ValueError('nonfinite scores')
            return {'scores': scores}
        except (requests.RequestException, KeyError, ValueError, TypeError) as exc:
            raise HTTPException(502, 'vLLM scoring failed') from exc
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--role', required=True, choices=('embedding','reranker'))
    parser.add_argument('--model', required=True)
    parser.add_argument('--upstream', required=True)
    parser.add_argument('--port', required=True, type=int)
    parser.add_argument('--tokenizer')
    args = parser.parse_args()
    tokenizer = None
    if args.role == 'reranker':
        from transformers import AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(args.tokenizer or args.model, local_files_only=True)
    uvicorn.run(create_app(args.role, args.model, args.upstream, tokenizer), host='127.0.0.1', port=args.port)
