"""Pluggable benchmark-specific recognition of final answer formats."""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class FinalAnswer:
    answer: str
    source: str


def _visible_without_fenced_code(content: str) -> str:
    # Unclosed thinking and code fences must not become visible final answers.
    visible = content.rsplit('</think>', 1)[-1].split('<think>', 1)[0]
    return re.sub(r'(?ms)^\s*(`{3,}|~{3,})[^\n]*\n.*?(?:^\s*\1\s*$|\Z)', '', visible)


def browsecomp_exact_answer(content: str) -> FinalAnswer | None:
    visible = _visible_without_fenced_code(content)
    if '<tool_call>' in visible or '</tool_call>' in visible:
        return None
    # Do not match block quotes, lists, embedded text, or fenced examples.
    pattern = r'(?im)^[ \t]*(?:\*\*)?Exact[ \t]+Answer[ \t]*(?::\*\*|\*\*[ \t]*:|:)[ \t]*(.*?)[ \t]*$'
    matches = [m.group(1).strip() for m in re.finditer(pattern, visible)]
    if not matches or any(not item for item in matches) or len(set(matches)) != 1:
        return None
    return FinalAnswer(matches[0], 'browsecomp_exact_answer')


def browsecomp_answer(content: str) -> FinalAnswer | None:
    visible = content.rsplit('</think>', 1)[-1].split('<think>', 1)[0]
    outside_fences = _visible_without_fenced_code(content)
    if '<tool_call>' in outside_fences or '</tool_call>' in outside_fences:
        return None
    fences = list(re.finditer(r'(?ms)^\s*(`{3,}|~{3,})[^\n]*\n.*?(?:^\s*\1\s*$|\Z)', visible))
    tag_matches = [m for m in re.finditer(
        r'<answer>((?:(?!<answer>|</answer>)[\s\S])*?)</answer>', visible)
        if not any(f.start() <= m.start() < f.end() for f in fences)]
    if tag_matches:
        tags = [match.group(1).strip() for match in tag_matches]
        if any(not answer for answer in tags) or len(set(tags)) != 1:
            return None
        without_tags = visible
        for match in reversed(tag_matches):
            without_tags = without_tags[:match.start()] + without_tags[match.end():]
        exact = browsecomp_exact_answer(without_tags)
        if exact and exact.answer != tags[0]:
            return None
        return FinalAnswer(tags[0], 'browsecomp_answer_tag')
    return browsecomp_exact_answer(content)


RECOGNIZERS = {'browsecomp': browsecomp_answer}


def recognize_benchmark_answer(content: str, profile: str, *, finish_reason: str | None,
                               has_tool_calls: bool) -> FinalAnswer | None:
    """Use an explicitly configured recognizer only for complete non-tool replies."""
    if not profile:
        return None
    recognizer = RECOGNIZERS.get(profile.lower())
    if recognizer is None:
        raise ValueError(f'Unknown final answer profile: {profile}')
    if has_tool_calls or finish_reason != 'stop':
        return None
    return recognizer(content)
