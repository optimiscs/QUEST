import pytest

from inference.final_answer import recognize_benchmark_answer


def recognize(text, **kwargs):
    return recognize_benchmark_answer(text, 'browsecomp', finish_reason=kwargs.get('finish_reason', 'stop'),
                                      has_tool_calls=kwargs.get('has_tool_calls', False))


@pytest.mark.parametrize('text', [
    'Explanation: Found it.\nExact Answer: Clare Wigfall\nConfidence: 90%',
    '**Exact Answer:** Clare Wigfall',
    '**Exact Answer**: Clare Wigfall',
    '```\nExact Answer: decoy\n```\nExact Answer: Clare Wigfall',
])
def test_browsecomp_exact_answer(text):
    answer = recognize(text)
    assert answer.answer == 'Clare Wigfall'
    assert answer.source == 'browsecomp_exact_answer'


@pytest.mark.parametrize('text,expected', [
    ('Evidence. <answer>Clare Wigfall</answer>', 'Clare Wigfall'),
    ('<think>hidden</think><answer>Clare Wigfall</answer>', 'Clare Wigfall'),
    ('<answer>Explanation: Evidence.\nExact Answer: Clare Wigfall</answer>',
     'Explanation: Evidence.\nExact Answer: Clare Wigfall'),
])
def test_browsecomp_tag_answer(text, expected):
    answer = recognize(text)
    assert answer.answer == expected
    assert answer.source == 'browsecomp_answer_tag'


@pytest.mark.parametrize('text', [
    'Exact Answer:',
    'Exact Answer: A\nExact Answer: B',
    '> Exact Answer: quoted example',
    '```\nExact Answer: example\n```',
    '```\nExact Answer: unfinished',
    '<think>Exact Answer: hidden</think>Still researching',
    '<think>Exact Answer: unfinished',
    '<tool_call>{"name":"search"}</tool_call>\nExact Answer: A',
    '```\n<answer>example</answer>\n```',
    '<answer>A</answer>\nExact Answer: B',
    '<answer>A</answer><answer>B</answer>',
])
def test_browsecomp_rejects_ambiguous_or_nonfinal_text(text):
    assert recognize(text) is None


def test_benchmark_is_opt_in_and_requires_completed_no_tool_response():
    text = 'Exact Answer: A'
    assert recognize_benchmark_answer(text, '', finish_reason='stop', has_tool_calls=False) is None
    assert recognize(text, finish_reason='length') is None
    assert recognize(text, finish_reason=None) is None
    assert recognize(text, has_tool_calls=True) is None
    assert recognize('<answer>A</answer>', finish_reason='length') is None
    assert recognize('<answer>A</answer>', has_tool_calls=True) is None
    with pytest.raises(ValueError, match='Unknown final answer profile'):
        recognize_benchmark_answer(text, 'unknown', finish_reason='stop', has_tool_calls=False)
