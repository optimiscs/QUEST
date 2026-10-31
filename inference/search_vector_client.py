"""Parse search results and connect them to the scoped vector service."""
import hashlib
import json
import os
import re
from pathlib import Path

import requests


def scope_for(directory):
    if not directory:
        raise ValueError('trajectory directory required')
    return hashlib.sha256(str(Path(directory).resolve()).encode()).hexdigest()


def parse_search_results(text):
    headers = list(re.finditer(r"(?m)^A (?:Google )?search for '([^\n]*)' found \d+ results:\s*$", text))
    results = []
    for i, h in enumerate(headers):
        body = text[h.end():headers[i + 1].start() if i + 1 < len(headers) else len(text)]
        matches = re.finditer(r'(?ms)^Title: ([^\n]*)\nLink: (\S+)(.*?)(?=\n\nTitle: |\Z)', body)
        for m in matches:
            raw = m.group(3).strip()
            # Keep all original snippet text; archive contains remaining fields.
            snippet = re.search(r'(?s)(?:^|\n)Snipptes:\s*(.*?)(?=\nSitelinks:\s*\n|\Z)', raw)
            results.append({'title': m.group(1), 'url': m.group(2),
                            'snippet': snippet.group(1).strip() if snippet else raw,
                            'query': h.group(1)})
    return results


def search(base, directory, query, limit=8, evidence_id=None, source_query=None):
    payload = {'scope': scope_for(directory), 'query': query, 'limit': limit}
    if evidence_id is not None:
        payload['evidence_id'] = evidence_id
    if source_query is not None:
        payload['source_query'] = source_query
    result = requests.post(base.rstrip('/') + '/search', json=payload, timeout=(3, 120))
    result.raise_for_status()
    return result.json()['hits']


def index(base, directory, evidence_id, text):
    entries = parse_search_results(text)
    return index_entries(base, directory, evidence_id, entries)


def index_entries(base, directory, evidence_id, entries):
    if not entries:
        return 0
    result = requests.post(base.rstrip('/') + '/index', json={
        'scope': scope_for(directory), 'evidence_id': evidence_id, 'entries': entries}, timeout=(3, 300))
    result.raise_for_status()
    return result.json()['indexed']


def index_visit(base, directory, evidence_id, text, goal=''):
    from inference.retrieval_experiment import split_chunks
    markers = list(re.finditer(r'(?m)^The useful information in (https?://\S+) for user goal ', text))
    sections = []
    if markers:
        if markers[0].start():
            sections.append(('', text[:markers[0].start()]))
        for i, match in enumerate(markers):
            sections.append((match.group(1), text[match.start():markers[i + 1].start() if i + 1 < len(markers) else len(text)]))
    else:
        sections = [('', text)]
    entries = [{'title': 'Archived visit evidence', 'url': url, 'snippet': c.text, 'query': goal}
               for url, body in sections for c in split_chunks(body, target=400, overlap=64)]
    return index_entries(base, directory, evidence_id, entries)


def enqueue(directory, evidence_id):
    folder = Path(directory) / 'vector-outbox'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (evidence_id + '.json')
    temp = folder / (evidence_id + f'.{os.getpid()}.tmp')
    temp.write_text(json.dumps({'evidence_id': evidence_id}), encoding='utf-8')
    os.replace(temp, path)
    return path


def retry_pending(base, directory, maximum=1):
    from inference import evidence_archive
    folder = Path(directory) / 'vector-outbox'
    if not folder.exists():
        return 0
    done = 0
    for pending in sorted(folder.glob('E*.json'))[:maximum]:
        evidence_id = json.loads(pending.read_text(encoding='utf-8'))['evidence_id']
        record = evidence_archive.load(directory, evidence_id)
        external = record['content'].split('\n\nLocal archived results for query:', 1)[0]
        index(base, directory, evidence_id, external)
        pending.unlink(missing_ok=True)
        done += 1
    return done
