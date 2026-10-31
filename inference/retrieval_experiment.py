"""Shared, deterministic building blocks for the GAIA retrieval experiment.

This module does not change the production visit tool. Model scoring and the
experiment runner must explicitly supply their scores to ``rank_chunks``.
"""
import re
import time
import os
from dataclasses import dataclass

import requests
import tiktoken
from rank_bm25 import BM25Okapi

ENCODING = tiktoken.get_encoding('cl100k_base')
TOKEN_RE = re.compile(r'[a-z0-9]+|[\u4e00-\u9fff]+', re.I)


def terms(text):
    result = []
    for match in TOKEN_RE.finditer(text.lower()):
        word = match.group()
        if '\u4e00' <= word[0] <= '\u9fff' and len(word) > 1:
            result.extend(word[i:i + 2] for i in range(len(word) - 1))
        else:
            result.append(word)
    return result


def count_tokens(text):
    return len(ENCODING.encode(text, disallowed_special=()))


@dataclass(frozen=True)
class Chunk:
    text: str
    index: int


def split_chunks(text, target=400, overlap=64):
    """Split paragraphs and Markdown tables while preserving table headers."""
    if target <= overlap or overlap < 0:
        raise ValueError('invalid chunk size or overlap')
    chunks = []
    blocks = []
    for section in re.split(r'\n\s*\n', text):
        lines = section.splitlines(keepends=True)
        current = []
        i = 0
        while i < len(lines):
            if (i + 1 < len(lines) and '|' in lines[i] and
                    re.match(r'^\s*\|?\s*:?-{3,}', lines[i + 1])):
                if current:
                    blocks.append(''.join(current)); current = []
                header = lines[i] + lines[i + 1]
                i += 2
                rows = []
                while i < len(lines) and '|' in lines[i] and lines[i].strip():
                    row = lines[i]
                    if rows and count_tokens(header + ''.join(rows) + row) > target:
                        blocks.append(header + ''.join(rows)); rows = []
                    rows.append(row); i += 1
                blocks.append(header + ''.join(rows))
            else:
                current.append(lines[i]); i += 1
        if current:
            blocks.append(''.join(current))
    for block in blocks:
        if not block.strip():
            continue
        # Never cut a single long table row: downstream budget checks can
        # reject it, but partial rows would corrupt the evidence.
        if '\n' in block and re.match(r'^\s*\|', block) and count_tokens(block) > target:
            chunks.append(Chunk(block, len(chunks)))
            continue
        start = 0
        while start < len(block):
            low, high = start + 1, len(block)
            while low < high:
                mid = (low + high + 1) // 2
                if count_tokens(block[start:mid]) <= target:
                    low = mid
                else:
                    high = mid - 1
            end = low
            chunks.append(Chunk(block[start:end], len(chunks)))
            if end == len(block):
                break
            next_start = end
            while next_start > start + 1 and count_tokens(block[next_start - 1:end]) <= overlap:
                next_start -= 1
            start = next_start
    return chunks


def bm25_rank(chunks, goal):
    docs = [terms(c.text) for c in chunks]
    query = terms(goal)
    if not query or not docs or not any(docs):
        return []
    scores = BM25Okapi(docs, k1=1.5, b=0.75).get_scores(query)
    q = set(query)
    # Restrict to lexical matches: BM25Okapi can assign negative IDF.
    indices = [i for i, doc in enumerate(docs) if q.intersection(doc)]
    return sorted(indices, key=lambda i: (-scores[i], i))


def reciprocal_rank_fusion(rankings, k=60):
    scores = {}
    for ranking in rankings:
        for position, index in enumerate(ranking, 1):
            scores[index] = scores.get(index, 0.0) + 1.0 / (k + position)
    return sorted(scores, key=lambda i: (-scores[i], i))


def pack(chunks, ranked, *, top_k=8, budget=8000):
    """Choose ranked blocks within budget and restore source order."""
    chosen = []
    for index in ranked[:top_k]:
        if not 0 <= index < len(chunks):
            raise ValueError('rank index outside chunk list')
        candidate = sorted(set(chosen + [index]))
        joined = '\n\n'.join(chunks[i].text for i in candidate)
        if count_tokens(joined) <= budget:
            chosen = candidate
    return '\n\n'.join(chunks[i].text for i in chosen), chosen


def select(text, goal, method, *, embedding_url=None, reranker_url=None):
    """Select evidence with an explicit experiment method and audit metadata."""
    if method not in {'bm25', 'embedding', 'bm25_embedding', 'bm25_reranker', 'hybrid', 'hybrid_reranker'}:
        raise ValueError('unknown retrieval method')
    started = time.monotonic()
    pool_url = os.getenv('VISIT_BM25_POOL_URL', '').strip()
    if pool_url:
        response = requests.post(pool_url.rstrip('/') + '/prepare',
                                 json={'text': text, 'goal': goal, 'need_bm25': method != 'embedding'},
                                 timeout=(5, 7200))
        response.raise_for_status()
        prepared = response.json()
        original_tokens = prepared['input_tokens']
        if not isinstance(original_tokens, int) or original_tokens < 0 or not isinstance(prepared.get('short_page'), bool):
            raise ValueError('invalid BM25 pool response')
        if prepared['short_page']:
            return text, {'reason': 'short_page', 'input_tokens': original_tokens, 'output_tokens': original_tokens}
        raw_chunks, lexical = prepared['chunks'], prepared['lexical']
        if not isinstance(raw_chunks, list) or not all(isinstance(value, str) for value in raw_chunks):
            raise ValueError('invalid BM25 pool chunks')
        if not isinstance(lexical, list) or any(type(index) is not int or not 0 <= index < len(raw_chunks) for index in lexical) or len(set(lexical)) != len(lexical):
            raise ValueError('invalid BM25 pool ranking')
        chunks = [Chunk(value, i) for i, value in enumerate(raw_chunks)]
    else:
        original_tokens = count_tokens(text)
        if original_tokens <= 2000:
            return text, {'reason': 'short_page', 'input_tokens': original_tokens, 'output_tokens': original_tokens}
        chunks = split_chunks(text)
        lexical = bm25_rank(chunks, goal) if method != 'embedding' else []
    dense = []
    durations = {}

    def score(url, indices, stage):
        if not url:
            raise ValueError(f'{stage} service URL required')
        start = time.monotonic()
        # The shared 8B services serialize GPU inference. A long page may
        # require minutes, and a request can also wait behind other agents;
        # a five-minute timeout turns ordinary queueing into lost evidence.
        response = requests.post(url.rstrip('/') + '/score', json={'goal': goal, 'passages': [chunks[i].text for i in indices]}, timeout=(10, 7200))
        response.raise_for_status()
        values = response.json()['scores']
        if len(values) != len(indices):
            raise ValueError(f'{stage} returned wrong number of scores')
        durations[stage] = time.monotonic() - start
        return sorted(zip(indices, values), key=lambda pair: (-pair[1], pair[0]))

    if method in {'embedding', 'hybrid', 'hybrid_reranker'}:
        dense = [i for i, _ in score(embedding_url, list(range(len(chunks))), 'embedding')]
    if method == 'embedding':
        ranking = dense
    elif method in {'hybrid', 'hybrid_reranker'}:
        ranking = reciprocal_rank_fusion([lexical[:32], dense[:32]])
    else:
        ranking = lexical
    candidate_limit = int(os.getenv('VISIT_RETRIEVAL_CANDIDATES', os.getenv('VISIT_RERANK_CANDIDATES', '32')))
    output_limit = int(os.getenv('VISIT_RETRIEVAL_TOP_K', '8'))
    if not 1 <= candidate_limit <= 512 or not 1 <= output_limit <= 512:
        raise ValueError('invalid retrieval limits')
    if method in {'bm25_reranker', 'hybrid_reranker'} and ranking:
        ranking = [i for i, _ in score(reranker_url, ranking[:candidate_limit], 'reranker')]
    elif method == 'bm25_embedding' and ranking:
        ranking = [i for i, _ in score(embedding_url, ranking[:candidate_limit], 'embedding')]
    if not ranking:
        selected, chosen = pack(chunks, list(range(len(chunks))), top_k=output_limit)
        if not selected:
            raise ValueError('no evidence block fits within the 8000 token budget')
        return selected, {'reason': 'no_retrieval_matches_prefix_fallback', 'input_tokens': original_tokens, 'output_tokens': count_tokens(selected), 'selected_indices': chosen}
    selected, chosen = pack(chunks, ranking, top_k=output_limit)
    if not selected:
        raise ValueError('no ranked evidence block fits within the 8000 token budget')
    return selected, {'reason': 'selected', 'input_tokens': original_tokens, 'output_tokens': count_tokens(selected), 'chunks': len(chunks), 'selected_indices': chosen, 'ranked_indices': ranking[:candidate_limit], 'stage_seconds': durations, 'total_seconds': time.monotonic() - started}
