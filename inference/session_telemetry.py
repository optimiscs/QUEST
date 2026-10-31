"""Per-request measurements; absent provider data is never inferred as zero."""
import time
from functools import lru_cache

from openai.lib.streaming.chat import ChatCompletionStreamState


@lru_cache(maxsize=64)
def context_capacity(base_url, model):
    """Read the endpoint's configured model limit; never assume a default."""
    import json
    from urllib.request import urlopen
    try:
        with urlopen(str(base_url).rstrip('/') + '/models', timeout=2) as response:
            models = json.load(response).get('data', [])
        for entry in models:
            if entry.get('id') == model:
                value = entry.get('max_model_len')
                if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                    return value
    except Exception:
        pass
    return None


def measured_completion(client, **kwargs):
    """Collect an OpenAI-compatible stream without changing its final message.

    TTFT starts immediately before the HTTP request and ends at the first
    content, reasoning, or tool-call delta, rather than at the first SSE frame.
    """
    start = time.monotonic()
    first = None
    accumulator = ChatCompletionStreamState()
    stream = client.chat.completions.create(**kwargs, stream=True,
                                            stream_options={"include_usage": True})
    try:
        for chunk in stream:
            if first is None:
                for choice in chunk.choices:
                    delta = choice.delta
                    if (getattr(delta, 'content', None) or getattr(delta, 'reasoning_content', None)
                            or getattr(delta, 'reasoning', None) or getattr(delta, 'tool_calls', None)):
                        first = time.monotonic() - start
                        break
            accumulator.handle_chunk(chunk)
        # get_final_completion() invokes SDK parsing and raises on a length
        # finish; the agent must receive truncated tool calls unchanged so it
        # can apply its own validation and recovery policy.
        result = accumulator.current_completion_snapshot
    finally:
        stream.close()
    return result, first
