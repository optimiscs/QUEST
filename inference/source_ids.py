"""Task-scoped, persistent search source IDs. No model-generated URL mapping."""
import fcntl
import json
import os
from pathlib import Path
import re
import time
import uuid
import hashlib
from contextvars import ContextVar

_task_dir = ContextVar('source_id_task_dir', default=None)
_URL_BODY = r"(?:[^\s<>\"'`\\]|\\[/_()\[\]]|'(?=[\w/%~.-]))+"
URL_PATTERN = re.compile(r'(?:https?|ftp):(?:/|\\/){2}' + _URL_BODY + r'|www\.' + _URL_BODY, re.I)
ID_PATTERN = re.compile(r'(?<!\w)S[1-9][0-9]*(?!\w)')


def referenced_ids(value):
    return set(ID_PATTERN.findall(json.dumps(value, ensure_ascii=False)))


def _unescape_url(url):
    return re.sub(r'\\([/_()\[\]])', r'\1', url)


def _prose_url_end(raw):
    """Stop at Markdown delimiters, retaining balanced URL parentheses."""
    stack = []
    pairs = {')': '(', ']': '[', '}': '{'}
    escaped = False
    for i, char in enumerate(raw):
        if escaped:
            escaped = False
            continue
        if char == '\\':
            escaped = True
        elif char == '|':
            return i
        elif char in '([{':
            stack.append(char)
        elif char in pairs:
            if not stack or stack[-1] != pairs[char]:
                return i
            stack.pop()
    return len(raw)


def bind_task(task_dir):
    _task_dir.set(task_dir)


def compact_memory(messages):
    if not enabled():
        return messages
    return SourceRegistry(_task_dir.get()).context(messages, 'memory')


def enabled():
    return os.getenv('QUEST_SOURCE_IDS', '').lower() in {'1', 'true', 'yes'}


class SourceRegistry:
    def __init__(self, task_dir):
        if not task_dir:
            raise ValueError('Source IDs require a task log directory')
        self.root = Path(task_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'sources.json'
        self.provenance_path = self.root / 'source-provenance.json'

    def _read(self):
        return json.loads(self.path.read_text()) if self.path.exists() else {}

    def audit(self, event, **fields):
        with (self.root / 'source-id-events.jsonl').open('a') as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.write(json.dumps(dict(event=event, epoch=time.time(), **fields), ensure_ascii=False) + '\n')
            f.flush()

    def render(self, text):
        # Also replace URLs embedded in titles, snippets and query echoes.
        exact_urls = re.findall(r'(?m)^Link: (https?://\S+)', text)
        source_lines = {}
        sitelinks = False
        for line in text.splitlines():
            if line == 'Sitelinks:':
                sitelinks = True
            elif sitelinks and line.startswith('- '):
                match = re.match(r'- .*: (https?://\S+)', line)
                if match:
                    exact_urls.append(match.group(1))
                    source_lines[line] = match.group(1)
            else:
                sitelinks = False
        # Source fields are structured data: do not infer URL boundaries from
        # punctuation. Apostrophes and parentheses can be part of the URL.
        self.compact([], exact_urls=exact_urls, origin='search_result')
        reverse = {url: sid for sid, url in self._read().items()}
        rendered = re.sub(r'(?m)^(Link: )(https?://\S+)',
                          lambda m: m.group(1) + reverse[m.group(2)], text)
        rendered = ''.join(line.replace(source_lines[line.rstrip('\r\n')],
                                        reverse[source_lines[line.rstrip('\r\n')]])
                           if line.rstrip('\r\n') in source_lines else line
                           for line in rendered.splitlines(keepends=True))
        rendered = self.compact(rendered, origin='search_result')
        self.audit('search_render')
        return rendered

    def compact(self, value, exact_urls=(), *, allow_new=True, origin='unverified', unknown='raise', check_source_ids=True):
        """Replace web URLs recursively, including JSON-encoded tool arguments."""
        with (self.root / 'sources.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            sources = self._read()
            before = len(sources)
            provenance = json.loads(self.provenance_path.read_text()) if self.provenance_path.exists() else {}
            observed = set()
            reverse = {url: sid for sid, url in sources.items()}
            for url in exact_urls:
                if url not in reverse:
                    if not allow_new:
                        raise ValueError('assistant_introduced_unseen_url')
                    sid = 'S' + str(len(sources) + 1)
                    sources[sid] = url
                    reverse[url] = sid
                observed.add(reverse[url])

            def replace(match):
                raw = match.group()
                if _unescape_url(raw) in reverse:
                    observed.add(reverse[_unescape_url(raw)])
                    return reverse[_unescape_url(raw)]
                url = raw[:_prose_url_end(raw)].rstrip('.,;!?，。；！？”、')
                suffix = raw[len(url):]
                # A greedy match can include several adjacent Markdown links.
                # Process their URLs as separate sources without losing syntax.
                # Register the first URL before processing the suffix to retain
                # chronological source numbering.
                url = _unescape_url(url)
                if url not in reverse:
                    if not allow_new:
                        if unknown == 'mask':
                            return '[unregistered URL]' + URL_PATTERN.sub(replace, suffix)
                        raise ValueError('assistant_introduced_unseen_url')
                    sid = 'S' + str(len(sources) + 1)
                    sources[sid] = url
                    reverse[url] = sid
                observed.add(reverse[url])
                return reverse[url] + URL_PATTERN.sub(replace, suffix)

            def walk(obj):
                if isinstance(obj, str):
                    # Preserve JSON validity, including URLs used as object keys.
                    if obj.lstrip().startswith(('{', '[')):
                        try:
                            parsed = json.loads(obj)
                        except ValueError:
                            pass
                        else:
                            if isinstance(parsed, (dict, list)) and URL_PATTERN.search(obj):
                                return json.dumps(walk(parsed), ensure_ascii=False)
                    return URL_PATTERN.sub(replace, obj)
                if isinstance(obj, dict):
                    return {walk(k): walk(v) for k, v in obj.items()}
                if isinstance(obj, list):
                    return [walk(x) for x in obj]
                return obj

            result = walk(value)
            if not allow_new and check_source_ids:
                missing = referenced_ids(result) - sources.keys()
                if missing and unknown != 'mask':
                    raise ValueError('assistant_introduced_unknown_source_id')
                if missing:
                    def mask(obj):
                        if isinstance(obj, str):
                            return ID_PATTERN.sub(lambda m: '[unregistered source]' if m[0] in missing else m[0], obj)
                        if isinstance(obj, list): return [mask(x) for x in obj]
                        if isinstance(obj, dict): return {k: mask(v) for k, v in obj.items()}
                        return obj
                    result = mask(result)
            if len(sources) != before or not self.path.exists():
                temp = self.path.with_name('sources.' + uuid.uuid4().hex + '.tmp')
                try:
                    with temp.open('w') as f:
                        json.dump(sources, f, ensure_ascii=False, indent=2)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(temp, self.path)
                finally:
                    temp.unlink(missing_ok=True)
            if allow_new:
                for sid in observed:
                    entry = provenance.setdefault(sid, {'origins': []})
                    if origin not in entry['origins']: entry['origins'].append(origin)
                temp = self.provenance_path.with_name('provenance.' + uuid.uuid4().hex + '.tmp')
                try:
                    temp.write_text(json.dumps(provenance, ensure_ascii=False, indent=2))
                    os.replace(temp, self.provenance_path)
                finally:
                    temp.unlink(missing_ok=True)
            return result

    def assistant(self, value):
        """Shared offline/online validation: policy text cannot create sources."""
        return self.compact(value, allow_new=False)

    def validate_final(self, value):
        result = self.assistant(value)
        provenance = json.loads(self.provenance_path.read_text()) if self.provenance_path.exists() else {}
        for sid in referenced_ids(result):
            if not set(provenance.get(sid, {}).get('origins', [])) & {'search_result', 'page_observation'}:
                raise ValueError('citation_has_no_tool_observation:' + sid)
        return result

    def context(self, value, role):
        # History may contain an invalid model attempt. Mask it in subsequent
        # requests without converting it into a legitimate source. Raw history
        # remains available in the trajectory log for rejection/audit.
        def message(item):
            if item.get('role') == 'assistant':
                return self.compact(item, allow_new=False, unknown='mask')
            return self.compact(item, origin={'user': 'user_seed', 'tool': 'tool_context',
                                              'system': 'instruction'}.get(item.get('role'), 'unverified'))
        if role == 'policy' and isinstance(value, dict) and isinstance(value.get('messages'), list):
            result = dict(value, messages=[message(m) for m in value['messages']])
            if 'tools' in result: result['tools'] = self.compact(result['tools'], origin='instruction')
        elif role == 'memory':
            result = self.compact(value, allow_new=False, unknown='mask')
        else:
            result = self.compact(value, origin='user_seed' if role == 'user' else 'unverified')
        serialized = json.dumps(result, ensure_ascii=False)
        if URL_PATTERN.search(serialized):
            raise ValueError('Unresolved URL in model context')
        self.audit('context_checked', role=role, remaining_urls=0,
                   sha256=hashlib.sha256(serialized.encode()).hexdigest())
        return result

    def resolve(self, value):
        requested = [value] if isinstance(value, str) else value
        if not isinstance(requested, list) or not all(isinstance(x, str) for x in requested):
            raise ValueError('visit.url must contain source IDs or full URLs')
        sources = self._read()
        resolved = []
        for item in requested:
            sid = item.strip()
            if re.fullmatch(r'\[S[1-9][0-9]*\]', sid):
                sid = sid[1:-1]
            if sid in sources:
                resolved.append(sources[sid])
            elif item in sources.values():
                resolved.append(item)
            else:
                self.audit('visit_rejected', requested=requested, invalid=item)
                raise ValueError(f'Unknown source ID: {item}. Search first; use an observed source ID or a registered URL.')
        self.audit('visit_resolution', requested=requested, resolved=resolved)
        return resolved[0] if isinstance(value, str) else resolved
