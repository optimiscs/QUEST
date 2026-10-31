from types import SimpleNamespace

from openai.types.chat import ChatCompletionChunk

from inference.session_telemetry import measured_completion


def test_length_finish_keeps_partial_response_and_usage():
    base = {'id': 'c', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'x'}
    chunks = [
        {**base, 'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': 'partial'}, 'finish_reason': None}]},
        {**base, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'length'}]},
        {**base, 'choices': [], 'usage': {'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12,
                                           'prompt_tokens_details': {'cached_tokens': 4}}},
    ]
    class Stream:
        def __iter__(self):
            return iter(ChatCompletionChunk.model_validate(c) for c in chunks)
        def close(self):
            pass
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: Stream())))
    result, ttft = measured_completion(client, model='x', messages=[])
    assert result.choices[0].finish_reason == 'length'
    assert result.choices[0].message.content == 'partial'
    assert result.usage.prompt_tokens_details.cached_tokens == 4
    assert ttft is not None
