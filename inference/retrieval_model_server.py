"""Local Qwen3 8B retrieval service, one model role per GPU/process."""
import argparse
import math
import os
import threading

import torch
import torch.nn.functional as F
from fastapi import FastAPI
from pydantic import BaseModel
from transformers import AutoModel, AutoModelForCausalLM, AutoTokenizer
import uvicorn

TASK = 'Given a web search query, retrieve relevant passages that answer the query'
PREFIX = '<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the Instruct provided. Note that the answer can only be "yes" or "no".<|im_end|>\n<|im_start|>user\n'
SUFFIX = '<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n'


class Request(BaseModel):
    goal: str
    passages: list[str]


def create_app(role, path, batch_size=4, max_length=2048, device='cuda'):
    if role not in ('embedding', 'reranker') or batch_size < 1 or max_length < 1:
        raise ValueError('invalid retrieval role, batch size, or maximum length')
    app = FastAPI()
    tokenizer = AutoTokenizer.from_pretrained(path, padding_side='left', local_files_only=True)
    model_class = AutoModel if role == 'embedding' else AutoModelForCausalLM
    model = model_class.from_pretrained(path, torch_dtype=torch.bfloat16, local_files_only=True).to(device).eval()
    lock = threading.Lock()
    prefix = tokenizer.encode(PREFIX, add_special_tokens=False)
    suffix = tokenizer.encode(SUFFIX, add_special_tokens=False)
    if role == 'reranker' and max_length <= len(prefix) + len(suffix):
        raise ValueError('maximum length leaves no space for reranker input')

    @app.get('/health')
    def health():
        return {'role': role, 'model': os.path.basename(path), 'batch_size': batch_size}

    @app.post('/score')
    def score(request: Request):
        if not request.passages:
            return {'scores': []}
        with lock, torch.inference_mode():
            if role == 'embedding':
                texts = [f'Instruct: {TASK}\nQuery:{request.goal}'] + request.passages
                vectors = []
                for start in range(0, len(texts), batch_size):
                    inputs = tokenizer(texts[start:start + batch_size], padding=True, truncation=True, max_length=max_length, return_tensors='pt').to(device)
                    states = model(**inputs).last_hidden_state[:, -1]
                    vectors.append(F.normalize(states.float(), p=2, dim=1).cpu())
                vectors = torch.cat(vectors)
                scores = (vectors[1:] @ vectors[0]).tolist()
            else:
                scores = []
                false_id = tokenizer.convert_tokens_to_ids('no')
                true_id = tokenizer.convert_tokens_to_ids('yes')
                for start in range(0, len(request.passages), batch_size):
                    docs = request.passages[start:start + batch_size]
                    pairs = [f'<Instruct>: {TASK}\n<Query>: {request.goal}\n<Document>: {doc}' for doc in docs]
                    inputs = tokenizer(pairs, padding=False, truncation=True, max_length=max_length-len(prefix)-len(suffix), return_attention_mask=False)
                    inputs['input_ids'] = [prefix + ids + suffix for ids in inputs['input_ids']]
                    batch = tokenizer.pad(inputs, padding=True, return_tensors='pt').to(device)
                    logits = model(**batch).logits[:, -1, :]
                    scores.extend(torch.softmax(logits[:, [false_id, true_id]].float(), dim=1)[:, 1].cpu().tolist())
        return {'scores': scores}
    # Do not report a healthy service until an actual model forward succeeds.
    probe = score(Request(goal='What is the capital of France?', passages=['Paris is the capital of France.', 'The moon orbits Earth.']))
    if len(probe['scores']) != 2 or not all(math.isfinite(value) for value in probe['scores']):
        raise RuntimeError('retrieval scoring preflight failed')
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--role', required=True, choices=['embedding', 'reranker'])
    parser.add_argument('--model', required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--batch-size', type=int, default=4)
    args = parser.parse_args()
    uvicorn.run(create_app(args.role, args.model, args.batch_size), host='127.0.0.1', port=args.port)
