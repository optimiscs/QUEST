"""Small helpers shared by the cached and uncached webpage-summary paths."""
import json
import os


def parse_summary_with_retry(raw, call_server, messages, *, max_retries, parse_retries=1):
    """Parse the initial response and each retry; never cache an invalid response.

    `max_retries` is forwarded to the underlying model call; `parse_retries`
    controls additional model calls after invalid JSON, matching the original
    single format retry by default.
    """
    for attempt in range(parse_retries + 1):
        if isinstance(raw, str):
            raw = raw.replace('```json', '').replace('```', '').strip()
        try:
            return json.loads(raw), True
        except (json.JSONDecodeError, TypeError, ValueError):
            if attempt == parse_retries:
                return None, False
            raw = call_server(messages, max_retries=max_retries)
    return None, False


def visit_max_content_tokens():
    """Maximum cl100k tokens of webpage text; defaults to upstream's 95K."""
    raw = os.getenv("VISIT_MAX_CONTENT_TOKENS", "95000")
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("VISIT_MAX_CONTENT_TOKENS must be a positive integer") from exc
    if value <= 0:
        raise ValueError("VISIT_MAX_CONTENT_TOKENS must be a positive integer")
    return value
