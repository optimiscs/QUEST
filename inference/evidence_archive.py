"""Per-trajectory evidence storage and conservative, reversible compaction."""
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path


def store(directory, tool, arguments, content):
    if not directory or not isinstance(content, str):
        raise ValueError('Evidence requires a trajectory directory and textual content')
    payload = {'tool': tool, 'arguments': arguments, 'content': content}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    digest = hashlib.sha256(encoded).hexdigest()
    evidence_id = 'E' + digest
    folder = Path(directory) / 'evidence'
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / (evidence_id + '.json')
    if not destination.exists():
        fd, tmp = tempfile.mkstemp(prefix='.evidence-', dir=folder)
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, destination)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    # Verify what was committed before permitting the caller to omit content.
    if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
        raise IOError('Evidence archive verification failed')
    return evidence_id


def read(directory, evidence_id, offset=0, limit=12000):
    if not directory or not re.fullmatch(r'E[0-9a-f]{64}', str(evidence_id)):
        raise ValueError('Invalid evidence ID')
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise ValueError('offset must be a non-negative integer')
    data = (Path(directory) / 'evidence' / (evidence_id + '.json')).read_bytes()
    if hashlib.sha256(data).hexdigest() != evidence_id[1:]:
        raise IOError('Evidence archive hash mismatch')
    record = json.loads(data)
    content = record['content']
    end = min(len(content), offset + limit)
    return {'evidence_id': evidence_id, 'tool': record['tool'], 'arguments': record['arguments'],
            'offset': offset, 'next_offset': end if end < len(content) else None,
            'total_chars': len(content), 'content': content[offset:end]}


def load(directory, evidence_id):
    if not directory or not re.fullmatch(r'E[0-9a-f]{64}', str(evidence_id)):
        raise ValueError('Invalid evidence ID')
    data = (Path(directory) / 'evidence' / (evidence_id + '.json')).read_bytes()
    if hashlib.sha256(data).hexdigest() != evidence_id[1:]:
        raise IOError('Evidence archive hash mismatch')
    return json.loads(data)


def compact(tool, content, evidence_id, goal=''):
    """Choose verbatim content; full original remains retrievable from the archive."""
    header = f'[Archived {tool} result; evidence_id={evidence_id}. Use read_evidence to retrieve the original.]'
    if tool == 'search':
        # Keep every distinct snippet/title. Only remove identical complete result blocks.
        parts = re.split(r'(?=^Title: )', content, flags=re.M)
        seen = set(); kept = []
        for part in parts:
            if part.startswith('Title: ') and part in seen:
                continue
            if part.startswith('Title: '):
                seen.add(part)
            kept.append(part)
        return header + '\n' + ''.join(kept)
    if tool == 'visit':
        # Preserve original order and choose paragraphs by goal overlap; no LLM.
        chunks = re.split(r'\n\s*\n', content)
        terms = {x.lower() for x in re.findall(r'[\w]+', goal) if len(x) >= 3}
        ranked = sorted(range(len(chunks)), key=lambda i: (-sum(t in chunks[i].lower() for t in terms), i))
        selected = set(ranked[:8])
        if chunks:
            selected.add(0)
        return header + '\n' + '\n\n'.join(chunks[i] for i in sorted(selected))
    # Preserve error classification while retaining the full message in storage.
    first = next((line.strip() for line in content.splitlines() if line.strip()), 'Tool error')
    return header + '\n' + first[:500]
