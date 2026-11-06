import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'inference'))
from openai.lib.streaming.chat import ChatCompletionStreamState
from openai.types.chat import ChatCompletionChunk
from session_telemetry import measured_completion


class Stream:
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False
    def __iter__(self):
        return iter(self.chunks)
    def close(self):
        self.closed = True


def test_stream_preserves_reasoning_tools_usage_and_all_logprobs():
    def chunk(delta, finish=None, probs=None):
        return ChatCompletionChunk(id='c', object='chat.completion.chunk', created=1, model='test',
            choices=[{'index': 0, 'delta': delta, 'finish_reason': finish, 'logprobs': probs}])
    prob = {'token': 'a', 'logprob': -0.1, 'bytes': [97], 'top_logprobs': []}
    chunks = [chunk({'role': 'assistant', 'reasoning': 'Reason ', 'reasoning_content': 'Reason '})]
    chunks += [chunk({'reasoning': 'a', 'reasoning_content': 'a'}, probs={'content': [prob]}) for _ in range(40)]
    chunks += [chunk({'content': 'Searching', 'tool_calls': [{'index': 0, 'id': 't', 'type': 'function',
                  'function': {'name': 'search', 'arguments': '{"query":'}}]}),
               chunk({'tool_calls': [{'index': 0, 'function': {'arguments': '["x"]}'}}]}, 'tool_calls')]
    chunks += [ChatCompletionChunk(id='c', object='chat.completion.chunk', created=1, model='test', choices=[],
                                  usage={'prompt_tokens': 10, 'completion_tokens': 50, 'total_tokens': 60})]
    baseline = ChatCompletionStreamState()
    for c in chunks:
        baseline.handle_chunk(c)
    stream = Stream(chunks)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: stream)))
    actual, first = measured_completion(client, model='test', messages=[])
    assert actual.model_dump() == baseline.current_completion_snapshot.model_dump()
    assert first is not None and first >= 0 and stream.closed
    assert len(actual.choices[0].logprobs.content) == 40


def test_length_finish_is_returned_without_sdk_parse_error():
    c = ChatCompletionChunk(id='c', object='chat.completion.chunk', created=1, model='test',
        choices=[{'index': 0, 'delta': {'role': 'assistant', 'content': '{partial'}, 'finish_reason': 'length'}])
    stream = Stream([c])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: stream)))
    result, _ = measured_completion(client, model='test')
    assert result.choices[0].finish_reason == 'length'
    assert result.choices[0].message.content == '{partial'
    assert stream.closed
